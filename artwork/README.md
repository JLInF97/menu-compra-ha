# Identidad aprobada — Menú y Compra

icono-maestro.png es el archivo elegido por el usuario: bolsa y plato de la propuesta B con tenedor y cuchillo de A. Se conserva sin redibujar ni regenerar.

Los derivados PNG/ICO se generan con tools/build_icons.py y Pillow13.0.0. La app usa rutas relativas a static/ para respetar Ingress. icon.png y logo.png junto a config.yaml son los recursos gráficos de la ficha de la app en Supervisor.

El panel_icon de la barra lateral Home Assistant solo admite iconos MDI; se conserva el pictograma configurado. El favicon de la app no sustituye el del documento padre de HA.

logotipo-texto.png conserva las letras ya rasterizadas del logo original. La regeneración usa solo este PNG y el icono maestro, sin fuentes del sistema, rutas de Windows ni cachés de generación. No se distribuye ningún archivo de fuente. Pillow es una herramienta de desarrollo, no una dependencia del contenedor.
