# Menú y Compra

En **1.1.0** la conexión con Home Assistant es automática bajo Supervisor: instala/inicia la app, copia el componente **1.1.0** a `/config/custom_components/menu_compra/` y **reinicia Core**. La entrada se crea sin escribir URL ni copiar claves. El componente requiere esa copia manual; la app no puede instalarlo sola. La interfaz y los datos no cambian, ni se publican puertos. [Guía de enlace automático](https://github.com/JLInF97/menu-compra-ha/blob/main/ENLACE_AUTOMATICO.md) y [Telegram](https://github.com/JLInF97/menu-compra-ha/blob/main/HA_TELEGRAM.md).

Una app nueva genera su clave y activa la conexión al arrancar bajo Supervisor. Una actualización conserva la clave y el estado anterior: si estaba desactivada, pulsa **Activar** en Datos y ajustes para usarla. `announced` solo confirma aceptación del anuncio por Supervisor, no que Core haya terminado de enlazar. Si Core no está disponible o falta el componente, hay reintentos sin bloquear la app ni cambiar la clave.

Con una sola app no hay campos de conexión; si hay varias debes elegir. Telegram sigue siendo opcional: configura la entidad de eventos, una lista explícita de chats permitidos y su automatización. El descubrimiento no autoriza chats ni grupos. El modo manual solo está en **Configuración manual avanzada**, para Docker/desarrollo/migraciones especiales.

Aplicación local para **Home Assistant OS**, en castellano, con menú semanal, lista de la compra e historial de precios. Se abre dentro de Home Assistant mediante **Ingress**, sin publicar puertos ni crear otra cuenta.

- Planifica comidas y cenas con varios platos independientes en cada franja.
- Añade a la compra desde el enlace subrayado bajo el nombre del plato al crearlo o editarlo. No hay botones de compra permanentes en las tarjetas.
- Escribe el producto y confirma: si hay una coincidencia se selecciona sola; si hay varias eliges; si no existe se crea automáticamente a precio 0 y sin categoría o tienda específicas.
- Lista móvil limpia, agrupada, con congelados al final y contador comprados/total; controles −/+ y botón flotante para añadir, sin panel de pendientes, notas ni menú Cantidad.
- Precio, supermercado, categoría y unidad se actualizan en la compra al editar el producto, sin perder cantidad ni estado comprado.
- Gestión de categorías y tiendas en ajustes; borrado definitivo de productos e historial con confirmación; Limpiar todos solo vacía la compra.
- Navegación móvil fija abajo, platos con letra más grande, menú sin subtítulo ni recuentos y versión en el pie.
- El área visible del iframe se recalcula para no dejar navegación y FAB bajo el banner de Home Assistant; incluye recortes de contenedores y Shadow DOM.
- Nombres de productos más legibles, controles de cantidad compactos y precios del catálogo más discretos.
- Categoría y tienda «Sin especificar» siempre protegidas; badge de productos pendientes de clasificar.
- Toques en nombres para editar y alta directa de 1 unidad desde «+ A la lista» del catálogo.
- Duplica los platos de una semana a la siguiente sin borrar lo que ya exista ni repetir platos ya copiados.
- Guarda productos y precios por supermercado, por unidad, kg o litro; consulta su historial.
- Comparte la misma base de datos entre los usuarios que acceden a la app. No hay listas privadas ni permisos diferenciados dentro de ella.
- Exporta e importa tus datos en JSON y conserva copias con Home Assistant.

Los datos se guardan en SQLite en `/data/menu_compra.sqlite3`. No hay productos ni precios de ejemplo: introduce tus datos reales. No utiliza servicios externos durante su funcionamiento normal; la instalación sí necesita descargar la imagen base y las dependencias.

## Instalación local

1. Copia **esta carpeta `menu_compra` completa** a `/local_apps/menu_compra` desde Terminal & SSH o al recurso `local_apps` de Samba. En instalaciones anteriores, la ubicación habitual es `/addons/menu_compra` o el recurso `addons`; usa la carpeta local que exponga tu instalación, no ambas.
2. En **Ajustes → Aplicaciones → Instalar aplicación**, abre el menú de la tienda y pulsa **Buscar actualizaciones**. En versiones antiguas se llama **Complementos → Tienda de complementos**.
3. Busca **Menú y Compra** entre las aplicaciones locales y pulsa **Instalar**. Se compila en el propio equipo: espera a que termine.
4. Pulsa **Iniciar**, revisa **Registro** y activa **Mostrar en la barra lateral**. Abre **Interfaz web** o la entrada **Menú y compra**.

Puedes añadir `https://github.com/JLInF97/menu-compra-ha` a Repositorios de la tienda. Si ya usas la instalación local, no la sustituyas sin planificar una migración: los dos orígenes tienen identificadores, datos y claves separados; no se migra ni se cambia de app silenciosamente. Exporta/restaura y elige explícitamente la instalación que quieres enlazar. No copies únicamente los archivos de `app/`, ni coloques el proyecto en `/config` (solo el componente y el blueprint van allí).

**Actualizar desde 1.0.0:** haz copia; sustituye primero el componente por 1.1.0 y reinicia Core; después actualiza la misma app a 1.1.0. Conserva su slug y `/data`; no desinstales ni recrees la entrada o la automatización. Se conservan clave, ID y opciones Telegram de la misma instalación, incluido el estado desactivado.

**Guía completa:** [instalación, uso, copias y resolución de problemas](DOCS.md). El ZIP de fuentes incluye también el arranque local en Windows y las pruebas. [Repositorio](https://github.com/JLInF97/menu-compra-ha) · [Releases](https://github.com/JLInF97/menu-compra-ha/releases) · [Licencia MIT](LICENSE).

La versión **0.2.0** corrige el ZIP de 0.1.0, que omitía `Dockerfile`. Comprueba que `Dockerfile` y `config.yaml` estén juntos en esta carpeta. No necesitas reparar el Supervisor por ese defecto del ZIP anterior.

## Compatibilidad y límites

Empaquetada para `amd64` y `aarch64`, con `python:3.12-slim`. Acceso web solo por Ingress; el descubrimiento usa Supervisor sin permisos ampliados `hassio_api`/`homeassistant_api`, red del anfitrión ni puertos publicados. `panel_admin: false` permite mostrar el panel a usuarios no administradores; todos comparten y pueden modificar los mismos datos, incluidas las restauraciones.

Documentación de **1.1.0**. La confirmación manual del usuario en un Home Assistant de test pertenece a **1.0.0**, sin prueba en hardware aarch64; no verifica el nuevo enlace automático. Las pruebas de CI/paquetes de 1.1.0 deberán tener evidencias propias y sigue pendiente la validación en Core/Supervisor real. Consulta [las comprobaciones y límites](DOCS.md#comprobaciones-y-límites).
