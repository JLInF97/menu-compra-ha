# Preparación de publicación — Menú y Compra 1.0.0

## Validación del usuario

El usuario confirma: «He realizado estas pruebas en un Home Assistant de test y funciona todo. No he probado en arquitectura aarch64».

Se registra como validación manual del usuario, no como una instalación ejecutada por el agente. No se presupone la arquitectura concreta de ese equipo. La validación completa en aarch64 sigue pendiente; disponer de wheels o preparar un job QEMU no la sustituye.

## Cambios de desarrollo, sin funcionalidades nuevas

- Temporales configurables y rutas calculadas desde el proyecto, sin carpetas del usuario de desarrollo.
- Playwright declarado con versión exacta y package-lock; Chromium instalado por la herramienta, no Edge obligatorio.
- Icono y logo reproducibles desde PNG incluidos. Se conserva el diseño exacto y no se distribuyen fuentes del sistema.
- requirements-ci.lock universal con dependencias transitivas fijadas y hashes para Python3.12/3.14.
- Workflow de GitHub Actions con lint, pruebas Python, navegador real y verificación de paquetes extraídos; trabajo independiente de contenedores amd64/arm64.
- Nuevos paquetes e informes bajo build/, conservando las entregas originales de dist/. Se excluyen node_modules, datos y antiguas evidencias locales de las nuevas fuentes.

Las instrucciones completas están en PRUEBAS.md. El código funcional, protocolo, esquema de datos, credenciales e interfaz no se modifican.

## Resultados locales de esta preparación

- Suite completa ejecutada en Windows con Python3.12.14 y3.14.9: 472 pruebas correctas en cada versión, sin fallos ni omisiones. Persiste un aviso de deprecación del cliente Starlette/httpx, no un fallo.
- 56 comprobaciones de navegador con Chromium de Playwright1.65.1, backend y SQLite reales, sin NODE_PATH ni selección obligatoria de Edge.
- Regeneración del icono/logo en un checkout temporal sin fuentes del sistema; igualdad byte a byte de los gráficos con la entrega1.0.0.
- Ruff, sintaxis JS/POSIX y comprobación de rutas locales correctos. Los SHA de las seis Actions se han contrastado con los tags de sus repositorios oficiales.
- En el momento de estas comprobaciones locales, antes del primer push, GitHub Actions no se había ejecutado remotamente. El smoke Docker falla con un informe explícito porque el daemon local no está disponible; no se presenta como una prueba aprobada de Docker o arm64. Sus probes HTTP y de persistencia sí se han ejercitado localmente y su orquestación tiene fixtures declaradas.

## Licencia MIT

El titular ha elegido MIT. El texto completo está en LICENSE, con autoría de Jesús. Permite uso, modificación y redistribución, también comercial, conservando el aviso de autoría/licencia y sin garantías; no obliga a publicar el código de derivados.

Referencia: https://choosealicense.com/licenses/mit/

## Qué falta antes de anunciar la publicación

- Licencia y autoría elegidas: MIT, Jesús (completado).
- Repositorio público creado: https://github.com/JLInF97/menu-compra-ha. Se publican código, gráficos aprobados, licencia, documentación y pruebas; se excluyen claves, datos, cachés, evidencias locales y contratos internos de desarrollo.
- Subir el workflow y comprobar su primera ejecución real en GitHub Actions. Preparado/validado localmente no significa ejecutado en GitHub.
- Validar aarch64 antes de anunciarla como arquitectura probada. El job Docker arm64 mediante QEMU aporta una comprobación técnica adicional, no una prueba completa en hardware con HA.

La revisión de seguridad y política de mantenimiento públicas pueden hacerse por separado; las comprobaciones existentes no se presentan como auditoría independiente.
