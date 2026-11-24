# Desarrollo y pruebas reproducibles

Requisitos: Python3.12 o3.14, Node>=22 y npm. Para la comprobación más cercana al adaptador Core2026.11.1 usa Python3.14. No se necesita Home Assistant instalado para las pruebas locales: los adaptadores de HA/entrega Telegram usan fixtures declaradas y el backend FastAPI/SQLite se ejecuta de verdad.

## Preparar entorno

Crea un entorno con `python -m venv .venv` y actívalo con `.venv\Scripts\activate` en Windows CMD o `source .venv/bin/activate` en Linux/macOS. Desde la raíz:

    python -m pip install --require-hashes -r requirements-ci.lock
    npm ci
    npx playwright install chromium

En Linux puede hacer falta `npx playwright install --with-deps chromium`. En CI se instala así. No se necesita Edge, NODE_PATH ni fuentes de Windows. El lock Python es universal, incluye hashes y marca colorama solo en Windows. Para actualizarlo de manera deliberada: `uv pip compile requirements-dev.txt --python-version 3.12 --universal --generate-hashes --output-file requirements-ci.lock`.

## Ejecutar

    python tools/check_portability.py
    python -m ruff check menu_compra/app custom_components tests tools
    python -m pytest -q --junitxml=build/pytest.xml
    npm run check:js
    sh -n menu_compra/run.sh
    npm run test:browser

`sh -n` requiere un shell POSIX (Linux/macOS o Git Bash en Windows). `npm run test:browser` usa el Python del entorno activado. Como alternativa explícita usa `python tools/run_browser_tests.py --output build/browser-evidence`.

Los escenarios cubren regresión funcional, gestión de la clave en modo avanzado, marca/favicon bajo proxy Ingress y enlace automático con una fixture HTTP de Supervisor expresamente identificada. El backend/SQLite y las peticiones HTTP son reales; la fixture no es un Home Assistant ni un Supervisor real. Crean sus propios datos y puertos loopback efímeros; cierran servidores y no acceden al HA del usuario. Informes/capturas en build/browser-evidence, incluido summary.json. Los fallos devuelven código distinto de0, no se convierten en éxitos.

Los temporales usan el directorio temporal del sistema, respetando su configuración. `MENU_COMPRA_TEST_TMPDIR` permite elegir el directorio de los fixtures TCP. `PLAYWRIGHT_BROWSERS_PATH` permite mover la caché de navegadores. Solo como opción deliberada: `PLAYWRIGHT_EXECUTABLE_PATH` o `PLAYWRIGHT_CHANNEL` seleccionan otro navegador instalado; EDGE_PATH se conserva como alias antiguo, sin rutas predefinidas.

## Regenerar gráficos

    python tools/build_icons.py

Se usan artwork/icono-maestro.png y artwork/logotipo-texto.png; no hay fuentes externas ni cachés de generación. Las pruebas regeneran todos los derivados en un checkout temporal y comparan sus píxeles y formatos (sin depender de la compresión PNG del sistema). La aplicación no necesita Node ni Pillow en producción.

## Probar los paquetes, no solo el árbol

    python tools/build_release.py --output-dir build/ci-dist
    python tools/verify_release.py --dist-dir build/ci-dist --evidence-dir build/ci-release-evidence

Activa MENU_COMPRA_VERIFY_UI=1 para repetir los escenarios de navegador sobre la app del instalador extraído. En shell POSIX:

    MENU_COMPRA_VERIFY_UI=1 python tools/verify_release.py --dist-dir build/ci-dist --evidence-dir build/ci-release-evidence

Los paquetes nuevos no sustituyen los de dist/. Las fuentes incluyen los locks, herramientas y workflow, pero no node_modules, datos ni evidencias locales históricas. Los informes de la verificación extraída permanecen en build/ci-release-evidence incluso al eliminar los temporales.

## GitHub Actions

.github/workflows/ci.yml está preparado para push, pull_request y ejecución manual. Ejecuta lint/suite con Python3.12 y3.14, navegador Chromium y extracción/verificación de ZIP; conserva informes como artefactos. Un trabajo aparte construye y comprueba contenedores amd64 y arm64, usando QEMU para arm64. No publica imágenes, no necesita claves de HA/Telegram y usa permisos de lectura del repositorio.

Para ejecutarlo remotamente hay que subir el proyecto a un repositorio GitHub con Actions habilitado. Que el YAML exista o pase validación local NO significa que los jobs hayan terminado en GitHub. Un test de arm64 mediante QEMU tampoco sustituye la validación en un Home Assistant físico aarch64.

## Enlace automático1.1.0

Supervisor se simula mediante una fixture explícita en el escenario de navegador automático. El runner usa --supervisor-fixture y una fábrica solo de tests, fuera de la imagen de producción. Las pruebas de transporte y de flujo Core mantienen esa distinción. No instalan componentes en el HA del usuario ni necesitan sus credenciales.

## Estado de la prueba manual

El usuario confirmó que las pruebas de la versión1.0.0 se realizaron en un Home Assistant de test y todo funcionaba. Esa confirmación no valida por sí sola el nuevo enlace automático1.1.0, que se verifica por separado. Esta es una confirmación del usuario, no una ejecución remota del agente. No ha probado aarch64; queda pendiente. No se han utilizado sus credenciales ni se ha modificado su instalación.
