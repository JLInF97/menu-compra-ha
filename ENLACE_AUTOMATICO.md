# Enlace automático con Home Assistant · 1.1.0

En Home Assistant OS con Supervisor, **no tienes que escribir una URL ni copiar una clave** para conectar Menú y Compra. La app anuncia su instalación real y el componente personalizado crea o actualiza la entrada. El menú, la compra y el catálogo siguen en la misma base de datos de la app.

[Repositorio público](https://github.com/JLInF97/menu-compra-ha) · [Releases](https://github.com/JLInF97/menu-compra-ha/releases) · [Licencia MIT](LICENSE) · [Guía de Telegram y acciones](HA_TELEGRAM.md) · [Guía de la app](https://github.com/JLInF97/menu-compra-ha/blob/main/menu_compra/DOCS.md).

Esta guía describe 1.1.0; consulta en Releases qué paquetes están publicados. No es una afirmación de que 1.1.0 haya pasado CI ni de que el enlace se haya probado en un Core/Supervisor real. Los resultados de 1.0.0 son históricos y sus entregas permanecen inmutables.

## Instalación nueva

1. Añade `https://github.com/JLInF97/menu-compra-ha` a **Ajustes → Aplicaciones → Instalar aplicación → ⋮ → Repositorios**. Instala e inicia **Menú y Compra 1.1.0**. También puedes instalar la app local con `menu-compra-ha-1.1.0-instalar.zip`, siguiendo la guía de la app; no instales ambos orígenes por accidente.
2. Descarga el paquete separado `menu-compra-ha-1.1.0-integracion.zip`. Copia **`custom_components/menu_compra/`** a **`/config/custom_components/menu_compra/`**. Copia también `blueprints/automation/menu_compra/telegram.yaml` bajo `/config/blueprints/automation/menu_compra/` si usarás Telegram. Fusiona las carpetas; no añadas un directorio intermedio con el nombre del ZIP.
3. **Reinicia Home Assistant Core**, no solo la app. El componente no se instala automáticamente: la app no tiene acceso de escritura a `/config`. Esa copia inicial es necesaria una vez; en actualizaciones posteriores hay que reemplazar también los archivos del componente cuando corresponda. No es una integración oficial ni se distribuye por HACS.
4. Ve a **Ajustes → Dispositivos y servicios**. Con una sola app descubierta, la entrada **Menú y Compra** se crea automáticamente, sin campos de URL o contraseña. Si abres **Añadir integración → Menú y Compra**, el flujo también consulta los descubrimientos disponibles. Si hay varias instalaciones, debes elegir la correcta; no se selecciona una al azar ni se sustituye una entrada de otra instalación en silencio.
5. Comprueba la conexión con una lectura, por ejemplo la acción `menu_compra.get_shopping`, seleccionando el `config_entry_id` de Menú y Compra. Ver la entrada y consultar sus datos es una comprobación distinta de ver el estado `announced` en la app.

En una app **nueva bajo Supervisor**, la conexión se activa y genera una clave persistente al iniciar. No necesitas verla ni copiarla. La interfaz por Ingress no exige esta conexión y sigue funcionando si la desactivas. No publiques el puerto 8099 ni actives red del anfitrión o permisos ampliados de API.

### Telegram sigue necesitando autorización

El descubrimiento enlaza la app; **no autoriza chats ni grupos**. En **Configurar/Opciones** de la entrada selecciona la entidad **`event.…`** de tu integración Telegram Bot y una lista explícita de chats permitidos. Vacío significa Telegram desactivado. El propio Telegram Bot de HA también debe permitir esos chats.

Crea y activa una sola automatización del blueprint por entrada, usando la misma entidad. No hay otro receptor, polling ni token Telegram que copiar a la app. Autorizar un grupo permite iniciar comandos a todos sus miembros; los botones mantienen sus restricciones de actor/chat/bot/tema. Consulta [los comandos y controles de seguridad](HA_TELEGRAM.md).

## Actualizar desde 1.0.0

1. Exporta el JSON desde la app y crea una copia de Home Assistant que incluya sus datos y la configuración de la integración. Protege la copia completa: contiene secretos.
2. Sustituye primero el componente en **`/config/custom_components/menu_compra/`** por **1.1.0** y **reinicia Core**. La integración 1.1.0 admite health de backends 0.6.0, 1.0.0 y 1.1.0 para facilitar la transición.
3. Actualiza después **la misma app** a **1.1.0**, desde su origen actual. Para la app local, sustituye la carpeta completa en `/local_apps/menu_compra` o en la antigua `/addons/menu_compra`, refresca la tienda y pulsa Actualizar. No cambies el slug, no dupliques las carpetas y no desinstales.
4. Conserva **`/data`**, la clave, la entrada y la automatización. No regeneres credenciales ni recrees configuraciones para esta actualización. SQLite sigue en versión 4, los JSON en versión 3 y el protocolo de máquina en v1. No se modifican menús, catálogo, compra, precios, iconos ni funciones de la interfaz aceptada.
5. Si ya existía `/data/ha_bridge.json`, se conserva su clave y su estado. **`enabled: false` sigue desactivado**, también después de reiniciar. Si quieres enlazar, pulsa **Activar** en Datos y ajustes: no hay URL ni clave que introducir.
6. Comprueba los datos por Ingress y la entrada en Dispositivos y servicios. Para la **misma app gestionada**, se conserva el ID de entrada, la entidad Telegram, los chats y las opciones; se actualizan host/credenciales sin perderlos. Una entrada manual cuya URL coincide puede adoptarse. Si apunta a otra instalación, se pide resolver la elección/conflicto antes de cambiarla.

No borres una entrada ni una automatización existente para forzar el descubrimiento. Si hay conflicto, comprueba primero de qué app son los datos y elige conscientemente. La selección de varias apps no exige escribir URL ni contraseña.

## Estados y diagnóstico

En **Datos y ajustes → Conectar con Home Assistant** se muestra el estado de enlace automático. El estado no contiene la clave.

| Estado (`discovery_state`) | Significado y siguiente comprobación |
| --- | --- |
| `unavailable` | No está disponible el canal de descubrimiento Supervisor, por ejemplo fuera de él. En HA OS revisa el arranque y registros; fuera de Supervisor usa solo el modo manual avanzado si lo necesitas. No hay un hostname de sustitución fijo. |
| `pending` | El anuncio está pendiente. Comprueba que la app y Supervisor estén disponibles y deja actuar el siguiente reintento. |
| `announced` | **Supervisor aceptó el anuncio**. No confirma que Core haya instalado, creado o cargado la integración: comprueba el componente 1.1.0, reinicio de Core, la entrada y una lectura real. |
| `error` | Falló un intento de descubrimiento. Revisa disponibilidad de Supervisor/app/Core y los registros sin compartir secretos. Se reintenta por intervalo. |
| `disabled` | La conexión está desactivada. Se conserva así al reiniciar/actualizar. Pulsa Activar solo si quieres habilitarla. |

**Core apagado, componente ausente o servidor no disponible:** instala/actualiza el componente, reinicia Core y arranca la app. El proceso de descubrimiento reintenta de forma acotada por intervalo, sin bloquear la interfaz, sin rotar la clave y sin prometer que Core haya terminado. También puedes abrir Añadir integración para consultar descubrimientos. No se garantiza enlace inmediato ni un plazo de recuperación.

**Varias apps o datos inesperados:** comprueba qué instalación has abierto por Ingress y cuál está enlazada. No confundas la app local con la del repositorio; sus datos no se unen. No elijas la primera arbitrariamente.

**Telegram no responde:** comprueba entidad de eventos, chats en ambas integraciones y automatización/traza. Esto no se resuelve cambiando la URL. Tras una entidad `unknown`/`unavailable`, repite un comando de lectura para inicializar el flujo si hace falta.

**Error tras una escritura:** no repitas a ciegas; consulta `/compra` o `/menu`. Los reintentos de descubrimiento no son reintentos de escrituras: las acciones de modificación no se reenvían automáticamente y podrían haberse completado aunque se pierda la respuesta.

### Desactivar o rotar

- **Desactivar** corta nuevas llamadas de máquina y retira el anuncio, sin apagar Ingress. Conserva la clave y no se revierte por reiniciar. **Activar** vuelve a anunciar sin campos de conexión.
- **Regenerar clave** requiere confirmar e invalida la anterior inmediatamente. En una entrada gestionada de la misma app se reanuncia y actualiza automáticamente; comprueba la disponibilidad antes de ejecutar acciones. Solo el modo manual avanzado requiere actualizar la clave a mano.
- La clave se guarda en **`/data/ha_bridge.json`** y el journal privado del anuncio en **`/data/ha_discovery.json`**, fuera del JSON de datos y de los paquetes públicos. Una copia completa de Supervisor y la configuración HA sí pueden contenerla: trátalas como secretos. Restaurar JSON de menú/productos no cambia la conexión; restaurar una copia completa antigua puede recuperar una clave antigua.

## Migrar de local a repositorio

La instalación local y la del repositorio son **apps distintas** con identificadores, `/data` y claves separados. El enlace automático no convierte una en otra, ni traslada datos, ni reemplaza silenciosamente la entrada existente. Puedes mantener y actualizar la app local sin migrar.

Si decides cambiar de origen:

1. Haz copias y exporta el JSON de la app de origen. Detén temporalmente su automatización Telegram y evita acciones concurrentes durante la restauración.
2. Instala la nueva app sin borrar la anterior y restaura el JSON en el destino elegido. La restauración **reemplaza** sus datos, no los mezcla; el JSON no contiene la clave bridge.
3. Comprueba menú, compra, catálogo y precios en el destino por Ingress. Resuelve explícitamente la elección de instalación en HA; si hay una entrada de otra app, atiende el conflicto en lugar de forzar su sustitución. El modo manual avanzado queda disponible para casos especiales, no como paso normal obligatorio.
4. Verifica el `config_entry_id` que usa la automatización y sus opciones antes de reactivarla. No supongas que dos apps comparten el ID o los chats porque tengan el mismo nombre. Conserva el origen hasta verificar los datos y las copias.

## Arquitectura y configuración manual avanzada

Este apartado es técnico; **no es una lista de campos que rellenar al instalar en HA OS**. El contrato técnico se describe en este apartado, con Supervisor estable **2026.11.0** y Core **2026.11.1** como referencias de implementación, no como evidencia de una prueba real.

- La app espera a que su listener HTTP esté listo antes del primer anuncio, para no iniciar el health de Core antes de poder atenderlo.
- La app consulta **`GET /addons/self/info`** para obtener su `hostname` y slug reales. El origen interno utiliza esa identidad y el puerto interno 8099. No se calcula con un hash del repositorio, no se toma de la URL del navegador y no se fija un host válido para todas las instalaciones.
- Anuncia **`POST /discovery`** con `service: menu_compra` y `config` que contiene `base_url`, `api_key` y `protocol_version: 1`. El secreto circula solo por el canal autenticado Supervisor/Core, no en el estado de la UI, URLs, logs ni formularios normales.
- Se prefiere **`SUPERVISOR_SOCKET`** (HTTP por socket Unix); **`SUPERVISOR_TOKEN`** hacia el destino fijo `http://supervisor` es compatibilidad. No se siguen redirecciones. Estas rutas de identidad/descubrimiento están permitidas a la app sin ampliar `hassio_api`/`homeassistant_api`. No cambia `host_network`, Ingress ni los puertos.
- Core recibe el descubrimiento autenticado por Supervisor, valida servicio, identidad de instalación, protocolo, origen y clave, y comprueba `/bridge/v1/health` antes de crear/actualizar la entrada. Un anuncio aceptado no demuestra que esas comprobaciones hayan terminado. Reauth/reconfiguración de la misma app gestionada recupera las credenciales de Supervisor, no exige copiarlas.

**Docker sin Supervisor, desarrollo o migraciones especiales:** abre **Configuración manual avanzada** en la app y la opción avanzada de la integración cuando proceda. Usa el origen HTTP/HTTPS real accesible desde Core, con su puerto, sin rutas, parámetros, fragmentos ni credenciales en la URL. Introduce solo ahí la clave bridge de la instalación correcta. No copies un hostname de ejemplo, no uses la URL de Ingress y no expongas el bridge a Internet. En opciones manuales, una contraseña vacía conserva la clave; nunca se precarga.

El modo de desarrollo `MENU_COMPRA_DEV=1` elimina la restricción web de Ingress y **no es una solución para HA OS ni para exponer el servicio a la red**. Mantén las protecciones de producción, CSRF, autenticación Bearer y rechazo de redirects.

## Alcance de la validación de 1.1.0

El procedimiento reproducible está en [PRUEBAS.md](https://github.com/JLInF97/menu-compra-ha/blob/main/PRUEBAS.md). Las pruebas locales y de paquetes extraídos aportan evidencias propias de1.1.0; los resultados remotos se consultan en GitHub Actions y en las notas de la release correspondiente. No deben confundirse con una prueba en la instalación real del usuario.

Las fixtures y helpers de esquemas no ejecutan un runtime real de Core/Supervisor. También queda pendiente comprobar el enlace automático, la actualización conservando entrada/opciones, los conflictos entre apps y el bot en una instalación real. La confirmación del usuario sobre 1.0.0 no valida estos cambios. La prueba en hardware aarch64 sigue separada y pendiente; Docker arm64 bajo QEMU no la sustituye.
