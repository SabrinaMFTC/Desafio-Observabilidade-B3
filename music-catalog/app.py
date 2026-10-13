import logging
import os
import random
import time

from flask import Flask, jsonify, request

from json_logging import setup_logging
from prom_metrics import init_metrics

setup_logging()
logger = logging.getLogger(__name__)

app = Flask(__name__)
init_metrics(app)

# Chave em minúsculas para a busca não depender de maiúsculas; o valor guarda a grafia original.
CATALOG = {
    ("foo fighters", "everlong"): {"artist": "Foo Fighters", "title": "Everlong", "bpm": 158},
    ("avicii", "levels"): {"artist": "Avicii", "title": "Levels", "bpm": 126},
    ("massive attack", "teardrop"): {"artist": "Massive Attack", "title": "Teardrop", "bpm": 77},
}

# Probabilidades entre 0 e 1; tempos em milissegundos.
FAILURE_RATE = float(os.environ.get("FAILURE_RATE", "0.05"))
LATENCY_MIN_MS = float(os.environ.get("LATENCY_MIN_MS", "10"))
LATENCY_MAX_MS = float(os.environ.get("LATENCY_MAX_MS", "50"))
SLOW_RATE = float(os.environ.get("SLOW_RATE", "0.02"))
SLOW_MIN_MS = float(os.environ.get("SLOW_MIN_MS", "1000"))
SLOW_MAX_MS = float(os.environ.get("SLOW_MAX_MS", "3000"))

logger.info(
    "music-catalog configured",
    extra={
        "failure_rate": FAILURE_RATE,
        "latency_min_ms": LATENCY_MIN_MS,
        "latency_max_ms": LATENCY_MAX_MS,
        "slow_rate": SLOW_RATE,
        "slow_min_ms": SLOW_MIN_MS,
        "slow_max_ms": SLOW_MAX_MS,
    },
)


def should_fail():
    return random.random() < FAILURE_RATE


def simulate_latency():
    """Espera antes de responder: a maioria das chamadas é rápida, uma pequena parte é lenta."""
    if random.random() < SLOW_RATE:
        delay_ms = random.uniform(SLOW_MIN_MS, SLOW_MAX_MS)
        logger.info("simulated slow response", extra={"delay_ms": round(delay_ms)})
    else:
        delay_ms = random.uniform(LATENCY_MIN_MS, LATENCY_MAX_MS)
    time.sleep(delay_ms / 1000)


def find_track(artist, title):
    key = (artist.strip().lower(), title.strip().lower())
    return CATALOG.get(key)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/tracks")
def list_tracks():
    return jsonify(list(CATALOG.values()))


@app.route("/track")
def get_track():
    artist = request.args.get("artist")
    title = request.args.get("title")

    if not artist or not title:
        return jsonify({"error": "the 'artist' and 'title' parameters are required"}), 400

    # Latência antes do sorteio: falhas também levam tempo, como na vida real.
    simulate_latency()

    # Falha antes da busca: um catálogo indisponível não sabe dizer se a música existe.
    if should_fail():
        logger.warning(
            "simulated failure",
            extra={"reason": "simulated_failure", "http_status": 503},
        )
        return jsonify({"error": "music database temporarily unavailable"}), 503

    track = find_track(artist, title)
    if track is None:
        return jsonify({"error": "track not found"}), 404

    return jsonify(track)


# Só roda com `python app.py` (desenvolvimento local); no container quem inicia é o Gunicorn.
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))