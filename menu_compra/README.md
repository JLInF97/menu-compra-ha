# Menú y Compra

En 1.0.0 puedes habilitar una conexión interna desde Datos y ajustes para controlarla con acciones de Home Assistant y con tu integración Telegram Bot existente. El paquete adicional de integración y blueprint se instala bajo `/config` de HA, no dentro de esta carpeta. La interfaz web y la base de datos siguen siendo las mismas; la conexión está desactivada inicialmente y no publica puertos.

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

Puedes añadir `https://github.com/JLInF97/menu-compra-ha` a Repositorios de la tienda. Si ya usas la instalación local, no la sustituyas sin planificar una migración: los dos orígenes tienen identificadores y datos separados. No copies únicamente los archivos de `app/`, ni coloques el proyecto en `/config`.

**Guía completa:** [instalación, uso, copias y resolución de problemas](DOCS.md). El ZIP de fuentes incluye también el arranque local en Windows y las pruebas.

La versión **0.2.0** corrige el ZIP de 0.1.0, que omitía `Dockerfile`. Comprueba que `Dockerfile` y `config.yaml` estén juntos en esta carpeta. No necesitas reparar el Supervisor por ese defecto del ZIP anterior.

## Compatibilidad y límites

Empaquetada para `amd64` y `aarch64`, con `python:3.12-slim`. Acceso solo por Ingress; no necesita la API de Home Assistant ni del Supervisor. `panel_admin: false` permite mostrar el panel a usuarios no administradores; todos comparten y pueden modificar los mismos datos, incluidas las restauraciones.

Versión 1.0.0 estable. El usuario confirma que las pruebas solicitadas funcionan en un Home Assistant de test. No ha probado aarch64. Esta confirmación manual no equivale a ejecución del agente en HA ni a resultados del workflow de CI. Consulta [las comprobaciones y límites](DOCS.md#comprobaciones-y-límites).
