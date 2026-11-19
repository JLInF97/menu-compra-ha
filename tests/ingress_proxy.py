"""Proxy local de pruebas para ejercitar rutas con un prefijo como HA Ingress.

NO es un servidor de producción ni simula la autenticación de Home Assistant.
Ejecutar: python tests/ingress_proxy.py
Interfaz: http://127.0.0.1:8100/api/hassio_ingress/prueba-menu/
"""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PREFIX = "/api/hassio_ingress/prueba-menu/"
SIMULATOR = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Simulación local del panel Home Assistant</title>
<style>
:root{--banner-height:56px;--clip-height:100dvh}*{box-sizing:border-box}
html,body{height:100%;margin:0;overflow:hidden;background:#f7f5ef;font-family:system-ui}
#ha-banner{height:var(--banner-height);display:flex;align-items:center;padding:8px 16px;
background:#03a9f4;color:#fff;font-weight:600;overflow:hidden}
#ha-panel{height:calc(100dvh - var(--banner-height));max-height:var(--clip-height);overflow:hidden;position:relative}
iframe{display:block;width:100%;height:100dvh;border:0}
</style><header id="ha-banner">Home Assistant · Menú y Compra (simulación)</header>
<main id="ha-panel"><iframe id="app-frame" title="Menú y Compra" src="__APP_PATH__"></iframe></main>
</html>""".replace("__APP_PATH__", PREFIX)


class Proxy(BaseHTTPRequestHandler):
    def forward(self):
        if self.path.split("?", 1)[0] == "/ha-simulator" and self.command in ("GET", "HEAD"):
            payload = SIMULATOR.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            return
        if not self.path.startswith(PREFIX):
            self.send_error(404, "La ruta debe conservar el prefijo Ingress")
            return
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size) if size else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection", "content-length")}
        headers["X-Ingress-Path"] = PREFIX.rstrip("/")
        connection = HTTPConnection("127.0.0.1", 8099, timeout=20)
        try:
            connection.request(self.command, "/" + self.path[len(PREFIX):], body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in ("connection", "content-length", "transfer-encoding", "server", "date"):
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        finally:
            connection.close()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = forward


if __name__ == "__main__":
    print(f"Proxy de pruebas: http://127.0.0.1:8100{PREFIX}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8100), Proxy).serve_forever()
