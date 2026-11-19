# Menú y Compra 1.0.0 · Home Assistant y Telegram

## Actualizar desde app 0.6.0 e integración 0.6.0/0.6.1

Haz copia de seguridad. Primero sustituye `/config/custom_components/menu_compra/` con el ZIP `menu-compra-ha-1.0.0-integracion.zip` y reinicia Core. Esta integración admite app0.6.0 y app1.0.0, por lo que después puedes sustituir los archivos de la app y actualizarla a1.0.0 con su ZIP instalador. No desinstales, no borres /data, no cambies su clave ni recrees integración o automatización. El blueprint no ha cambiado. La versión estable consolida el comportamiento aprobado y añade el icono elegido; futuras funciones serán evolutivos.

`/menu` muestra por defecto la semana actual completa de lunes a domingo. Cada día tiene encabezado, fecha **DD/MM/YY**, guiones y Comida/Cena; se muestran también los huecos vacíos. Usa los botones Semana anterior / Semana siguiente / Semana actual. La lectura no se pagina por platos; si supera el límite de Telegram se divide en varios mensajes sin omitirlos. **Gestionar platos** abre aparte las acciones de editar/quitar, manteniendo la vista semanal limpia.

Integración local para **Home Assistant Core 2026.11.1**. Reutiliza la integración **Telegram Bot que ya tienes**; no crea otro bot, no añade polling de Telegram ni necesita su token. La aplicación sigue funcionando por Ingress aunque desactives esta conexión.

## 1. Instalar o actualizar la aplicación

**Origen de la instalación y URL del bridge:** desde `https://github.com/JLInF97/menu-compra-ha`, usa `http://1872afc9-menu-compra:8099`. `http://local-menu-compra:8099` es solo para la instalación local manual (la app conserva esa sugerencia). El prefijo se deriva de la URL exacta del repositorio; ramas u otras variantes pueden cambiarlo. Comprueba el identificador de tu app en el Supervisor si es diferente.

No cambies de instalación local a repositorio como si fuera una actualización: son apps distintas con datos separados. Para migrar, exporta/restaura JSON y configura en la integración la URL y la clave de la nueva app; no se transfieren las credenciales con el JSON.

1. Exporta una copia JSON de los datos y conserva también una copia de seguridad de Home Assistant que incluya la aplicación.
2. Instala/actualiza la aplicación local con el **instalador de la app 1.0.0**, no con el ZIP de integración HA. Conserva el slug `menu_compra` y sus datos; no desinstales para actualizar. Las instalaciones recientes usan `/local_apps/menu_compra` (recurso Samba `local_apps`); las antiguas pueden usar `/addons/menu_compra` (`addons`). No instales ambas copias.
3. Actualiza la tienda de aplicaciones locales, instala/actualiza y arranca. Comprueba versión 1.0.0 y que menú, compra y catálogo siguen presentes desde Ingress.
4. Abre **Datos y ajustes → Conectar con Home Assistant**. Activa la conexión y pulsa **Mostrar clave** solo cuando vayas a copiarla. La URL interna sugerida es `http://local-menu-compra:8099`.

No publiques el puerto 8099, no actives `host_network` y no uses la URL larga de Ingress en la integración. No hacen falta permisos de Supervisor API ni de Core API. La clave bridge es diferente de todas las claves HA y del token Telegram.

## 2. Copiar el ZIP HA y reiniciar

El **ZIP de integración HA**, separado del instalador de la app, contiene `custom_components/`, `blueprints/` y esta guía. Copia su contenido dentro de `/config` de Home Assistant, fusionando carpetas:

```text
/config/custom_components/menu_compra/__init__.py
/config/custom_components/menu_compra/manifest.json
/config/custom_components/menu_compra/config_flow.py
/config/custom_components/menu_compra/api.py
/config/custom_components/menu_compra/actions.py
/config/custom_components/menu_compra/settings.py
/config/custom_components/menu_compra/services.py
/config/custom_components/menu_compra/telegram.py
/config/custom_components/menu_compra/services.yaml
/config/custom_components/menu_compra/strings.json
/config/custom_components/menu_compra/translations/es.json
/config/blueprints/automation/menu_compra/telegram.yaml
```

Evita una carpeta extra como `/config/menu-compra-ha-1.0.0/custom_components`. Reinicia **Home Assistant**, no solo la aplicación. Es una integración personalizada, no HACS ni una integración oficial del catálogo.

## 3. Añadir la integración

En **Ajustes → Dispositivos y servicios → Añadir integración**, busca **Menú y Compra**:

- **URL interna**: `http://local-menu-compra:8099` en HA OS con la aplicación local. En una instalación diferente usa el origen HTTP/HTTPS accesible desde HA, con su puerto; sin ruta, parámetros, credenciales ni fragmentos.
- **Clave bridge**: pega la clave completa de Datos y ajustes. El campo es de contraseña y se valida contra `/bridge/v1/health`.
- **Entidad de eventos Telegram**: opcional. Selecciona `event.…` de tu integración Telegram Bot existente, no una entidad notify.
- **Chats permitidos**: IDs numéricos separados por comas. **Vacío desactiva Telegram**, aunque hayas seleccionado una entidad. Por ejemplo, `123456789, -1001234567890` son IDs de ejemplo, no valores que debas copiar.

Solo se admite **una entrada** Menú y Compra; las acciones exigen además `config_entry_id` explícito. No hay sensores ni sincronización periódica: las consultas leen el backend al pedirlas. La entrada ofrece **Configurar/Opciones** y **Reconfigurar** para URL, clave, entidad y chats. En opciones/reconfiguración, deja la contraseña vacía para conservarla; nunca se precarga en el formulario. Para apagar Telegram, vacía los chats (y, opcionalmente, elimina la entidad).

### Chats y grupos

Obtén el `chat_id` desde un evento recibido por la entidad Telegram en Herramientas para desarrolladores → Estados, o desde la configuración existente del bot. No confundas `user_id` con `chat_id`:

- En chat privado suelen coincidir.
- Los grupos/supergrupos usan normalmente IDs **negativos** y deben añadirse tal cual.
- La integración **Telegram Bot** también debe permitir ese chat en su propia configuración.
- Permitir un grupo permite iniciar comandos a **todos sus miembros**. No es una lista de usuarios autorizados. Los botones sí quedan ligados a la persona que abrió el panel, al chat, al bot y al tema. Si el grupo no es de confianza, usa chat privado.
- En grupos puedes escribir `/menuc@NombreDeTuBot`. Un sufijo dirigido a otro bot se ignora.
- En temas de supergrupos, se conserva `message_thread_id`, también al pulsar un botón.

## 4. Crear la automatización del blueprint

1. Ve a **Ajustes → Automatizaciones y escenas → Blueprints** y recarga/importa el blueprint local **Menú y Compra · Telegram (Core 2026.11.1)** si aún no aparece.
2. Crea una automatización con él.
3. Elige la **entrada de Menú y Compra** y la **misma entidad event de Telegram** configurada en la integración.
4. Guarda y activa **una sola automatización** de este blueprint por entrada.

Usa cambios de estado de `event.…`, cuyo estado es un timestamp. No usa los antiguos triggers de bus `telegram_command` o `telegram_callback`. Exige estado anterior existente/válido, timestamp nuevo y `event_type` command/callback. Descarta restauraciones, eventos de texto, envíos del bot y cambios de atributos sin timestamp nuevo. El primer evento después de que la entidad esté `unknown`/`unavailable` puede servir solo para inicializar el timestamp: vuelve a escribir `/menuc` si el primero no obtiene respuesta.

El blueprint envía un snapshot de los campos simples del trigger, no los atributos de un evento posterior que haya llegado durante la acción. Excluye fechas `datetime` y objetos anidados innecesarios para que el resultado nativo de la plantilla siga siendo un diccionario válido. El servicio valida entidad, timestamp reciente, registro de entidades Telegram, bot y chat de nuevo. El destino de respuesta se deriva de `entity_registry.config_entry_id`; nunca se selecciona el primer bot ni el primer chat por defecto. La acción interna `telegram_update` está destinada a esta automatización; **no la conectes directamente a un webhook público**. Los usuarios con permiso para ejecutar acciones HA ya pueden ejecutar las acciones de compra/menú: no es una frontera de permisos entre administradores HA.

Otras automatizaciones del bot pueden seguir activas para comandos distintos. Si ya tienes otra que maneje `/menu` o `/compra`, decide cuál debe atenderlos para no obtener dos respuestas. Esta integración ignora comandos ajenos y callbacks sin prefijo `mc:`.

## 5. Comandos y botones

| Comando | Efecto |
| --- | --- |
| `/menuc`, `/ayudamenu` | Ayuda y panel con compra/menú |
| `/compra` | Lista paginada con marcar/desmarcar, −1, +1 y quitar |
| `/comprar leche` | Añade cantidad 1; si no existe crea producto genérico con precio 0 |
| `/comprar 2,5 leche` | Añade cantidad 2,5; también admite punto decimal |
| `/menu`, `/menu semana`, `/menu hoy` | Semana actual completa, de lunes a domingo |
| `/menu 16/11/26`, `/menu mañana` | Semana que contiene la fecha elegida |
| `/plato hoy comida Sopa y pan` | Añade **un plato** sin dividir «y», sin sustituir otros |
| `/plato 16/11/26 cena Tortilla` | Añade un plato en la fecha y franja indicadas |
| `/editarplato 12 Crema de verduras` | Muestra el plato actual y pide confirmar el cambio |
| `/quitarplato 12` | Pide confirmar antes de quitar solo ese ID |

Los IDs se ven en `/compra` y en **Gestionar platos** del menú. Las fechas visibles son DD/MM/YY; los comandos admiten ese formato (YY se interpreta como 2000–2099) y conservan ISO por compatibilidad. Las fechas relativas usan la fecha local de HA. `comida` equivale a `lunch`, `cena` a `dinner`; se admiten varios platos por franja. Editar/añadir desde el panel muestra el comando que debes enviar: no existe una conversación ilimitada que capture otros mensajes del bot.

**Ambigüedad:** si hay productos coincidentes en varios supermercados, no se añade nada y aparecen botones de selección por ID y supermercado. Hay páginas si hay más opciones. Nunca se elige una tienda arbitraria. El catálogo se administra en la app, no desde Telegram.

**Confirmaciones:** Quitar, Limpiar comprados y Vaciar compra siempre requieren pulsar un segundo botón de confirmación. Vaciar/limpiar solo elimina líneas de compra; conserva catálogo, historial y menú. Los botones de marcado fijan `checked=true/false`, no alternan a ciegas. −1 no elimina una línea al llegar al mínimo: el backend devuelve un error.

**Botones temporales:** prefijo `mc:` y nonce opaco de 19 bytes, sin IDs ni instrucciones manipulables en el callback. Caducan en **10 minutos** y son de **un solo uso**, incluso navegación; abre el panel de nuevo para refrescarlo. La integración conserva como máximo 4096 botones y 4096 IDs de updates (deduplicación de 1 hora). Los protege con un lock, consume el nonce antes de escribir y rechaza otro actor/chat/bot/tema. Se comprueba la identidad actual de filas/productos/platos antes de mutar; los botones antiguos de un JSON restaurado con IDs reutilizados no deben actuar sobre un contenido distinto. Una confirmación de vaciado se invalida si cambia el conjunto, estado o cantidad de sus líneas.

La deduplicación y sesiones son **volátiles**, no una segunda base de datos: se pierden al recargar/reiniciar HA. No garantizan exactamente-una-vez entre reinicios, tras agotar el caché o fuera del TTL. El backend no ofrece revisión condicional/transacción entre lectura de identidad y escritura: para restaurar JSON, desactiva temporalmente la automatización y no hagas acciones concurrentes. Un registro restaurado idéntico no puede distinguirse de su versión anterior solo por sus campos.

Los mensajes se envían con `parse_mode: plain_text` y sin vista previa web; HTML y Markdown de los nombres se muestran literalmente, sin interpretarlos. Se eliminan controles/bidi y se parten a un máximo conservador de 4000 unidades UTF-16 (por debajo de 4096). Los teclados son arrays de pares `[etiqueta, callback]`, no cadenas separadas por comas.

## 6. Acciones sin Telegram

Todas están bajo el dominio `menu_compra`, con selectors, schemas y respuesta opcional. Selecciona siempre la entrada Menú y Compra; su `config_entry_id` no es el de Telegram. En Herramientas para desarrolladores → Acciones usa primero una consulta:

```yaml
action: menu_compra.get_shopping
data:
  config_entry_id: ID_DE_TU_ENTRADA_MENU_COMPRA
```

Ejemplo en un script con respuesta:

```yaml
sequence:
  - action: menu_compra.get_menu
    data:
      config_entry_id: ID_DE_TU_ENTRADA_MENU_COMPRA
      week: "2026-11-16"
    response_variable: mi_menu
```

| Acción | Campos específicos |
| --- | --- |
| `get_shopping` | Ninguno |
| `get_menu` | `week` (fecha ISO dentro de la semana) |
| `get_products` | `name` opcional; vacío devuelve catálogo |
| `add_shopping` | `name`, `quantity` opcional, `product_id` opcional, `price_cents` opcional |
| `update_shopping` | `item_id`, `quantity` y/o `checked` |
| `adjust_shopping` | `item_id`, `delta` −1 o 1 |
| `remove_shopping` | `item_id`, **`confirm: true`** |
| `clear_shopping` | `checked_only` booleano, **`confirm: true`** |
| `add_menu` | `date`, `slot` (`lunch`/`dinner`), `text` |
| `update_menu` | `entry_id`, `date`, `slot`, `text` |
| `remove_menu` | `entry_id`, **`confirm: true`** |
| `add_menu_batch` | `date`, `slot`, `texts` (lista de 1–20 textos) |
| `duplicate_week` | `week` de origen, **`confirm: true`**; destino semana siguiente |

Las respuestas mantienen los objetos del backend. Cuando el backend devuelve una lista, se envuelve como `result`. `add_shopping` ambiguo devuelve **`status: choose`, `written: false`, `matches`**: no se ha escrito. Debes elegir un producto y volver a llamar con su `product_id`; no uses el primer candidato automáticamente. Los demás fallos se propagan como excepciones HA, no como supuestos éxitos. Los scripts son responsables de solicitar confirmación humana antes de establecer `confirm: true`.

No hay proxy HTTP arbitrario, backup/restore por bridge, cambios de categorías/supermercados/catálogo, recetas ni acceso a archivos/secretos. La única creación de catálogo es la compra rápida genérica definida por el backend. Las escrituras no tienen reintentos automáticos. El cliente evita también el retry interno de aiohttp 3.14.5 para PUT/DELETE usando una sesión privada con `_retry_connection=False`; no modifica la sesión HTTP compartida de HA. Si se pierde una respuesta o falla Telegram después de escribir, consulta `/compra` o `/menu` **antes de repetir un comando**: la escritura podría haberse completado.

## 7. Rotar, desactivar y hacer copias

- **Rotar**: Datos y ajustes → Regenerar clave → confirmar. Invalida la anterior inmediatamente. Copia la nueva y actualízala en Opciones/Reconfigurar de la integración. No compartas la clave por Telegram ni la incluyas en capturas.
- **Desactivar bridge**: corta las siguientes llamadas de máquina; Ingress y la UI siguen disponibles. Para volver, activa y valida la integración.
- **Solo apagar Telegram**: vacía chats permitidos y/o desactiva su automatización. Las acciones HA de compra/menú siguen disponibles.
- La app guarda su clave en `/data/ha_bridge.json`, separada de la exportación JSON de datos. La exportación JSON no contiene esa clave ni sustituye la copia de seguridad HA.
- La copia de seguridad de la app debe incluir `/data`; la de HA incluye la configuración de la integración y su clave. **Trata ambas como secretos** y protege también las copias antiguas. Restaurar una copia antigua puede restaurar una clave anterior; rota después si procede.
- La URL HTTP sugerida es para la red interna de HA OS. No expongas el bridge a Internet ni uses HTTP sin protección en una red no confiable. El cliente valida HTTPS normalmente y no sigue redirects que puedan filtrar Bearer.

## 8. Prueba manual en tu HA (pendiente de ejecutar allí)

1. Comprueba que la conexión se añade y que `get_shopping` devuelve la lista correcta sin Telegram.
2. En un chat permitido envía `/menuc`, `/compra` y `/menu semana`; comprueba el mismo bot/chat/tema de salida.
3. Envía `/comprar 2 Producto de prueba`. Comprueba en Ingress una sola línea con cantidad 2. Prueba marcar, desmarcar y +1/−1.
4. Si tienes el mismo nombre en dos supermercados, busca ese nombre y comprueba que se pregunta cuál antes de escribir.
5. Añade dos platos en la misma comida. Edita uno, confirma y comprueba que el otro queda intacto. Quita uno y comprueba que pide confirmación.
6. Prueba Cancelar y después Limpiar comprados/Vaciar compra con datos de prueba; comprueba que catálogo y menú no cambian.
7. En un grupo, otro usuario no debe poder usar tus botones, pero sí abrir su propio panel si el grupo está permitido. Un chat no permitido no recibe respuesta ni produce compras.
8. Comprueba que los demás comandos de tu bot siguen funcionando. Prueba una recarga de la integración: un botón antiguo debe informar que caducó, sin repetir una compra.

## 9. Diagnóstico y alcance de las verificaciones

- **No aparece la integración:** revisa ruta de `manifest.json`, reinicia HA y comprueba los logs. No hace falta reinstalar Supervisor.
- **No conecta:** usa origen interno, verifica app 1.0.0 arrancada, bridge activado y clave actual. Una URL Ingress o un redirect se rechazan deliberadamente.
- **Telegram no responde:** verifica chats en ambas integraciones, entidad event correcta, automatización activada y traza. Tras `unknown`, repite un comando. No sustituyas el blueprint por eventos legacy del bus.
- **Botón caducado:** es normal tras 10 minutos, uso previo, limpieza del caché o recarga. Abre `/menuc`/`/compra`/`/menu` de nuevo.
- **Timeout/error después de escribir:** no repitas a ciegas; consulta los datos. No hay reintento de escrituras ni reenvío de entrega Telegram.

Verificación local: módulos puros contra **servidor FastAPI/SQLite real**, cliente **aiohttp 3.14.5**, pruebas de restauración JSON real, rotación y autenticación reales. La salida Telegram de esas pruebas es una **fixture explícita que captura payloads**, no un bot real. Las fixtures TCP adversarias comprueban redirects y pérdida de respuesta sin simular la API de la app. Se validan JSON/YAML, AST, plantillas Jinja con estados fixture y schemas con **probatio 0.13.0 real** y helpers `cv` fixture declarados.

Interfaces contrastadas con fuentes oficiales del tag **2026.11.1**: [Telegram event.py](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/homeassistant/components/telegram_bot/event.py), [bot.py](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/homeassistant/components/telegram_bot/bot.py), [services.py](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/homeassistant/components/telegram_bot/services.py), [services.yaml](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/homeassistant/components/telegram_bot/services.yaml), [config_flow.py](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/homeassistant/components/telegram_bot/config_flow.py), [config_entries.py](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/homeassistant/config_entries.py) y [requirements.txt](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/requirements.txt). Se usa **probatio**, no voluptuous; Core requiere Python ≥3.14.2. Los módulos puros siguen siendo importables en Python 3.11 para desarrollo.

Los resultados consolidados de la entrega original están en `VERIFICACION.md`. La preparación de CI se documenta en `PRUEBAS.md` y genera sus propios informes bajo build/; las evidencias históricas locales no se incluyen en los nuevos paquetes de fuentes. Incluyen las pruebas HA/Telegram, las regresiones de la app y la confirmación de callbacks sin repetir escrituras si caduca el aviso Telegram. Ruff y los tests de navegador se ejecutan también sobre el paquete final. Existe un aviso de deprecación de Starlette sobre `httpx`, no un fallo. En Python 3.11 se omiten las pruebas de probatio cuando ese paquete no es compatible; la verificación completa se hace con Python 3.14.9.

**Confirmación manual posterior:** el usuario informa de que ha realizado las pruebas solicitadas en un Home Assistant de test y todo funciona, sin probar aarch64. Esto actualiza el estado de validación manual, no implica que el agente haya instalado archivos, usado credenciales ni ejecutado HA/Telegram real. Los resultados locales del agente, los futuros jobs de CI y la prueba del usuario se mantienen separados.
