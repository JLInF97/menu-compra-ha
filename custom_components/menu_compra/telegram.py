"""Router Telegram puro. Solo el sink de salida depende de Home Assistant.

Los nonces y la deduplicación son volátiles, limitados y con TTL: no constituyen
una segunda base de datos. No se reenvía una escritura tras perder su respuesta.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import secrets
import time
from typing import Any, Awaitable, Callable

from .api import BridgeClient, BridgeError, ChoiceRequired, identifier

HELP = ("Menú y Compra\n"
        "/menuc o /ayudamenu: panel y ayuda\n"
        "/compra: lista y botones\n"
        "/comprar [cantidad] nombre: añadir (precio 0 si es nuevo)\n"
        "/menu [DD/MM/YY]: semana actual o la que contiene esa fecha\n"
        "/plato FECHA comida|cena TEXTO: añade un plato independiente\n"
        "/editarplato ID TEXTO: cambia solo ese plato\n"
        "/quitarplato ID: solicita confirmación\n"
        "FECHA admite hoy, mañana o DD/MM/YY (también ISO anterior). Los botones caducan en 10 minutos "
        "y solo los puede usar quien abrió el panel. Para actualizarlo, pide /compra o /menu.")
COMMANDS = {"/menuc", "/ayudamenu", "/compra", "/comprar", "/menu", "/plato", "/editarplato", "/quitarplato"}


def plain(value: Any) -> str:
    # plain_text desactiva el parser: no hay que escapar Markdown/HTML (mostraría
    # las barras). Eliminar controles/bidi evita nombres que falsifiquen el panel.
    return "".join(c for c in str(value) if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127
                   and not (0x202A <= ord(c) <= 0x202E or 0x2066 <= ord(c) <= 0x2069)))


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Límite conservador en unidades UTF-16, sin cortar pares/emojis."""
    chunks, current, units = [], [], 0
    for char in plain(text):
        size = 2 if ord(char) > 0xFFFF else 1
        if units + size > limit:
            chunks.append("".join(current))
            current, units = [], 0
        current.append(char)
        units += size
    if current or not chunks:
        chunks.append("".join(current))
    return chunks


WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def display_date(day: date | str) -> str:
    day = date.fromisoformat(day) if isinstance(day, str) else day
    return f"{day.day:02d}/{day.month:02d}/{day.year % 100:02d}"


def parse_day(value: str, today: date) -> date:
    if value.lower() == "hoy":
        return today
    if value.lower() in ("mañana", "manana"):
        return today + timedelta(days=1)
    try:
        if re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{2}", value):
            day, month, year = map(int, value.split('/'))
            return date(2000 + year, month, day)
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return date.fromisoformat(value)
    except ValueError:
        pass
    raise ValueError("Fecha no válida: usa hoy, mañana o DD/MM/YY")


def parse_buy(args: list[str]) -> tuple[float, str]:
    if not args:
        raise ValueError("Uso: /comprar [cantidad] nombre")
    quantity = Decimal(1)
    # No interpretar «2% leche» como cantidad. Sí rechazar cantidades inválidas.
    if re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)", args[0]):
        try:
            quantity = Decimal(args.pop(0).replace(",", "."))
        except InvalidOperation:
            raise ValueError("Cantidad no válida") from None
    if not quantity.is_finite() or quantity <= 0 or quantity > 100000 or quantity.as_tuple().exponent < -3:
        raise ValueError("Cantidad: mayor que 0, hasta 100000 y con un máximo de 3 decimales")
    name = " ".join(args).strip()
    if not name or len(name) > 180:
        raise ValueError("Indica un nombre de producto de 1 a 180 caracteres")
    return float(quantity), name


def fingerprint(record: dict, kind: str) -> str:
    fields = {"row": ("product_id", "product_name", "unit", "supermarket_name"),
              "menu": ("date", "slot", "text", "dish_id"),
              "product": ("name", "supermarket_id", "unit")}[kind]
    return hashlib.sha256(json.dumps([record.get(k) for k in fields], ensure_ascii=False).encode()).hexdigest()


def event_payload(attrs: dict) -> dict:
    """Snapshot de campos simples, sin datetime ni objetos Telegram anidados.

    La plantilla nativa HA usa literal_eval: incluir attrs.date (datetime) haría
    que un dict completo se convirtiera en string, no en un objeto de servicio.
    Mantener esta proyección sincronizada con el blueprint.
    """
    bot = attrs.get("bot") or {}
    message = attrs.get("message") or {}
    if not isinstance(bot, Mapping) or not isinstance(message, Mapping):
        raise ValueError("Atributos Telegram no válidos")
    return {**{key: attrs.get(key) for key in ("event_type", "id", "chat_id", "user_id", "command", "args", "data", "message_thread_id")},
            "bot": {"config_entry_id": bot.get("config_entry_id"), "username": bot.get("username")},
            "message": {"message_thread_id": message.get("message_thread_id")}}


def shopping_rows(data: dict) -> list[dict]:
    return [row for group in data["groups"] for row in group["items"]]


@dataclass(frozen=True)
class Update:
    event_entity: str
    timestamp: str
    event_type: str
    attrs: dict
    bot_entry_id: str

    @property
    def chat(self) -> int | None:
        value = self.attrs.get("chat_id")
        return value if type(value) is int and value != 0 else None

    @property
    def actor(self) -> int | None:
        value = self.attrs.get("user_id")
        return value if type(value) is int and value > 0 else None

    @property
    def thread(self) -> int | None:
        value = self.attrs.get("message_thread_id")
        if value is None and isinstance(self.attrs.get("message"), dict):
            value = self.attrs["message"].get("message_thread_id")
        # HA 2026.11.1 usa ATTR_MSG = 'message' para callback_query.message.
        return value if type(value) is int and value > 0 else None


@dataclass
class Ticket:
    expires: float
    chat: int
    actor: int
    thread: int | None
    bot_entry_id: str
    op: str
    payload: dict


class TelegramRouter:
    TTL = 600
    DEDUP_TTL = 3600
    MAX_TICKETS = 4096
    MAX_UPDATES = 4096
    PAGE = 6

    def __init__(self, client: BridgeClient, event_entity: str, allowed_chats: set[int],
                 send: Callable[[Update, dict], Awaitable[None]], *,
                 today: Callable[[], date] = date.today, clock: Callable[[], float] = time.monotonic):
        self.client, self.event_entity = client, event_entity
        self.allowed_chats, self.send = set(allowed_chats), send
        self.today, self.clock = today, clock
        self._lock = asyncio.Lock()
        self._seen: OrderedDict[tuple, float] = OrderedDict()
        self._tickets: OrderedDict[str, Ticket] = OrderedDict()

    def _prune(self):
        now = self.clock()
        for store in (self._seen, self._tickets):
            while store:
                first = next(iter(store))
                expiry = store[first].expires if store is self._tickets else store[first]
                if expiry > now:
                    break
                store.popitem(last=False)

    def _button(self, update: Update, label: str, op: str, **payload) -> list[str]:
        # Op y argumentos solo viven en memoria; callback_data no admite acciones.
        nonce = "mc:" + secrets.token_urlsafe(12)
        self._tickets[nonce] = Ticket(self.clock() + self.TTL, update.chat, update.actor,
                                     update.thread, update.bot_entry_id, op, payload)
        while len(self._tickets) > self.MAX_TICKETS:
            self._tickets.popitem(last=False)
        return [plain(label).replace("\n", " ")[:60], nonce]

    async def _say(self, update: Update, message: str, keyboard: list | None = None):
        chunks = split_message(message)
        for index, chunk in enumerate(chunks):
            data = {"config_entry_id": update.bot_entry_id, "chat_id": update.chat,
                    "message": chunk, "parse_mode": "plain_text", "disable_web_page_preview": True}
            if update.thread is not None:
                data["message_thread_id"] = update.thread
            if keyboard and index == len(chunks) - 1:
                data["inline_keyboard"] = keyboard
            await self.send(update, data)

    async def handle(self, update: Update) -> bool:
        if (not self.event_entity or update.event_entity != self.event_entity
                or update.chat not in self.allowed_chats or update.actor is None
                or not update.bot_entry_id or not update.timestamp):
            return False
        if update.event_type == "telegram_callback":
            if not str(update.attrs.get("data", "")).startswith("mc:"):
                return False
        elif update.event_type == "telegram_command":
            command = str(update.attrs.get("command", ""))
            base, _, suffix = command.partition("@")
            bot_name = update.attrs.get("bot", {}).get("username", "")
            if base.lower() not in COMMANDS or (suffix and suffix.lower() != str(bot_name).lower()):
                return False
        else:
            return False
        async with self._lock:
            self._prune()
            # HA msgid: int de mensaje para comandos, str de query para callbacks.
            # También bloquear el timestamp aunque el msgid no exista.
            key = (update.bot_entry_id, update.chat, update.event_type,
                   str(update.attrs.get("id", update.attrs.get("message_id", update.timestamp))))
            if key in self._seen:
                return True
            self._seen[key] = self.clock() + self.DEDUP_TTL
            while len(self._seen) > self.MAX_UPDATES:
                self._seen.popitem(last=False)
            try:
                if update.event_type == "telegram_callback":
                    await self._callback(update)
                else:
                    await self._command(update)
            except ChoiceRequired as err:
                # Solo quick_add maneja elecciones: ninguna otra acción es segura
                # para convertir en una compra automáticamente.
                await self._say(update, str(err))
            except (BridgeError, ValueError) as err:
                await self._say(update, f"No se ha podido completar: {err}")
            return True

    async def _command(self, u: Update):
        command = u.attrs["command"].partition("@")[0].lower()
        args = u.attrs.get("args", [])
        if not isinstance(args, (list, tuple)) or any(not isinstance(arg, str) for arg in args):
            raise ValueError("Argumentos del comando no válidos")
        args = list(args)
        if command in ("/menuc", "/ayudamenu"):
            await self._say(u, HELP, [[self._button(u, "Compra", "shopping"),
                                      self._button(u, "Menú semanal", "menu_current")]])
        elif command == "/compra":
            await self._shopping(u)
        elif command == "/comprar":
            quantity, name = parse_buy(args)
            await self._buy(u, name, quantity)
        elif command == "/menu":
            if len(args) > 1:
                raise ValueError("Uso: /menu [DD/MM/YY]")
            day = self.today() if not args or args[0].lower() == "semana" else parse_day(args[0], self.today())
            await self._menu(u, day.isoformat())
        elif command == "/plato":
            if len(args) < 3 or args[1].lower() not in ("comida", "cena"):
                raise ValueError("Uso: /plato FECHA comida|cena TEXTO")
            day = parse_day(args[0], self.today())
            text = " ".join(args[2:]).strip()
            self._text(text)
            await self.client.add_menu(day.isoformat(), "lunch" if args[1].lower() == "comida" else "dinner", text)
            await self._say(u, "Plato añadido. Usa /menu para consultar el resultado.")
        elif command == "/editarplato":
            if len(args) < 2:
                raise ValueError("Uso: /editarplato ID TEXTO")
            entry_id, text = identifier(args[0]), " ".join(args[1:]).strip()
            self._text(text)
            entry = await self.client.menu_entry(entry_id)
            # Mostrar y confirmar la edición liga también comandos con ID a la
            # identidad actual, evitando ejecutar una sugerencia de panel antiguo.
            await self._confirm(u, f"¿Cambiar el plato #{entry_id} ({display_date(entry['date'])}, {'comida' if entry['slot'] == 'lunch' else 'cena'})\n{entry['text']}\npor:\n{text}?",
                                "edit_menu", entry_id=entry_id, identity=fingerprint(entry, "menu"), text=text)
        elif command == "/quitarplato":
            if len(args) != 1:
                raise ValueError("Uso: /quitarplato ID")
            entry = await self.client.menu_entry(identifier(args[0]))
            await self._confirm(u, f"¿Quitar únicamente este plato?\n{display_date(entry['date'])} · {entry['text']}",
                                "remove_menu", entry_id=entry["id"], identity=fingerprint(entry, "menu"))

    @staticmethod
    def _text(text):
        if not text or len(text) > 1000:
            raise ValueError("El plato debe tener de 1 a 1000 caracteres")

    async def _buy(self, u, name, quantity, product_id=None):
        try:
            await self.client.quick_add(name, quantity, product_id)
        except ChoiceRequired as err:
            matches = err.data.get("matches", [])
            if not matches:
                raise BridgeError("No hay coincidencias seleccionables; vuelve a buscar.") from None
            # Hasta 20 por panel y páginas: nunca truncar alternativas en silencio.
            await self._choices(u, matches, name, quantity, 0)
            return
        await self._say(u, f"Añadido: {quantity:g} × {name}. Consulta /compra.")

    async def _choices(self, u, matches, name, quantity, page):
        start = page * 20
        keys = []
        for product in matches[start:start + 20]:
            keys.append([self._button(u, f"{product['name']} · {product['supermarket_name']} (#{product['id']})", "choose",
                                      product_id=product["id"], identity=fingerprint(product, "product"), name=name, quantity=quantity)])
        nav = []
        for label, target in (("Anteriores", page - 1), ("Más opciones", page + 1)):
            if 0 <= target * 20 < len(matches):
                nav.append(self._button(u, label, "choices", matches=matches, name=name, quantity=quantity, page=target))
        if nav:
            keys.append(nav)
        await self._say(u, "Hay varios productos. Elige el supermercado exacto (no se ha añadido nada):", keys)

    async def _shopping(self, u, page=0):
        data = await self.client.shopping()
        rows = shopping_rows(data)
        page = max(0, min(page, max(0, (len(rows) - 1) // self.PAGE)))
        lines = [f"Compra: {data['checked_count']}/{data['count']} comprados · página {page + 1}"]
        keys = []
        for row in rows[page * self.PAGE:(page + 1) * self.PAGE]:
            item_id, identity = row["id"], fingerprint(row, "row")
            lines.append(f"{'☑' if row['checked'] else '☐'} #{item_id} · {row['quantity']} {row['unit']} · {row['product_name']} · {row['supermarket_name']}")
            keys.append([self._button(u, f"#{item_id} {'Desmarcar' if row['checked'] else 'Marcar'}", "check", item_id=item_id, identity=identity, checked=not row["checked"]),
                         self._button(u, "−1", "adjust", item_id=item_id, identity=identity, delta=-1),
                         self._button(u, "+1", "adjust", item_id=item_id, identity=identity, delta=1),
                         self._button(u, "Quitar", "ask_row", item_id=item_id, identity=identity)])
        nav = []
        for label, target in (("◀", page - 1), ("▶", page + 1)):
            if 0 <= target * self.PAGE < len(rows):
                nav.append(self._button(u, label, "shopping", page=target))
        if nav:
            keys.append(nav)
        keys.append([self._button(u, "Limpiar comprados", "ask_clear", checked_only=True),
                     self._button(u, "Vaciar compra", "ask_clear", checked_only=False)])
        await self._say(u, "\n".join(lines) if rows else "La compra está vacía.", keys)

    async def _menu(self, u, day):
        selected = date.fromisoformat(day)
        monday = selected - timedelta(days=selected.weekday())
        data = await self.client.menu(monday.isoformat())
        days = [monday + timedelta(days=n) for n in range(min(7, (date.max - monday).days + 1))]
        lines = [f"Semana del {display_date(monday)} al {display_date(days[-1])}"]
        for current in days:
            weekday = WEEKDAYS[current.weekday()]
            lines.extend(['', f"{weekday} · {display_date(current)}", '-' * len(weekday)])
            for slot, label in (("lunch", "Comida"), ("dinner", "Cena")):
                entries = sorted((entry for entry in data['entries'] if entry['date'] == current.isoformat() and entry['slot'] == slot),
                                 key=lambda entry: (entry.get('position', 0), entry['id']))
                if not entries:
                    lines.append(f"{label}: Sin planificar")
                elif len(entries) == 1:
                    lines.append(f"{label}: {entries[0]['text']}")
                else:
                    lines.append(f"{label}:")
                    lines.extend(f"  • {entry['text']}" for entry in entries)
        navigation = []
        for label, offset in (("◀ Semana anterior", -7), ("Semana siguiente ▶", 7)):
            try:
                target = (monday + timedelta(days=offset)).isoformat()
            except OverflowError:
                continue
            navigation.append(self._button(u, label, "menu", day=target))
        keys = [navigation] if navigation else []
        keys.append([self._button(u, "Semana actual", "menu_current")])
        today = self.today()
        add_day = today.isoformat() if monday <= today <= days[-1] else monday.isoformat()
        keys.append([self._button(u, "Añadir plato", "help_add", day=add_day),
                     self._button(u, "Gestionar platos", "menu_tools", day=monday.isoformat())])
        await self._say(u, '\n'.join(lines), keys)

    async def _menu_tools(self, u, day, page=0):
        selected = date.fromisoformat(day)
        monday = selected - timedelta(days=selected.weekday())
        data = await self.client.menu(monday.isoformat())
        entries = sorted(data['entries'], key=lambda entry: (entry['date'], 0 if entry['slot'] == 'lunch' else 1, entry.get('position', 0), entry['id']))
        page = max(0, min(page, max(0, (len(entries) - 1) // self.PAGE)))
        lines = [f"Gestionar platos · semana del {display_date(monday)} · página {page + 1}"]
        keys = []
        for entry in entries[page * self.PAGE:(page + 1) * self.PAGE]:
            entry_id = entry["id"]
            lines.append(f"#{entry_id} · {display_date(entry['date'])} · {'comida' if entry['slot'] == 'lunch' else 'cena'}: {entry['text']}")
            payload = {"entry_id": entry_id, "identity": fingerprint(entry, "menu")}
            keys.append([self._button(u, f"Editar #{entry_id}", "help_edit", **payload),
                         self._button(u, f"Quitar #{entry_id}", "ask_menu", **payload)])
        if not entries:
            lines.append("No hay platos. Puedes añadir varios en cada franja.")
        pages = []
        for label, target in (("Platos anteriores", page - 1), ("Más platos", page + 1)):
            if 0 <= target * self.PAGE < len(entries):
                pages.append(self._button(u, label, "menu_tools", day=monday.isoformat(), page=target))
        if pages:
            keys.append(pages)
        keys.append([self._button(u, "Volver al menú semanal", "menu", day=monday.isoformat())])
        await self._say(u, "\n".join(lines), keys)

    async def _confirm(self, u, prompt, op, **payload):
        await self._say(u, prompt, [[self._button(u, "Sí, confirmar", op, **payload),
                                   self._button(u, "Cancelar", "cancel")]])

    async def _row(self, item_id, identity):
        row = next((row for row in shopping_rows(await self.client.shopping()) if row["id"] == item_id), None)
        if row is None or fingerprint(row, "row") != identity:
            raise ValueError("La línea ya no es la misma. Abre /compra y utiliza sus botones nuevos")
        return row

    async def _entry(self, entry_id, identity):
        entry = await self.client.menu_entry(entry_id)
        if fingerprint(entry, "menu") != identity:
            raise ValueError("El plato ha cambiado. Abre /menu antes de actuar")
        return entry

    @staticmethod
    def _clear_identity(rows):
        # Confirmar exactamente el conjunto/estado que el usuario ha visto.
        return hashlib.sha256(json.dumps(sorted((r["id"], fingerprint(r, "row"), r["checked"], str(r["quantity"])) for r in rows)).encode()).hexdigest()

    async def _callback(self, u):
        nonce = str(u.attrs["data"])
        ticket = self._tickets.get(nonce)
        if ticket is None or ticket.expires <= self.clock():
            await self._say(u, "Este botón ha caducado o ya se utilizó. Abre /menuc para empezar de nuevo.")
            return
        if (ticket.chat, ticket.actor, ticket.thread, ticket.bot_entry_id) != (u.chat, u.actor, u.thread, u.bot_entry_id):
            await self._say(u, "Este botón pertenece a otro usuario, chat o tema. Abre tu propio /menuc.")
            return
        # Consumir antes de I/O. Un fallo de envío o respuesta no resucita la acción.
        del self._tickets[nonce]
        p, op = ticket.payload, ticket.op
        if op == "cancel":
            await self._say(u, "Cancelado.")
        elif op == "shopping":
            await self._shopping(u, **p)
        elif op == "menu":
            await self._menu(u, **p)
        elif op == "menu_current":
            await self._menu(u, self.today().isoformat())
        elif op == "menu_tools":
            await self._menu_tools(u, **p)
        elif op == "help_add":
            await self._say(u, f"Añade un plato con:\n/plato {display_date(p['day'])} comida TEXTO\no\n/plato {display_date(p['day'])} cena TEXTO\nNo sustituye los platos existentes.")
        elif op == "help_edit":
            await self._entry(**p)
            await self._say(u, f"Para editar solo este plato:\n/editarplato {p['entry_id']} TEXTO\nSe pedirá confirmar el texto actual y el nuevo.")
        elif op == "choices":
            await self._choices(u, **p)
        elif op == "choose":
            product = await self.client.product(p["product_id"])
            if fingerprint(product, "product") != p["identity"]:
                raise ValueError("El producto ha cambiado. Repite /comprar para elegir de nuevo")
            await self._buy(u, p["name"], p["quantity"], p["product_id"])
        elif op in ("check", "adjust", "ask_row", "remove_row"):
            row = await self._row(p["item_id"], p["identity"])
            if op == "ask_row":
                await self._confirm(u, f"¿Quitar de la compra {row['product_name']}? El catálogo no cambia.", "remove_row", **p)
                return
            if op == "check":
                await self.client.update_shopping(p["item_id"], checked=p["checked"])
            elif op == "adjust":
                await self.client.adjust_shopping(p["item_id"], p["delta"])
            else:
                await self.client.remove_shopping(p["item_id"])
            await self._shopping(u)
        elif op in ("ask_menu", "remove_menu", "edit_menu"):
            entry = await self._entry(p["entry_id"], p["identity"])
            if op == "ask_menu":
                await self._confirm(u, f"¿Quitar solo este plato?\n{display_date(entry['date'])} · {entry['text']}", "remove_menu", **p)
                return
            if op == "edit_menu":
                await self.client.update_menu(p["entry_id"], entry["date"], entry["slot"], p["text"])
            else:
                await self.client.remove_menu(p["entry_id"])
            await self._say(u, "Plato actualizado." if op == "edit_menu" else "Plato eliminado.")
        elif op in ("ask_clear", "clear"):
            rows = shopping_rows(await self.client.shopping())
            if p["checked_only"]:
                rows = [r for r in rows if r["checked"]]
            identity = self._clear_identity(rows)
            if op == "ask_clear":
                await self._confirm(u, f"¿{'Limpiar comprados' if p['checked_only'] else 'Vaciar toda la compra'}?\nSe eliminarán {len(rows)} líneas. El catálogo y el menú no cambian.",
                                    "clear", checked_only=p["checked_only"], identity=identity)
                return
            if identity != p["identity"]:
                raise ValueError("La compra ha cambiado desde la confirmación; abre /compra de nuevo")
            await self.client.clear_shopping(p["checked_only"])
            await self._shopping(u)
