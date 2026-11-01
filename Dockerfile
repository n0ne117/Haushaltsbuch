FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    TZ=Europe/Vienna

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Non-root user matching Unraid's appdata owner (nobody:users = 99:100).
RUN useradd --uid 99 --gid 100 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown 99:100 /data

COPY app ./app

USER 99:100
EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"

# Single worker: SQLite + in-process jobs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
