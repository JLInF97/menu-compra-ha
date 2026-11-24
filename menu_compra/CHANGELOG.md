# Registro de cambios

## 1.1.0 — enlace automático con Home Assistant

- En Supervisor, descubrimiento de la identidad real de la app y anuncio autenticado al componente personalizado: no hay que introducir URL ni copiar claves en el flujo normal. Sin host fijo, permisos ampliados de API, puertos publicados ni red del anfitrión.
- El componente 1.1.0 se copia manualmente bajo `/config/custom_components/menu_compra/` y requiere reiniciar Core. Después se crea/actualiza la entrada automáticamente; con varias apps se exige elegir. No se instala código en `/config` desde la app.
- App nueva bajo Supervisor: activación y clave automática. Actualizaciones: se respetan clave y estado, incluido `enabled: false`. Desactivar retira el anuncio; activar/rotar reanuncia. Reintentos por intervalo ante indisponibilidad sin bloquear la app ni rotar claves.
- Estado de enlace automático en Datos y ajustes. `announced` solo significa aceptación del anuncio por Supervisor, no que Core haya terminado de configurar la entrada. Configuración manual reservada a la opción avanzada para Docker/desarrollo/migraciones especiales.
- Para la misma app se mantienen ID de entrada y opciones Telegram; una entrada manual con la misma URL puede adoptarse. No se migra silenciosamente entre apps locales y de repositorio, cuyos identificadores y datos siguen separados. Telegram requiere entidad y chats permitidos explícitos; no se autorizan grupos automáticamente.
- Actualización desde 1.0.0: copia de seguridad, componente 1.1.0 → reinicio Core → app 1.1.0, sin desinstalar, cambiar slug, borrar `/data`, regenerar clave o recrear automatizaciones. Se conservan interfaz, iconos y funciones aceptadas, protocolo bridge v1, SQLite 4 y JSON 3. Las entregas 1.0.0 no se modifican.
- Documentación: [enlace automático](https://github.com/JLInF97/menu-compra-ha/blob/main/ENLACE_AUTOMATICO.md) y [Telegram](https://github.com/JLInF97/menu-compra-ha/blob/main/HA_TELEGRAM.md). Los resultados históricos de 1.0.0 no validan 1.1.0: CI y paquetes deberán tener evidencias propias; sigue pendiente probar el enlace en Core/Supervisor y Telegram reales, además de hardware aarch64.

## 1.0.0 — cierre estable

- Icono aprobado: bolsa y plato de la propuesta B con los cubiertos de A. Incorporado a la marca de la app, favicon, iconos de acceso directo móvil y ficha/tienda de Supervisor.
- Consolidación de las funciones y la interfaz aceptadas, incluido Telegram semanal lunes–domingo y fechas DD/MM/YY. Sin nuevas funcionalidades.
- App e integración versionadas a 1.0.0, app marcada stable. Misma base de datos (SQLite4), copias JSON3 y clave de conexión. La integración admite app0.6.0 durante la actualización escalonada.
- Las futuras funcionalidades se desarrollarán como evolutivos separados. Las comprobaciones locales no equivalen a una instalación real de Core/Supervisor.

## Integración 0.6.1

- Menú Telegram semanal por defecto, días completos y fechas DD/MM/YY; acciones separadas en Gestionar platos. No requería cambiar la app0.6.0.

## 0.6.0

- Conexión interna opcional con Home Assistant mediante Bearer propio, inicialmente desactivada, con activación y clave desde Datos y ajustes. Persistencia privada en /data, revelación explícita, desactivación y rotación.
- API de máquina limitada a catálogo de consulta, menú y compra; no permite copia/restauración, borrar productos o cambiar categorías/tiendas. La interfaz sigue protegida por Ingress; no se publican puertos ni se añaden permisos de Supervisor.
- Integración personalizada Menú y Compra y blueprint para reutilizar Telegram Bot de HA Core 2026.11.1. Acciones de automatización y comandos/botones para menú y compra, con chats permitidos, elección de supermercado y confirmaciones.
- Misma base de datos e interfaz que 0.5.1, sin cambios de esquema SQLite 4 ni copia JSON 3. La clave de conexión no se incluye en los JSON descargables, pero sí en copias completas de la app realizadas por Supervisor.

## 0.5.1

- Eliminado el campo Notas del editor de producto abierto desde la compra, tanto al tocar el nombre como al pulsar Editar. Se conservan las notas existentes sin modificarlas.
- Ocultas la categoría y la tienda «Sin especificar» en las listas de gestión. Siguen disponibles en los selectores del producto y protegidas en la API, sin eliminar datos.
- Sin cambio de esquema SQLite ni del formato de copia.

## 0.5.0

- Navegación inferior, FAB y diálogos adaptados al área realmente visible del iframe, sin altura fija del banner; observa cambios de viewport, banner y contenedores, incluidos hosts Shadow DOM.
- Nombre del producto mayor en compra y catálogo; unidades/−/+ más compactos y precio del catálogo menor.
- Categoría y supermercado «Sin especificar» permanentes y protegidos aunque estén vacíos. Migración de «Sin categoría» conservando productos, relaciones y precios.
- Badge de productos con categoría pendiente; se actualiza al crear, clasificar o borrar y se oculta a cero.
- Editar junto a Quitar en compra y edición directa tocando el nombre.
- Comida vacía y nombre de plato táctiles, con soporte de teclado y sin diálogos duplicados.
- «+ A la lista» en catálogo y detalle añade directamente 1 unidad al precio/tienda actuales, sin pedir cantidad o precio.
- SQLite versión 4, sin nuevas columnas respecto a 0.4.0; copias JSON versión 3 con restauración de versiones anteriores.

## 0.4.0

- Compra viva: precio, supermercado, categoría y unidad sincronizados con el catálogo, incluidas líneas ya marcadas como compradas; cantidad y estado conservados.
- Quitado el subtítulo y el recuento del menú semanal; nombres de platos más grandes.
- Eliminación definitiva de productos, historial y referencias de compra/ingredientes; retirada la opción de archivar. Los antiguos archivados se conservan visibles para poder eliminarlos.
- CRUD de categorías y supermercados desde Datos y ajustes, con reasignación genérica y protección frente a pérdidas o colisiones.
- Botones −/+ atómicos para cantidad y entrada manual, sin el botón ni diálogo Cantidad.
- Botón + flotante y navegación inferior fija en móvil, con espacio para la barra y áreas seguras.
- Pie de página con versión de la aplicación, sin lema.
- Limpiar todos junto a Limpiar comprados, con confirmación; catálogo e historial intactos.
- SQLite versión 3 y copia JSON versión 3, con restauración de versiones 1/2/3. Se conserva el nombre histórico de una tienda eliminada sin mantener su registro activo.

## 0.3.0

- Quitado el botón verde global de añadir plato del menú semanal; se mantienen los de cada comida/cena.
- Compra visualmente limpia: solo título, añadir, contador y lista; sin resumen de pendientes, subtítulo ni título del recorrido.
- Alta rápida de productos nuevos con precio 0, unidad ud, categoría «Sin categoría» y tienda «Sin especificar», sin formulario de catálogo.
- Coincidencia única autoseleccionada; selección manual solo con varias candidatas. La búsqueda no crea productos al escribir.
- Eliminadas las notas de compra de los formularios y de la lista; los datos antiguos permanecen en las copias por compatibilidad.
- «Añadir a la compra» como enlace subrayado bajo cada input del editor de menú, sin botones permanentes en las tarjetas ni guardados implícitos del menú.
- Duplicación segura de semana a siguiente: mantiene comidas/cenas, orden y platos existentes; evita duplicados y revierte toda la operación si no cabe en destino.
- Sin cambio de esquema SQLite ni del formato JSON de copia respecto a 0.2.0.

## 0.2.0

- Corregida la exclusión de `Dockerfile` en los ZIP; prueba de regresión que falla si falta dentro del archivo, aunque exista en disco.
- Nuevo ZIP de instalación con `menu_compra/` directamente en la raíz, además del ZIP completo de fuentes.
- Menú simplificado: varios platos independientes por comida y cena, alta múltiple y edición/borrado individual.
- Compra desde el nombre del plato: exacta única directa, selector si hay varias o coincidencias parciales y alta del producto si no hay coincidencias.
- Eliminado el flujo de recetas e ingredientes de la interfaz, sin borrar sus datos antiguos.
- Migración automática SQLite versión 1 a 2 y restauración compatible con copias JSON 1 y 2.

## 0.1.0

- Primera versión local para Home Assistant OS, con interfaz en castellano e Ingress.
- Menú semanal de comidas y cenas, platos y asociación manual reutilizable de ingredientes.
- Catálogo por supermercado, precios por unidad, kg o litro e historial de cambios.
- Lista compartida con categorías, congelados al final, cantidades, marcas de compra y totales.
- Instantáneas de precio en la lista: cambiar el catálogo no recalcula automáticamente líneas existentes.
- Persistencia SQLite en `/data`, exportación JSON y restauración validada y transaccional.
- Empaquetado para `amd64` y `aarch64`, sin puertos publicados ni permisos sobre las API de Home Assistant.
- Copias de Home Assistant en frío (`backup: cold`) para detener la aplicación al copiar SQLite.

Versión experimental: pendiente de validar la instalación y el funcionamiento dentro de un Home Assistant OS real y la ejecución de la imagen Docker.
