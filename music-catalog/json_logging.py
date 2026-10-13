import json
import logging
import os
import sys
from datetime import datetime, timezone

from opentelemetry import trace

# Atributos que todo LogRecord já tem; qualquer outro veio de extra={...}.
_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Formata cada log como uma linha de JSON, com o contexto do trace."""

    def __init__(self):
        super().__init__()
        self.service = os.environ.get("OTEL_SERVICE_NAME", "unknown")

    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Span ativo na thread que escreveu o log; fora de uma requisição não há.
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            entry["trace_id"] = format(span_context.trace_id, "032x")
            entry["span_id"] = format(span_context.span_id, "016x")

        # "otel*": atributos que a instrumentação de logging acrescenta; já temos os nossos.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("otel"):
                entry[key] = value

        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


def setup_logging(level=logging.INFO):
    """Envia os logs da aplicação para o stdout em JSON."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    # Acrescenta sem remover: o handler do OpenTelemetry na raiz envia os logs ao Loki.
    root.addHandler(handler)
    root.setLevel(level)