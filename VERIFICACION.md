# Verificación de Menú y Compra 1.0.0 — cierre estable

## Actualización de prepublicación

El usuario confirma que ha realizado las pruebas solicitadas en un Home Assistant de test y todo funciona. No ha probado aarch64. Se trata de una validación manual del usuario, no de ejecución del agente en su equipo. La preparación de pruebas portables y CI está en PRUEBAS.md y PREPUBLICACION.md. Los informes nuevos se generan en build/ y se mantienen separados de los resultados del cierre original descritos a continuación.

## Alcance

Consolidación de la interfaz y funciones aceptadas, incluido Telegram semanal de lunes a domingo y fechas DD/MM/YY. Se aplica el icono aprobado AB a la marca de la app, favicon/acceso directo e icon.png/logo.png para Supervisor. No se añaden funcionalidades ni se rediseña la interfaz.

App e integración1.0.0, stage stable. SQLite4 y JSON3 sin cambios. Persisten datos, clave bridge y configuración. La integración1.0.0 admite app0.6.0 y1.0.0 para actualización escalonada; no requiere recrear integración o automatización.

## Evidencia local

- 447 pruebas correctas en Python3.14.9, sin fallos ni omisiones; un aviso de deprecación Starlette/httpx del cliente de pruebas.
- 56 comprobaciones de navegador con backend/SQLite reales: regresión UI, conexión HA/clave y branding bajo proxy Ingress/banner simulado. Sin errores JavaScript. Icono visible y sin deformación en320/390/850/851/1280, imágenes/favicon con rutas relativas y navegación móvil visible. Capturas inspeccionadas.
- Maestro exacto aprobado conservado por SHA256. PNG32/180/192/512, icono tienda128, logo512x160 e ICO16/32/48/64 verificados. Derivados comparados píxel a píxel con el maestro redimensionado.
- Ruff, node --check y sh -n correctos. YAML estable mantiene slug menu_compra, acceso Ingress, /data y backup cold, sin nuevos puertos ni privilegios.
- Cliente/router Telegram probados contra FastAPI/SQLite reales. Solo la entrega Telegram y helpers HA/estado/selector son fixtures expresamente declaradas; schemas probatio0.13.0 reales e interfaces contrastadas con Core2026.11.1. No se suplantan módulos globales de HA.

Evidencias del cierre original en evidencias/1.0.0: pytest.xml, navegador.json, conexion-ha.json, branding.json, ejemplo semanal y capturas. Las nuevas fuentes no incluyen esas evidencias locales históricas; la CI genera sus propios informes y capturas bajo build/. Son datos de prueba, no datos del usuario. El banner es una simulación local, no HA real.

## Archivos

build_release.py comprueba dentro de los ZIP Dockerfile junto a config.yaml, run.sh LF, imágenes PNG/ICO y tamaños, manifiesto de integración y ausencia de claves/bases de datos. Entrega app, integración/blueprint y fuentes con maestro gráfico. verify_release.py extrae los tres, compara integración y fuentes, prueba la app extraída y ejecuta la suite desde las fuentes extraídas. MENU_COMPRA_VERIFY_UI=1 ejecuta los tres scripts de navegador contra el instalador extraído.

## Límites

No se ha ejecutado la imagen Docker: el daemon Docker Desktop no está disponible, comprobado en este cierre. No se ha instalado ni ejecutado Core/Supervisor/Telegram real ni usado credenciales del usuario. Stable identifica la entrega aceptada, no una certificación de ejecución en el dispositivo.

La barra lateral HA usa panel_icon MDI; no se sustituye por PNG ni se modifica su DOM. El favicon de la app no modifica el documento padre de Home Assistant.

Las sesiones Telegram son volátiles; controles de identidad lectura/escritura no son transacciones condicionales. Desactivar la automatización al restaurar JSON y no repetir escrituras inciertas sin consultar el resultado. Se mantienen los límites documentados en HA_TELEGRAM.md.

## Actualización

Hacer copia. Actualizar primero custom_components/menu_compra1.0.0 y reiniciar Core; después sustituir/actualizar app1.0.0 sin desinstalar ni borrar /data. No regenerar claves ni recrear automatizaciones. Recargar recursos/iconos tras actualizar. Instrucciones en CIERRE-1.0.0.md y HA_TELEGRAM.md. Evolutivos futuros separados del cierre.

