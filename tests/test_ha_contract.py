"""Contrato estático de wrappers/blueprint; NO prueba un runtime HA.

Si probatio no es importable en Python 3.11 se omite solo su prueba de schemas.
El resto valida archivos, AST y plantillas con Jinja real y estados fixture.
"""
import ast
from datetime import date, datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[1]
COMPONENT = Path(os.environ.get('MENU_COMPRA_TEST_COMPONENT_DIR', str(ROOT / "custom_components" / "menu_compra")))
EXPECTED_SERVICES = {"get_shopping", "get_menu", "get_products", "add_shopping", "update_shopping", "adjust_shopping",
                     "remove_shopping", "clear_shopping", "add_menu", "update_menu", "remove_menu", "add_menu_batch", "duplicate_week", "telegram_update"}


class BlueprintLoader(yaml.SafeLoader):
    pass


BlueprintLoader.add_constructor("!input", lambda loader, node: {"input": loader.construct_scalar(node)})


def blueprint():
    return yaml.load((ROOT / "blueprints/automation/menu_compra/telegram.yaml").read_text(encoding="utf-8"), Loader=BlueprintLoader)


def test_manifest_translations_services_blueprint_are_consistent():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "menu_compra" and manifest["version"] == "1.0.0"
    assert manifest["config_flow"] is True and manifest["single_config_entry"] is True
    assert manifest["requirements"] == [] and manifest["after_dependencies"] == ["telegram_bot"]
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert strings == json.loads((COMPONENT / "translations/es.json").read_text(encoding="utf-8"))
    assert set(strings["config"]["step"]) == {"user", "reconfigure", "reauth_confirm"}
    assert "init" in strings["options"]["step"]
    descriptions = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    assert set(descriptions) == EXPECTED_SERVICES
    for value in descriptions.values():
        assert value["fields"]["config_entry_id"]["required"] is True
        assert value["fields"]["config_entry_id"]["selector"] == {"config_entry": {"integration": "menu_compra"}}
        assert value["response"]["optional"] is True
    bp = blueprint()
    assert bp["blueprint"]["homeassistant"]["min_version"] == "2026.11.1"
    assert bp["triggers"][0]["trigger"] == "state"
    assert bp["actions"][0]["action"] == "menu_compra.telegram_update"
    assert bp["actions"][0]["data"]["config_entry_id"] == {"input": "menu_compra_entry"}
    assert bp["blueprint"]["input"]["telegram_event"]["selector"]["entity"]["filter"][0] == {"domain": "event", "integration": "telegram_bot"}
    assert "trigger.to_state.attributes" in bp["actions"][0]["data"]["event_data"]


def test_wrappers_compile_and_use_2026_interfaces_without_legacy_bus():
    for path in COMPONENT.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for name in ("config_flow.py", "services.py"):
        source = (COMPONENT / name).read_text(encoding="utf-8")
        imports = [node.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.alias)]
        assert "probatio" in imports and "voluptuous" not in imports
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    assert 'vol.Secret("api_key")' in flow and "TextSelectorType.PASSWORD" in flow
    assert "async_step_reconfigure" in flow and "async_step_reauth_confirm" in flow
    service = (COMPONENT / "services.py").read_text(encoding="utf-8")
    assert "registry_entry.config_entry_id" in service
    assert "bot_entry.domain" in service and 'registry_entry.platform != "telegram_bot"' in service
    assert "SupportsResponse.OPTIONAL" in service
    assert "async_listen" not in service
    assert "telegram_command" not in blueprint()["triggers"][0].values()


@pytest.mark.parametrize("before,after,kind,expected", [
    (None, "2026-11-16T10:00:01+00:00", "telegram_command", False),
    ("unknown", "2026-11-16T10:00:01+00:00", "telegram_command", False),
    ("unavailable", "2026-11-16T10:00:01+00:00", "telegram_callback", False),
    ("2026-11-16T10:00:00+00:00", "2026-11-16T10:00:00+00:00", "telegram_command", False),
    ("2026-11-16T10:00:02+00:00", "2026-11-16T10:00:01+00:00", "telegram_command", False),
    ("2026-11-16T10:00:00+00:00", "2026-11-16T10:00:01+00:00", "telegram_text", False),
    ("2026-11-16T10:00:00+00:00", "2026-11-16T10:00:01+00:00", "telegram_sent", False),
    ("2026-11-16T10:00:00+00:00", "2026-11-16T10:00:01+00:00", "telegram_command", True),
    ("2026-11-16T10:00:00+00:00", "2026-11-16T10:00:01+00:00", "telegram_callback", True),
])
def test_blueprint_template_only_new_timestamps_with_previous_state(before, after, kind, expected):
    jinja = pytest.importorskip("jinja2")
    def as_timestamp(value, default=None):
        try:
            return datetime.fromisoformat(value).timestamp()
        except (ValueError, TypeError):
            return default
    env = jinja.Environment(undefined=jinja.StrictUndefined)
    env.globals["as_timestamp"] = as_timestamp
    def state_fixture(text):
        return SimpleNamespace(state=text, attributes={"event_type": kind})
    trigger = SimpleNamespace(from_state=state_fixture(before) if before else None, to_state=state_fixture(after))
    result = env.from_string(blueprint()["conditions"][0]["value_template"]).render(trigger=trigger)
    assert (result.strip() == "True") is expected


def test_real_probatio_service_schemas_with_explicit_cv_fixture_no_ha_stubs():
    # No se carga services.py como integración ni se añade sys.modules['homeassistant'].
    # Se ejecuta su fábrica de schemas con probatio REAL y solo cv es una fixture
    # mínima declarada. La interfaz cv.date/string/boolean se contrasta en fuentes HA.
    try:
        import probatio as vol
    except (ImportError, SyntaxError):
        pytest.skip("probatio 0.13.0 requiere Python >=3.12; ejecutar también con Python 3.14")
    source = ast.parse((COMPONENT / "services.py").read_text(encoding="utf-8"))
    selected = [node for node in source.body if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"ID", "TEXT", "NAME", "CONFIRM", "SLOT"} for t in node.targets))
                or (isinstance(node, ast.FunctionDef) and node.name in {"whole_number", "schemas"})]
    cv_fixture = SimpleNamespace(string=vol.Coerce(str), boolean=bool, date=lambda v: date.fromisoformat(str(v)), entity_id=vol.Coerce(str))
    namespace = {"vol": vol, "cv": cv_fixture}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<actual-service-schema-factory-with-cv-fixture>", "exec"), namespace)
    schemas = namespace["schemas"]()
    assert set(schemas) == EXPECTED_SERVICES
    assert schemas["adjust_shopping"]({"config_entry_id": "entry", "item_id": 2, "delta": "-1"})["delta"] == -1
    assert schemas["get_menu"]({"config_entry_id": "entry", "week": "2026-11-16"})["week"] == date(2026, 11, 16)
    for invalid in (1.5, True, '01', '1.5', 9223372036854775808):
        with pytest.raises(vol.Invalid):
            schemas['adjust_shopping']({'config_entry_id': 'entry', 'item_id': invalid, 'delta': 1})
    for invalid in (1.5, True):
        with pytest.raises(vol.Invalid):
            schemas['adjust_shopping']({'config_entry_id': 'entry', 'item_id': 2, 'delta': invalid})
        with pytest.raises(vol.Invalid):
            schemas['add_shopping']({'config_entry_id': 'entry', 'name': 'Producto', 'price_cents': invalid})
    for name in EXPECTED_SERVICES:
        with pytest.raises(vol.Invalid):
            schemas[name]({})
    with pytest.raises(vol.Invalid):
        schemas["clear_shopping"]({"config_entry_id": "entry", "checked_only": False, "confirm": False})
    with pytest.raises(vol.Invalid):
        schemas["add_menu"]({"config_entry_id": "entry", "date": "2026-11-16", "slot": "breakfast", "text": "Pan"})


def test_real_probatio_config_form_factory_with_selector_fixture_no_ha_stubs():
    try:
        import probatio as vol
    except (ImportError, SyntaxError):
        pytest.skip("probatio 0.13.0 requiere Python >=3.12; ejecutar también con Python 3.14")
    source = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
    selected = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "form_schema"]
    # Selectors fixture: solo identidad de strings. No representa el frontend HA.
    selector_fixture = SimpleNamespace(
        TextSelector=lambda *a, **k: str, TextSelectorConfig=dict,
        TextSelectorType=SimpleNamespace(URL="url", PASSWORD="password"),
        EntitySelector=lambda *a, **k: str, EntitySelectorConfig=dict)
    namespace = {"vol": vol, "selector": selector_fixture, "DEFAULT_URL": "http://local-menu-compra:8099"}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<actual-config-schema-factory-with-selector-fixture>", "exec"), namespace)
    factory = namespace["form_schema"]
    current = {"api_key": "secret-fixture-not-a-real-token", "allowed_chats": [-100123]}
    result = factory(current)({"base_url": "http://local-menu-compra:8099", "allowed_chats": ""})
    assert "api_key" not in result and "telegram_event_entity" not in result
    with pytest.raises(vol.Invalid):
        factory({}, initial=True)({"base_url": "http://local-menu-compra:8099", "allowed_chats": ""})
    result = factory({}, initial=True)({"base_url": "http://local-menu-compra:8099", "api_key": "fixture", "allowed_chats": ""})
    assert result["api_key"] == "fixture"
    # Borrar/desmarcar la allowlist no debe reinsertar el antiguo grupo por default.
    cleared = factory(current)({"base_url": "http://local-menu-compra:8099"})
    assert not cleared.get("allowed_chats")


@pytest.mark.parametrize("kind", ["telegram_command", "telegram_callback"])
def test_blueprint_snapshot_survives_native_literal_parse_with_datetime_attrs(kind):
    jinja = pytest.importorskip("jinja2")
    from test_ha_support import pure_module
    tg = pure_module("telegram")
    attrs = {"event_type": kind, "id": "123456", "chat_id": -100987, "user_id": 77,
             "command": "/comprar", "args": ["2", "Pan's <b> & café"], "data": "mc:nonce-fixture",
             "date": datetime(2026, 11, 16, 10, 0), "message_thread_id": 45,
             "bot": {"config_entry_id": "entry-bot", "username": "mi_bot", "id": 123},
             "message": {"message_thread_id": 45, "date": datetime(2026, 11, 16, 10, 0)}}
    env = jinja.Environment(undefined=jinja.StrictUndefined)
    trigger = SimpleNamespace(to_state=SimpleNamespace(attributes=attrs))
    rendered = env.from_string(blueprint()["actions"][0]["data"]["event_data"]).render(trigger=trigger)
    payload = ast.literal_eval(rendered.strip())
    assert isinstance(payload, dict) and payload == tg.event_payload(attrs)
    assert "date" not in payload and "date" not in payload["message"]
    assert payload["message"]["message_thread_id"] == 45
