# Menú y Compra 1.0.0 — cierre estable

La versión 1.0.0 reúne las funciones, la interfaz y el menú semanal de Telegram ya aprobados. El único cambio visual es el icono elegido: bolsa/plato de B con los cubiertos de A. Las nuevas funcionalidades se tratarán como evolutivos, no como cambios de este cierre.

## Qué se conserva

- Catálogo, precios, categorías/tiendas, lista y menús existentes.
- SQLite versión4 y JSON de copia versión3; sin nueva migración de tablas.
- Clave privada bridge y configuración de la integración y su automatización.
- Menú Telegram de lunes a domingo con semana actual por defecto y fechas DD/MM/YY.
- Protecciones Ingress, acceso interno autenticado y ausencia de puertos publicados.

## Actualizar

1. Descarga copia JSON de los datos y una copia de Home Assistant que incluya app y configuración de Core.
2. Copia custom_components/menu_compra/ del ZIP de integración1.0.0 bajo /config y reinicia Core. La integración1.0.0 admite app0.6.0 y1.0.0 para hacer la transición.
3. Sustituye la carpeta local menu_compra/ por la del ZIP instalador1.0.0, busca actualizaciones en la tienda y actualiza la app. Conserva el slug y /data: no desinstales ni borres datos.
4. Recarga la interfaz para renovar iconos y assets. No cambies la clave ni recrees integración o automatización. Abre nuevos paneles Telegram tras reiniciar porque los botones son temporales.

El blueprint incluido es el mismo; si ya está configurado, no crees otra automatización.

## Identidad

El icono está dentro de la interfaz, en el favicon y acceso directo y en icon.png/logo.png de la ficha/tienda de la app. Home Assistant exige MDI en panel_icon de su barra lateral; ese pictograma y el favicon de la página padre HA no se reemplazan por un PNG ni se modifica el DOM del parent.

La fuente gráfica exacta está en artwork/icono-maestro.png del ZIP de fuentes. Los derivados se regeneran con tools/build_icons.py y Pillow13.0.0 (las letras se conservan en artwork/logotipo-texto.png, sin fuentes del sistema). El contenedor no necesita Pillow ni esa fuente.

## Verificación y límites

Resultados y evidencias en VERIFICACION.md. Los ZIP se extraen y prueban, incluida la presencia/formato de las imágenes dentro del paquete. No contienen bases de datos ni claves del usuario. Se conservan los paquetes anteriores.

El usuario confirma posteriormente que ha realizado las pruebas solicitadas en un Home Assistant de test y todo funciona; aarch64 no ha sido probado. Esta confirmación no es una ejecución del agente en su dispositivo. La preparación de CI y su alcance se explican en PRUEBAS.md y PREPUBLICACION.md; no se cambia el alcance funcional de1.0.0 ni se sobrescriben sus ZIP originales.
