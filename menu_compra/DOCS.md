# Guía de Menú y Compra

## Requisitos

- **Home Assistant OS** con acceso a la tienda de aplicaciones (antes, complementos). Home Assistant Container por sí solo no instala estas apps.
- Arquitectura **amd64** o **aarch64**; no se declara soporte para equipos de 32 bits.
- Acceso de administrador para instalar la app y un medio para copiar archivos: Samba share o Terminal & SSH.
- Conexión a Internet durante la instalación para descargar `python:3.12-slim` y las dependencias Python. Una vez instalada, la aplicación no necesita servicios externos para su funcionamiento normal.

Esta guía describe **1.1.0**. Lee [las limitaciones de validación](#comprobaciones-y-límites) antes de confiarle la única copia de tus datos. [Repositorio público](https://github.com/JLInF97/menu-compra-ha) · [Releases](https://github.com/JLInF97/menu-compra-ha/releases) · [Licencia MIT](LICENSE).

## Instalar como aplicación local

### Corregir «dockerfile is missing» en 0.1.0

El ZIP de 0.1.0 omitía `Dockerfile` por un error de empaquetado. No indica por sí mismo corrupción del Supervisor. Para 1.1.0 usa **`menu-compra-ha-1.1.0-instalar.zip`**, cuyo directorio raíz es `menu_compra/`, y sustituye por completo los archivos de la carpeta local existente sin desinstalar la app ni borrar su almacenamiento. Consulta su disponibilidad en Releases; esta guía no certifica que el paquete esté publicado.

Comprueba expresamente que **`Dockerfile` y `config.yaml` están juntos** en `/local_apps/menu_compra/` o `/addons/menu_compra/`. El nombre debe ser exactamente `Dockerfile`, sin `.txt` añadido y con la D mayúscula. Actualiza la tienda: debe mostrar la versión **1.1.0**. Si todavía no estaba instalada, pulsa Instalar; si ya lo estaba, Actualizar. No es necesario ejecutar `ha supervisor repair` por este defecto del paquete.

La migración del menú de la versión anterior se realiza al arrancar, conservando sus entradas, catálogo, compra y precios. Haz una copia previa si ya tienes datos.

### 1. Copiar los archivos

La documentación actual de Home Assistant denomina **`local_apps`** al directorio de aplicaciones locales. Accede al recurso `local_apps` mediante Samba o a `/local_apps` desde Terminal & SSH. En instalaciones anteriores se suele exponer **`addons`** o **`/addons`**; usa esa ruta si es la que ofrece tu instalación. El nombre antiguo sigue aceptándose por compatibilidad, aunque Home Assistant lo considera obsoleto.

Copia la carpeta **`menu_compra` completa**, sin renombrarla, de forma que quede uno de estos árboles, según el directorio disponible:

```text
/local_apps/menu_compra/         # nombre actual
# o /addons/menu_compra/         # nombre anterior habitual
    config.yaml
    Dockerfile
    requirements.txt
    run.sh
    README.md
    DOCS.md
    CHANGELOG.md
    app/
        main.py
        db.py
        models.py
        backup.py
        static/
            index.html
            app.js
            style.css
```

No copies solo `app/`; no crees un nivel extra como `menu_compra/menu_compra/config.yaml`; no pongas los archivos en `/config`. No dupliques la misma app en `/local_apps` y `/addons`. Si tu editor usa Windows, conserva **LF**, no CRLF, en `run.sh`.

### 2. Refrescar la tienda

1. Abre **Ajustes → Aplicaciones → Instalar aplicación** para entrar en la tienda. En versiones anteriores: **Ajustes → Complementos → Tienda de complementos**.
2. En el menú superior derecho pulsa **Buscar actualizaciones**; el texto puede aparecer como **Comprobar actualizaciones**.
3. Recarga la página y busca **Menú y Compra** en **Aplicaciones locales** (antes, **Complementos locales**).

También puedes instalar desde el repositorio público `https://github.com/JLInF97/menu-compra-ha`, añadiéndolo en Repositorios de la tienda. No cambies de instalación local a repositorio como si fuera una actualización: son apps distintas con identificadores, datos y claves separados. Exporta/restaura y elige explícitamente qué instalación enlazar; no se migran los datos ni se reemplaza la entrada existente silenciosamente. La instalación local puede seguir actualizándose manualmente. [Guía de migración](https://github.com/JLInF97/menu-compra-ha/blob/main/ENLACE_AUTOMATICO.md#migrar-de-local-a-repositorio).

### 3. Instalar, iniciar y abrir

1. Entra en **Menú y Compra** y pulsa **Instalar**. El Supervisor construye la imagen en el propio equipo; la primera vez puede tardar varios minutos.
2. Pulsa **Iniciar** y revisa la pestaña **Registro**.
3. Comprueba **Iniciar al arrancar** si deseas que se inicie con Home Assistant; está activado por defecto.
4. Activa **Mostrar en la barra lateral** y abre **Interfaz web**. También puedes entrar desde **Menú y compra**, con el icono de cubiertos.

No hay opciones obligatorias que configurar. **No abras el puerto 8099 en el router ni publiques puertos del contenedor.** El acceso pasa por Home Assistant Ingress.

## Primeros pasos

### Catálogo y supermercados

1. Crea tus supermercados y ajusta las categorías a tu forma de comprar.
2. Da de alta productos con nombre, categoría, supermercado y unidad (`ud`, `kg` o `l`). Elige una unidad coherente con el precio: por pieza, por kilogramo o por litro.
3. Introduce tus precios reales en euros. Internamente se guardan como enteros de céntimos para evitar errores de coma flotante en los importes.
4. Para comparar tiendas, crea registros del producto para cada supermercado. No se consultan folletos, tiendas en línea ni bases de precios externas.

El catálogo empieza sin productos ni precios de ejemplo. Incluye categorías iniciales y el supermercado **Sin especificar**. Ya no existe la opción Archivar. Los productos archivados en versiones antiguas se conservan y vuelven a estar visibles para que puedas editarlos o eliminarlos.

### Eliminar un producto definitivamente

La ficha ofrece **Eliminar producto**, con confirmación. Borra el producto del catálogo, sus líneas de compra, todo su historial de precios y sus asociaciones de ingredientes antiguas. No crea una papelera ni una marca de archivo. No borra textos libres del menú, aunque contengan el mismo nombre.

El borrado actúa sobre la base actual. No puede reescribir copias JSON, copias de Home Assistant ni archivos descargados previamente. SQLite usa `secure_delete` para reducir restos internos; no se promete borrado forense del disco o de copias externas.

### Enlace automático con Home Assistant y Telegram (1.1.0)

Instala/inicia la app 1.1.0; copia el componente 1.1.0 a `/config/custom_components/menu_compra/` y **reinicia Core**. Con una sola app descubierta la entrada se crea automáticamente en **Ajustes → Dispositivos y servicios**, sin escribir URL ni copiar claves. Con varias instalaciones hay que elegir, nunca se selecciona una arbitrariamente. El componente personalizado requiere esa copia manual una vez y su reemplazo al actualizar: la app no puede instalar código en `/config` por sí sola.

El paquete `menu-compra-ha-1.1.0-integracion.zip` incluye `custom_components/menu_compra/` y el blueprint para copiar bajo `/config`. Está dirigido a HA Core 2026.11.1. Tras el enlace, configura explícitamente en las opciones la entidad de eventos de Telegram Bot y los chats permitidos; crea la automatización del blueprint. Una lista vacía desactiva Telegram: **el descubrimiento no autoriza chats ni grupos**. No añadas otro polling/webhook para el mismo bot. [Guía Telegram, comandos y acciones](https://github.com/JLInF97/menu-compra-ha/blob/main/HA_TELEGRAM.md) · [Guía del enlace automático](https://github.com/JLInF97/menu-compra-ha/blob/main/ENLACE_AUTOMATICO.md).

Una app nueva bajo Supervisor activa la conexión y genera una clave al arrancar; los ajustes existentes conservan clave y estado. Si estaba desactivada (`enabled: false`), pulsa **Activar** solo si quieres usarla; no hay campos que rellenar. Supervisor proporciona la identidad real de la app, no se adivina un hostname ni un prefijo de repositorio. La API de máquina sigue limitada a menú, compra y consultas de catálogo con Bearer propio; no cambia las protecciones web ni habilita puertos. Docker sin Supervisor, desarrollo y migraciones especiales disponen de **Configuración manual avanzada**, no es el flujo normal.

Desactivar impide nuevas llamadas, conserva la clave y retira el anuncio; el reinicio no reactiva una desactivación explícita. Regenerar invalida la clave anterior y reanuncia: la entrada gestionada de la misma app la actualiza automáticamente; solo el modo manual requiere copiarla. La clave se guarda en `/data/ha_bridge.json`, excluido de exportaciones JSON e instaladores, pero incluido en una copia completa de Supervisor: protege tus copias. Restaurar un JSON de datos no cambia la conexión. Autorizar un grupo permite gestionar los datos compartidos a sus participantes según las reglas de los botones.

En Datos y ajustes, `announced` solo indica **anuncio aceptado por Supervisor**, no prueba que Core haya terminado de enlazar. Si Core está apagado o falta el componente, hay reintentos por intervalo sin bloquear la interfaz ni rotar la clave; instala/actualiza el componente, reinicia Core y comprueba la entrada y una acción de lectura. `unavailable` no se soluciona inventando una URL: consulta [estados y diagnóstico](https://github.com/JLInF97/menu-compra-ha/blob/main/ENLACE_AUTOMATICO.md#estados-y-diagnóstico).

La interfaz web y las funciones locales siguen disponibles sin Telegram. Telegram necesita Internet y recibe el contenido de los mensajes que envíes o consultes. Las pruebas locales no equivalen a verificar una instalación real en Core/Supervisor.

### Gestionar categorías y supermercados

En **Datos y ajustes** están los gestores para crear, editar y eliminar categorías y supermercados. Las categorías permiten nombre, orden y marca de congelados. Los cambios se reflejan en el catálogo y en la lista.

Las listas de gestión no muestran «Sin especificar». Esa opción sigue existiendo y se puede seleccionar al editar un producto, sin perder sus asignaciones ni el contador de pendientes.

Eliminar una categoría o tienda ordinaria reasigna sus productos a **Sin especificar**, sin borrarlos ni borrar precios; el historial conserva el nombre de una tienda eliminada y la señala como eliminada. La categoría y tienda **Sin especificar no se pueden editar ni borrar nunca**, aunque estén vacías. «Sin categoría», de versiones anteriores, se convierte automáticamente a la nueva categoría protegida, preservando los productos. Si mover los productos de una tienda provocaría dos registros con el mismo nombre en la tienda genérica, se rechaza la operación completa: reasigna o distingue esos productos antes de intentarlo de nuevo.

### Menú semanal con varios platos

El menú tiene siete días, con comida y cena. En cada franja puedes guardar varios platos independientes: por ejemplo, **Filetes de cerdo** y **Patatas** en la comida; **Arroz** y **Pollo** en la cena. Usa **Añadir plato** y **Otro plato** para escribir cada uno en su propio campo. Cada plato se edita o elimina por separado, sin sobrescribir los demás. Se admiten hasta 20 platos por comida o cena.

No se divide automáticamente una frase por la palabra «y»: «arroz y leche» podría ser el nombre completo de un plato. Si quieres dos entradas, usa dos campos. La vista semanal ya no muestra subtítulo ni recuentos de platos/comidas y utiliza nombres más grandes.
Un toque en una franja vacía abre el alta de un plato; un toque en el nombre de un plato abre su edición. Se mantienen los accesos por teclado y los botones existentes.

### Añadir a la compra sin recetas

Abre la edición de un plato o crea uno nuevo y pulsa el enlace subrayado **Añadir a la compra** que está justo bajo su nombre. No aparece de forma permanente en las tarjetas semanales. Esa acción añade a la compra sin guardar ni cerrar el editor de menú; guarda el menú al terminar.

- Una coincidencia se autoselecciona, aunque sea parcial. Se usa su precio y **cantidad 1 en su unidad de venta**, salvo que la ajustes; si se vende por kg, 1 equivale a 1 kg.
- Si hay varias candidatas, incluidas dos, eliges producto y supermercado. No se decide una tienda al azar.
- Si no hay coincidencias, al confirmar se crea el producto automáticamente con **precio 0 €, unidad ud, categoría Sin especificar y supermercado Sin especificar**. No se pide otro formulario. Después puedes completar su ficha en Productos.

La comparación exacta no distingue mayúsculas/minúsculas, incluidas las letras acentuadas, pero sí respeta las tildes y el nombre completo. Una coincidencia exacta tiene prioridad sobre nombres parecidos.

No necesitas recetas, ingredientes ni asociaciones previas. Las antiguas recetas de 0.1.0 se conservan en la base de datos y las copias por compatibilidad; no se muestran ni se exigen en el flujo nuevo. Si uno de esos ingredientes antiguos impide cambiar una unidad, crea otro producto para no reinterpretar sus cantidades guardadas.

### Duplicar a la semana siguiente

En la navegación semanal está el botón **Duplicar a la semana siguiente**. La confirmación indica la semana destino. Se desplazan los platos siete días manteniendo comida/cena y su orden; no se modifica la lista de la compra.

Se conservan los platos existentes de destino y se omiten los que ya estén presentes por día, comida/cena y nombre. Pulsarlo otra vez no duplica lo ya copiado. Si una comida de destino superaría los 20 platos, se rechaza toda la operación sin copiar una parte ni borrar nada.

### Lista de la compra y precios

El nombre del producto y el botón Editar de cada línea abren directamente su ficha. Los nombres son más grandes y los controles de unidades más compactos. En Productos, «+ A la lista» agrega directamente 1 unidad del producto de esa tarjeta al precio actual, sin pedir cantidad ni precio; puedes ajustarlos después.

El editor abierto desde la compra no incluye campo de notas; las notas antiguas se conservan sin cambiarlas al guardar. En el catálogo se mantiene su edición habitual.

El badge de Productos indica cuántos registros tienen categoría **Sin especificar**, no cuántos tienen supermercado genérico. Se oculta cuando todos están clasificados y cambia al crear, editar o eliminar productos.

- Escribe el nombre en **Añadir a la lista** y confirma: una coincidencia se autoselecciona, varias requieren elegir y un nombre inexistente se crea a precio 0 con valores genéricos. No se crea nada mientras escribes, solo al confirmar.
- Los botones **−/+** restan o suman 1 de la unidad del producto; el campo sigue admitiendo edición manual y fracciones. Restar nunca elimina la línea: al llegar a 1 o menos se deshabilita −. Para quitarla utiliza Quitar.
- Puedes indicar un precio al añadirlo; si cambia el del catálogo se registra en su historial.
- La lista se agrupa por categorías y deja siempre **congelados al final**.
- La pantalla muestra título, contador comprados/total y lista, sin panel de pendientes ni notas. En móvil, el alta está en el **+ flotante**, por encima de la navegación fija inferior. En escritorio permanece Añadir a la lista.
- Para exportar, **Limpiar comprados** o **Limpiar todos** utiliza Datos y ajustes. Limpiar todos pide confirmación y solo vacía la lista: no elimina catálogo, historial o menú.
- Añadir otra vez un producto pendiente suma la cantidad y aplica el precio actual a esa línea. Si ya estaba comprado, vuelve a quedar pendiente con la nueva cantidad.

La lista está **sincronizada con el catálogo**. Editar el producto o su precio actualiza precio, supermercado, categoría y unidad de su línea, conservando cantidad y marca de comprado. Se aplica también a líneas antiguas al arrancar o restaurar. El historial de precios se conserva por separado; no es un historial de tickets ni de compras cerradas.

## Compartir en casa y privacidad

### Altura visible dentro de Home Assistant

La barra móvil, el FAB y los diálogos se ajustan al viewport visible y, cuando comparten origen, a la posición y recortes del iframe y sus contenedores, incluidos hosts Shadow DOM. No se resta una altura fija de banner ni se modifica la página de Home Assistant. Se recalcula al redimensionar, rotar o cambiar el banner.

Si se incrusta en una página de otro origen, el navegador impide leer su geometría externa y se usa el viewport propio como alternativa. Las comprobaciones del banner se realizan en un simulador local; no sustituyen la verificación en el dispositivo real.

Cada persona entra con su propia cuenta de Home Assistant. Ingress gestiona el inicio de sesión; la app no pide otra contraseña. `panel_admin: false` permite mostrar el panel a usuarios no administradores.

Todos los que acceden a esta app trabajan sobre **los mismos datos**: catálogo, lista, menú e historiales. No hay separación por usuario, acceso de solo lectura ni papelera de restauraciones. También pueden reemplazar los datos con una restauración JSON. Concede acceso solo a personas de confianza y recarga la vista para recoger cambios hechos desde otro dispositivo.

Los datos se almacenan localmente y no se envían a servicios de IA. Un JSON exportado contiene información doméstica: guárdalo en un lugar privado.

## Persistencia, copias y restauración

### Copias de Home Assistant

La base de datos está en **`/data/menu_compra.sqlite3`**, en el almacenamiento privado y persistente que proporciona el Supervisor. Se conserva al reiniciar y actualizar la app. No necesitas mapear `/share`, `/config` ni el directorio de Home Assistant.

Crea una copia de seguridad de Home Assistant que **incluya Menú y Compra** antes de actualizar o de modificar muchos datos. La configuración usa **`backup: cold`**: el Supervisor detiene temporalmente la app para copiar SQLite de forma coherente. Mientras se hace la copia, no estará disponible. Para recuperar esa copia, utiliza la restauración de Home Assistant e incluye los datos de esta aplicación.

No copies el archivo SQLite mientras esté en uso: puede haber datos en los archivos auxiliares WAL. Prefiere las copias del Supervisor o la exportación JSON. Antes de desinstalar, exporta el JSON y crea una copia: la desinstalación puede eliminar el almacenamiento de la app.

### Exportación JSON de la aplicación

La API ofrece **`GET api/backup`**, relativo a la raíz de la app. Devuelve un documento con `format: "menu-compra"`, `version: 3`, fecha de exportación y las tablas de categorías, supermercados, productos, historial de precios, datos antiguos de recetas/ingredientes, menú y lista. No es la exportación de la compra en texto. El restaurador admite **versiones 1, 2 y 3**; las copias antiguas se convierten sin perder sus platos.

La copia JSON admite hasta **64 MiB y 100.000 registros** sumando todas las tablas. Si los supera, la exportación se rechaza con una explicación en lugar de descargar un archivo imposible de restaurar: utiliza una copia de seguridad de Home Assistant que incluya la aplicación. Las copias que exporta la app dentro de esos límites son compatibles con su restaurador.

Si utilizas las acciones de copia de la interfaz, guarda el archivo descargado fuera de Home Assistant. El mecanismo por API también se puede usar desde la consola del navegador, **seleccionando el contexto del iframe de Menú y Compra**, no el de la página principal de Home Assistant:

```javascript
{
  const response = await fetch('api/backup');
  if (!response.ok) throw new Error(await response.text());
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = 'menu-compra-copia.json';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
```

Las rutas de documentación `/api/backup` y `/api/restore` son internas al servidor. En Ingress usa **`api/backup`** y **`api/restore`** sin la barra inicial; la URL de Home Assistant incorpora un prefijo variable. No publiques ni compartas el token de esa URL.

### Restauración JSON: reemplaza todos los datos

**Exporta primero el estado actual.** La restauración no mezcla ni añade: reemplaza el contenido compartido de la aplicación. Avisa a los demás usuarios para que dejen de editar durante la operación.

Envía el JSON completo obtenido anteriormente mediante **`POST api/restore`**, con `Content-Type: application/json` y **`X-Menu-Compra: 1`**. La app valida el formato y las relaciones y lo restaura de forma transaccional. No edites a mano las tablas ni importes una lista de compra en texto como si fuera una copia.

Si necesitas restaurar por API desde el navegador, abre el contexto de consola del iframe de esta app y ejecuta este selector de archivo. La confirmación es obligatoria porque la operación es destructiva:

```javascript
{
  const file = await new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.onchange = () => resolve(input.files[0] || null);
    input.oncancel = () => resolve(null);
    input.click();
  });
  if (file) {
    const data = JSON.parse(await file.text());
    if (confirm('Se reemplazarán TODOS los datos compartidos. ¿Continuar?')) {
      const response = await fetch('api/restore', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Menu-Compra': '1'},
        body: JSON.stringify(data)
      });
      if (!response.ok) throw new Error(await response.text());
      location.reload();
    }
  }
}
```

Después, comprueba el catálogo, la lista y el menú. Conserva también una copia del código fuente de la app: una exportación JSON contiene los datos, no el instalador ni la imagen.

## Actualizar una instalación local

1. Exporta los datos y crea una copia de seguridad de Home Assistant con esta app incluida.
2. Para pasar de 1.0.0 a 1.1.0 con integración HA, **actualiza primero el componente** en `/config/custom_components/menu_compra/` y **reinicia Core**. Después sustituye los archivos de `/local_apps/menu_compra` (o `/addons/menu_compra`) por la app 1.1.0 completa. No toques `/data` ni cambies el slug.
3. Comprueba que `version` en `config.yaml` es superior a la instalada, busca actualizaciones en la tienda y pulsa **Actualizar**. El Supervisor reconstruye la imagen local.
4. Revisa Registro, abre la app y verifica que tus datos siguen presentes. Recarga el navegador si conserva recursos anteriores.

No recrees la integración ni la automatización, ni regeneres claves para actualizar. Para la misma app se conservan ID de entrada, entidad Telegram y chats/opciones; una entrada manual con la misma URL puede adoptarse. Si apunta a otra instalación se explica el conflicto antes de cambiarla. Se respeta `enabled: false`: pulsa Activar si quieres enlazar. La integración 1.1.0 admite backends 0.6.0/1.0.0/1.1.0 para facilitar la transición. [Actualización paso a paso](https://github.com/JLInF97/menu-compra-ha/blob/main/ENLACE_AUTOMATICO.md#actualizar-desde-100).

Para probar cambios propios, incrementa la versión y sigue ese procedimiento. No uses la desinstalación como método de actualización: puede borrar los datos. Pasar de local a repositorio no es este procedimiento: requiere migración explícita de datos y elección de app.

## Seguridad y detalles del empaquetado

- Imagen base multi-arquitectura **`python:3.12-slim`**, con `FROM` directo. No se necesita `build.yaml`, actualmente obsoleto.
- Se utiliza `init: true`: esta imagen no contiene S6 ni Bashio y el Supervisor añade el init de Docker.
- Uvicorn escucha en `0.0.0.0:8099` **dentro** del contenedor. No hay `ports`, `host_network` ni permisos ampliados `hassio_api`/`homeassistant_api`. El descubrimiento solo usa las rutas de Supervisor autorizadas para la propia app; no instala archivos en `/config`.
- Ingress llega desde **`172.30.32.2`**; el backend limita el acceso a ese origen en producción. La comprobación local de salud tiene una excepción específica para localhost.
- `run.sh` usa `exec` y **`--no-proxy-headers`**: la comprobación debe ver la IP real de la conexión, no `X-Forwarded-For`.
- `MENU_COMPRA_DATA_DIR=/data` en producción. **`MENU_COMPRA_DEV=1` solo en desarrollo**, con escucha local en `127.0.0.1`: desactiva la restricción de Ingress y no añade autenticación.
- Las mutaciones de la API requieren `X-Menu-Compra: 1` como protección CSRF. La interfaz lo envía.
- Dependencias directas fijadas en `requirements.txt`: FastAPI y Uvicorn sin extras innecesarios. Sus dependencias transitivas se resuelven al instalar; no es un fichero de bloqueo completo con hashes.

## Resolución de problemas

| Síntoma | Qué revisar |
| --- | --- |
| No aparece entre las apps locales | Ruta local correcta, sin doble carpeta; `config.yaml` en la raíz; arquitectura compatible. Buscar actualizaciones y recargar con Ctrl+F5. Consultar los registros del **Supervisor**, no solo los de la app. |
| Falla la construcción | Acceso a Docker Hub y PyPI, espacio disponible y detalles del registro del Supervisor. No hacen falta `BUILD_FROM`, `build.yaml`, Bashio ni S6. |
| `dockerfile is missing` | Usa el ZIP 0.2.0 o posterior. Confirma que `Dockerfile`, sin extensión `.txt`, esté junto a `config.yaml` dentro de la carpeta local de la app. El ZIP 0.1.0 lo omitía por error. |
| `run.sh` no se encuentra o no arranca | El archivo debe tener finales LF y estar incluido. El Dockerfile le da permisos ejecutables. |
| 403 al entrar directamente por IP/puerto | Es la restricción esperada en producción. Entra desde Home Assistant/Ingress; no actives modo de desarrollo para saltártela. |
| La página carga sin recursos o la API falla | Recarga; los enlaces deben ser relativos a Ingress. No uses `/api/...` ni `/static/...` desde su interfaz. |
| Una petición manual de escritura falla | Usa JSON y la cabecera `X-Menu-Compra: 1`, desde el contexto Ingress correcto. No se necesita un token de administrador de Home Assistant. |
| Un usuario no ve el panel | Comprueba que se activó Mostrar en la barra lateral y que tiene acceso a la app; `panel_admin` está a `false`. |
| Precio o supermercado desactualizado | Comprueba que tienes 1.1.0 y recarga la interfaz. Al editar la ficha, la lista se sincroniza; una sesión abierta en otro dispositivo puede necesitar recarga. |
| No aparece la entrada automática | App/componente 1.1.0, reinicio de Core y conexión activada. `announced` solo confirma el anuncio a Supervisor. Revisa Dispositivos y servicios; consulta la guía de enlace, sin publicar secretos. |
| Servidor no disponible o enlace pendiente | Arranca app/Core, instala el componente si falta y reinicia Core. Hay reintentos sin rotar claves; no abras puertos ni actives modo DEV para arreglarlo. |
| Se descubren varias apps | Elige explícitamente la correcta; local y repositorio tienen datos separados y no se migra la entrada en silencio. |
| Un plato no coincide con un producto | Usa Añadir a la compra: permite escoger entre coincidencias o crear el producto. No se buscan ingredientes de recetas ni se descompone el texto automáticamente. |
| Los datos parecen haberse perdido en desarrollo | Revisa `MENU_COMPRA_DATA_DIR`: otra carpeta implica otra base de datos. En HA el directorio debe ser `/data`. |

## Comprobaciones y límites

Las comprobaciones históricas del empaquetado y de la app anteriores a 1.1.0 se resumen a continuación; **no certifican el nuevo enlace automático**. Incluyen la ruta `local_apps`, el nombre antiguo, Ingress, `init` y las copias en frío:

- Manifiesto remoto de `python:3.12-slim` consultado: incluye Linux `amd64` y `arm64` (el equivalente de `aarch64` en Docker). No implica haber construido ni arrancado la imagen.
- YAML leído con un analizador y aserciones de identidad, arquitecturas, Ingress, `init: true`, copias en frío y ausencia de puertos/permisos adicionales.
- Sintaxis de `run.sh` con `sh -n`; finales LF, `exec` y argumento `--no-proxy-headers` verificados.
- FastAPI `0.162.5` y Uvicorn `0.54.0` consultados en PyPI. Resolución de dependencias solo con paquetes binarios para Python **3.11 y 3.12**, tanto Linux **amd64** como **aarch64**, sin conflictos. Esto no es ejecutar los paquetes en esos cuatro destinos.
- Arranque HTTP real con Python **3.11.16**, dependencias fijadas y SQLite temporal: salud 200, acceso directo 403 en modo producción y cabecera `X-Forwarded-For` incapaz de eludir la restricción. En modo desarrollo, lectura del catálogo y exportación JSON versionada correctas. No se utilizaron datos reales ni un servidor de Home Assistant.

**La confirmación del usuario en un Home Assistant de test corresponde a 1.0.0, no a 1.1.0; no incluyó hardware aarch64.** El agente no ejecutó esa instalación ni usó sus credenciales. Los documentos raíz [VERIFICACION.md](https://github.com/JLInF97/menu-compra-ha/blob/main/VERIFICACION.md), [PREPUBLICACION.md](https://github.com/JLInF97/menu-compra-ha/blob/main/PREPUBLICACION.md) y [CIERRE-1.0.0.md](https://github.com/JLInF97/menu-compra-ha/blob/main/CIERRE-1.0.0.md) conservan ese contexto histórico.

Para 1.1.0 deberán ejecutarse CI y pruebas de los ZIP extraídos con resultados propios; esta guía no afirma que ya hayan pasado. Las fixtures Supervisor/Core, los helpers y esquemas aislados no son una prueba en un runtime real de Home Assistant. El enlace con Core/Supervisor real y la entrega al bot real siguen pendientes de validación.

Al desplegar en otro dispositivo o arquitectura conviene repetir detección en la tienda, construcción/arranque, Ingress, persistencia tras reinicio/actualización y recuperación de copias. La comprobación aarch64 sigue pendiente. La automatización Docker arm64 bajo QEMU, una vez ejecutada, no sustituirá una prueba completa en HA sobre hardware aarch64.

## Referencias oficiales

- [Primera app: carpeta local e instalación](https://contributors.home-assistant.io/apps/first-app/).
- [Referencia de config.yaml](https://contributors.home-assistant.io/apps/reference/configuration/).
- [Ingress: IP de origen, usuarios y rutas relativas](https://contributors.home-assistant.io/apps/guides/ingress/).
- [Imagen, init y Dockerfile sin build.yaml](https://contributors.home-assistant.io/apps/guides/dockerfile/).
- [Almacenamiento y entorno proporcionado por el Supervisor](https://contributors.home-assistant.io/apps/reference/environment/).
- [FastAPI en PyPI](https://pypi.org/project/fastapi/) y [Uvicorn en PyPI](https://pypi.org/project/uvicorn/).
