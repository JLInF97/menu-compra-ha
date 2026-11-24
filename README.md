# Menú y Compra para Home Assistant OS

<img src="menu_compra/icon.png" alt="Icono de Menú y Compra" width="96" height="96">

[![Pruebas](https://github.com/JLInF97/menu-compra-ha/actions/workflows/ci.yml/badge.svg)](https://github.com/JLInF97/menu-compra-ha/actions/workflows/ci.yml)

App local en castellano para planificar el menú semanal, mantener una lista de la compra compartida y consultar precios por supermercado. FastAPI + SQLite + HTML/CSS/JavaScript, sin compilación del frontend, CDN ni servicios de IA.

## Instalar en Home Assistant OS

### Desde el repositorio de aplicaciones

En **Ajustes → Aplicaciones → Instalar aplicación → ⋮ → Repositorios**, añade:

https://github.com/JLInF97/menu-compra-ha

[Añadir el repositorio a Home Assistant](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJLInF97%2Fmenu-compra-ha)

Busca **Menú y Compra**, instala la app **1.1.0** e inicia. Se construye desde Dockerfile en tu equipo; no se publica una imagen precompilada. Para enlazar con Home Assistant, copia también el componente **1.1.0** a `/config/custom_components/menu_compra/` y **reinicia Core**. A partir de ahí la entrada se crea automáticamente, sin escribir URL ni copiar claves. El componente personalizado no puede instalarse solo desde la app y no se distribuye por HACS. [Guía de enlace automático](ENLACE_AUTOMATICO.md).

**Si ya usas la instalación local:** no la sustituyas por la del repositorio como si fuera una actualización. Son aplicaciones distintas, con identificadores, `/data` y claves separados. Puedes seguir actualizando la local. Para cambiar de origen, exporta/restaura los datos y elige explícitamente la instalación que quieres enlazar; no se migra ni se sustituye la entrada existente en silencio. El JSON no transfiere la clave privada. [Migración entre instalaciones](ENLACE_AUTOMATICO.md#migrar-de-local-a-repositorio).

### Instalación y actualización manual mediante ZIP

**Actualizar desde 1.0.0:** haz copia de seguridad; copia primero el componente **1.1.0** bajo `/config/custom_components/menu_compra/` y reinicia Core; después actualiza la misma app a **1.1.0**. No desinstales, no borres `/data`, no cambies el slug ni regeneres claves o recrees la integración/automatización. Se conservan datos, clave, ID de entrada y opciones Telegram de la misma instalación. Si la conexión estaba desactivada, se respeta: pulsa **Activar** en Datos y ajustes si quieres usarla, sin rellenar campos. [Pasos y límites de la actualización](ENLACE_AUTOMATICO.md#actualizar-desde-100).

El icono elegido se muestra dentro de la app, como favicon/acceso directo y en su ficha de la tienda. La barra lateral del propio Home Assistant sigue usando `panel_icon` MDI, conforme a su plataforma; no se modifica la interfaz padre de HA.

Para instalar utiliza **`menu-compra-ha-1.1.0-instalar.zip`**: al descomprimir aparece directamente `menu_compra/`. El ZIP de fuentes `menu-compra-ha-1.1.0.zip` incluye además pruebas, arranque Windows y herramientas de verificación. Consulta la disponibilidad de los paquetes en Releases; estas instrucciones no certifican su publicación. Sustituye los archivos y actualiza: no desinstales ni borres los datos. Haz una copia antes: SQLite y el JSON de copia se mantienen en versiones 4 y 3, respectivamente. La categoría antigua «Sin categoría» se unifica como «Sin especificar» conservando sus productos.

**Corregido el error de 0.1.0 «dockerfile is missing»:** el ZIP anterior omitía por error `Dockerfile`, que no tiene extensión. El empaquetador ahora lo incluye y valida los archivos obligatorios **dentro de ambos ZIP**, no solo en la carpeta fuente. No se necesita ejecutar `ha supervisor repair` para reparar este defecto del paquete. Sustituye la carpeta completa de la app sin desinstalarla ni borrar `/data`.

Copia la carpeta **`menu_compra` completa** a **`/local_apps/menu_compra`** usando Terminal & SSH o Samba (`local_apps`). En instalaciones que siguen exponiendo el nombre anterior, utiliza **`/addons/menu_compra`** (`addons` en Samba). No copies el proyecto a `/config` ni lo dupliques en ambas rutas.

En **Ajustes → Aplicaciones → Instalar aplicación** abre el menú de la tienda y pulsa **Buscar actualizaciones**. En versiones anteriores: **Ajustes → Complementos → Tienda de complementos**. Selecciona **Menú y Compra** entre las apps locales, pulsa **Instalar → Iniciar** y activa **Mostrar en la barra lateral**. La instalación construye la imagen en tu equipo y necesita Internet para obtener Python y dependencias.

Los paquetes se encuentran en [Releases](https://github.com/JLInF97/menu-compra-ha/releases). El ZIP de la app no se instala bajo `/config`; el ZIP de integración sí. También puedes generar los paquetes desde las fuentes con las instrucciones de PRUEBAS.md.

- [Guía completa de instalación, uso y copias de seguridad](menu_compra/DOCS.md).
- [Presentación de la app](menu_compra/README.md).
- [Cambios por versión](menu_compra/CHANGELOG.md).
- [Resultados de pruebas, capturas y comprobaciones pendientes](VERIFICACION.md).

## Qué guarda y cómo se comparte

La versión 1.1.0 añade el enlace automático con Home Assistant, conservando las funciones, el icono, la interfaz y los datos aprobados en 1.0.0. La edición desde la compra sigue sin notas y los gestores siguen ocultando «Sin especificar».

### Home Assistant y Telegram (opcional)

El ZIP **menu-compra-ha-1.1.0-integracion.zip** contiene el componente personalizado y un blueprint para **HA Core 2026.11.1**. Se copian bajo `/config`, no dentro de la app; reinicia Core después. Reutiliza la integración Telegram Bot ya instalada; no crea otro receptor ni necesita su token.

En una app nueva bajo Supervisor, la conexión se activa y genera su clave al arrancar. Supervisor proporciona la identidad real de la app y entrega el descubrimiento al componente: **no introduzcas URL ni contraseña**. Con una sola instalación, no hay campos de conexión que rellenar; con varias, hay que elegir, nunca se toma una al azar. Los ajustes existentes, incluida una desactivación explícita, se respetan. En Datos y ajustes, `announced` solo significa que Supervisor ha aceptado el anuncio: verifica también la entrada en **Dispositivos y servicios**. Si Core está apagado o falta el componente, el anuncio se reintenta sin bloquear la app ni rotar la clave. La conexión no publica puertos.

Después configura explícitamente la entidad de eventos de tu bot y los chats permitidos y crea la automatización desde el blueprint. El enlace automático **no autoriza chats ni grupos**; la lista vacía mantiene Telegram desactivado. La guía y los comandos están en [HA_TELEGRAM.md](HA_TELEGRAM.md). El modo manual queda en **Configuración manual avanzada** para Docker, desarrollo o migraciones especiales. Menú y compra siguen teniendo una única base de datos en la app. Telegram requiere Internet y los mensajes pasan por Telegram; el uso local de la app no depende de ello.

### Funciones de la aplicación

- Menú semanal de comidas y cenas con **varios platos por franja**: por ejemplo, Filetes y Patatas en campos independientes.
- Menú visual más limpio: añadir platos desde cada comida/cena, sin botón verde global ni botones de compra permanentes. El enlace subrayado «Añadir a la compra» está bajo cada nombre al crear o editar el plato.
- Compra por nombre: una coincidencia se autoselecciona; varias requieren elegir; un nombre nuevo se crea al confirmar, con precio 0, unidad ud, categoría y tienda «Sin especificar», sin asistente adicional. No hay recetas ni ingredientes que vincular.
- Lista limpia, con contador comprados/total y productos agrupados; controles −/+ e introducción manual de cantidad, sin menú Cantidad. En móvil el alta se abre con un botón flotante + y la navegación queda fija abajo.
- Duplicación de una semana a la siguiente con confirmación: conserva el destino, evita copiar de nuevo platos ya presentes y no añade nada a la compra.
- Navegación adaptada al área visible del iframe, incluidos banner superior y contenedores recortados; nombres mayores y controles más compactos.
- En la compra, tocar el nombre o Editar abre la ficha. En el menú, tocar una comida vacía añade un plato y tocar su nombre lo edita.
- Desde el catálogo, «+ A la lista» añade directamente 1 unidad al precio actual y a la tienda de esa ficha, sin diálogo.
- Precios en EUR con historial y compra **sincronizada con el catálogo**: cambiar precio, supermercado, categoría o unidad actualiza su línea existente, conservando cantidad y marca de comprado. También se corrigen las líneas antiguas al arrancar o restaurar una copia.
- Datos y ajustes permite crear, editar y eliminar categorías y supermercados; «Sin especificar» es permanente y no se puede editar ni borrar, incluso vacío. La navegación muestra cuántos productos tienen esa categoría. Los productos de otras categorías o tiendas eliminadas se conservan con valores genéricos. Si una reasignación de tienda produciría productos homónimos incompatibles, se rechaza sin tocar datos.
- Borrado definitivo del producto, su historial y referencias de compra/ingredientes, con confirmación. No hay archivo ni papelera. Los textos libres del menú y las copias ya exportadas no se modifican.
- Limpiar comprados y Limpiar todos en ajustes: solo borran líneas de compra, no productos, precios ni menús.
- Las bases de datos de 0.1.0 se migran automáticamente sin perder menú, catálogo, lista ni precios. Las antiguas recetas se conservan en copias y API por compatibilidad, pero ya no forman parte de la interfaz.
- Una única base de datos para todos los usuarios que acceden por Home Assistant. No hay cuentas, listas privadas ni roles propios; todos pueden modificar y restaurar los datos compartidos.

En producción la base es **`/data/menu_compra.sqlite3`**, persistente entre reinicios y actualizaciones. No hay productos ni precios de muestra. `GET api/backup` exporta JSON y `POST api/restore` lo restaura reemplazando los datos; consulta las precauciones en la guía. Las copias de Home Assistant detienen temporalmente la aplicación (`backup: cold`).

## Ejecutar en local para desarrollo

En Windows también puedes ejecutar `iniciar-local.cmd`: requiere `uv`, prepara las dependencias y muestra la dirección local. Esa opción guarda los datos de prueba en `datos-locales/`, separados de Home Assistant.

Requiere **Python 3.11 o posterior**. El contenedor usa Python 3.12. Desde la raíz del proyecto:

### Linux/macOS o shell POSIX

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r menu_compra/requirements.txt
MENU_COMPRA_DEV=1 MENU_COMPRA_DATA_DIR="$PWD/.local-data" \
  python -m uvicorn app.main:app --app-dir menu_compra \
  --host 127.0.0.1 --port 8099 --no-proxy-headers
```

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r menu_compra/requirements.txt
$env:MENU_COMPRA_DEV = "1"
$env:MENU_COMPRA_DATA_DIR = Join-Path $PWD ".local-data"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir menu_compra --host 127.0.0.1 --port 8099 --no-proxy-headers
```

Si usas otra versión de Python, cambia el selector `py -3.11` por el que tengas instalado. Abre <http://127.0.0.1:8099/>. Los datos locales se crean separados de `/data`, dentro de `.local-data/`, excluido de Git. Detén el servidor con Ctrl+C. `GET /api/health` es la comprobación de salud.

**`MENU_COMPRA_DEV=1` desactiva la restricción de origen de Ingress y solo sirve para pruebas locales.** No expongas este servidor a la red, no uses `--host 0.0.0.0` en desarrollo ni actives ese modo en Home Assistant. No tiene autenticación propia.

Para las pruebas automatizadas del proyecto:

```sh
python -m pip install --require-hashes -r requirements-ci.lock
python -m pytest -q
```

## Empaquetado y estado de validación

Las instrucciones reproducibles y la integración continua están en [PRUEBAS.md](PRUEBAS.md). No requieren rutas personales, Edge ni fuentes de Windows. El workflow contempla Python 3.12/3.14, Chromium, ZIP extraídos y contenedores amd64/arm64. Los paquetes de desarrollo se generan en `build/dist`, no sobre las entregas de `dist/`. La [primera ejecución en GitHub](https://github.com/JLInF97/menu-compra-ha/actions/runs/44622830112) es evidencia histórica anterior a 1.1.0, no valida el nuevo enlace automático. Los resultados de 1.1.0 deberán identificarse con su propia ejecución de CI y pruebas de paquetes. No se afirma aquí que ya se hayan ejecutado ni que se haya validado en Core/Supervisor real.

`menu_compra/config.yaml` declara `amd64` y `aarch64`, Ingress en el puerto interno 8099, panel para usuarios no administradores y copia SQLite en frío. No hay puertos publicados, red del anfitrión ni permisos ampliados `hassio_api`/`homeassistant_api`. El descubrimiento usa las rutas autorizadas de Supervisor para la propia app, sin esos permisos. `Dockerfile` utiliza `FROM python:3.12-slim` directamente, sin `build.yaml` ni Bashio/S6; `init: true` permite al Supervisor añadir su init.

`run.sh` debe conservar finales de línea **LF**. Arranca Uvicorn con `--no-proxy-headers` para que la comprobación de la IP de Ingress vea la conexión real y no una cabecera reenviada.

La confirmación del usuario de funcionamiento en un Home Assistant de test corresponde a **1.0.0**, no a 1.1.0; no incluyó hardware aarch64. [PREPUBLICACION.md](PREPUBLICACION.md), [VERIFICACION.md](VERIFICACION.md) y [CIERRE-1.0.0.md](CIERRE-1.0.0.md) conservan ese contexto histórico. Para 1.1.0 queda pendiente validar el enlace en un Core/Supervisor real y el bot real; las fixtures no sustituyen esa prueba. Las entregas 1.0.0 permanecen inmutables.

## Licencia

MIT. Copyright (c) 2026 Jesús. Consulta [LICENSE](LICENSE).

## Referencias oficiales

- [Crear la primera app e instalarla localmente](https://contributors.home-assistant.io/apps/first-app/).
- [Configuración admitida por el Supervisor](https://contributors.home-assistant.io/apps/reference/configuration/).
- [Ingress, URLs relativas y restricción de origen](https://contributors.home-assistant.io/apps/guides/ingress/).
- [Dockerfile, imágenes base y retirada de build.yaml](https://contributors.home-assistant.io/apps/guides/dockerfile/).
