FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PUBVOX_DATA_DIR=/app/data \
    PORT=7860

RUN addgroup -g 1000 pubvox \
    && adduser -D -u 1000 -G pubvox -h /app -s /sbin/nologin pubvox \
    && mkdir -p /app/data \
    && chown pubvox:pubvox /app/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY pubvox ./pubvox

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','7860')+'/api/health', timeout=2)"]

USER pubvox

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
