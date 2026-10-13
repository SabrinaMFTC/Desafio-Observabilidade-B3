FROM python:3.14-slim

# PYTHONUNBUFFERED: logs aparecem na hora no `docker logs`, sem buffer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

# Dependências antes do código: mudar o código não invalida o cache do pip install.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py .

USER appuser

EXPOSE 8080

# 1 worker: o OTel é configurado antes do fork do Gunicorn; threads atendem a espera de I/O.
CMD ["opentelemetry-instrument", "gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "32", "app:app"]