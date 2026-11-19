FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MENU_COMPRA_DATA_DIR=/data \
    MENU_COMPRA_DEV=0

LABEL org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.source="https://github.com/JLInF97/menu-compra-ha"

WORKDIR /opt/menu_compra

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY LICENSE ./LICENSE
COPY run.sh /run.sh
RUN chmod 0755 /run.sh

# Solo comprueba el proceso local; no publica el puerto en el anfitrión.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/api/health', timeout=3).read()"]

CMD ["/run.sh"]
