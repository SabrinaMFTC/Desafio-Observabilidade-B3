import time

from flask import Response, g, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# Healthcheck e scrape não são tráfego real e inflariam o RPS.
_IGNORED_ROUTES = {"/health", "/metrics"}

REQUESTS = Counter(
    "http_requests_total",
    "Total de requisições HTTP recebidas",
    ["method", "route", "status"],
)

# Sem label de status, para manter a cardinalidade baixa.
# Buckets densos entre 10 e 100 ms (latência normal) e em volta do timeout de 2 s.
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Duração das requisições HTTP em segundos",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 2.5, 5),
)


def init_metrics(app):
    """Registra as métricas RED da aplicação e expõe a rota /metrics."""

    @app.before_request
    def _start_timer():
        g.metrics_start = time.perf_counter()

    # Roda também nas respostas 500 de exceções não tratadas.
    @app.after_request
    def _record_request(response):
        # Modelo da rota, não a URL: parâmetros na URL explodiriam a cardinalidade.
        route = request.url_rule.rule if request.url_rule else "unmatched"
        if route not in _IGNORED_ROUTES and "metrics_start" in g:
            elapsed = time.perf_counter() - g.metrics_start
            REQUESTS.labels(request.method, route, str(response.status_code)).inc()
            LATENCY.labels(request.method, route).observe(elapsed)
        return response

    @app.route("/metrics")
    def metrics():
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)