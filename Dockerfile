FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PUBVOX_DATA_DIR=/app/data \
    PORT=7860

WORKDIR /app

RUN groupadd --gid 1000 pubvox \
    && useradd --uid 1000 --gid pubvox --home-dir /app --shell /usr/sbin/nologin pubvox \
    && mkdir -p /app/data \
    && chown pubvox:pubvox /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=pubvox:pubvox . .

EXPOSE 7860

USER pubvox

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
