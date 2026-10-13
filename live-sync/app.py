import logging
import os
import time

import requests
from flask import Flask, jsonify, request

from json_logging import setup_logging
from prom_metrics import init_metrics

setup_logging()
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.json.sort_keys = False  # mantém a ordem de campos do enunciado
init_metrics(app)

MUSIC_CATALOG_URL = os.environ.get("MUSIC_CATALOG_URL", "http://127.0.0.1:8081")
MUSIC_CATALOG_TIMEOUT_S = float(os.environ.get("MUSIC_CATALOG_TIMEOUT_S", "2"))

VISUAL_PRESETS = {
    "Low": "haze_and_spotlights",
    "Medium": "beams_and_color_sweeps",
    "High": "strobes_and_lasers",
}

logger.info(
    "live-sync configured",
    extra={
        "music_catalog_url": MUSIC_CATALOG_URL,
        "music_catalog_timeout_s": MUSIC_CATALOG_TIMEOUT_S,
    },
)


class TrackNotFound(Exception):
    """O catálogo musical não conhece a música pedida."""


class MusicCatalogUnavailable(Exception):
    """O catálogo musical não conseguiu responder (erro, timeout ou fora do ar)."""


def classify_energy(bpm):
    if bpm < 100:
        return "Low"
    if bpm < 130:
        return "Medium"
    return "High"


def fetch_track(artist, title):
    """Consulta o catálogo. Devolve os dados da música e a duração da chamada em ms."""
    start = time.perf_counter_ns()
    try:
        response = requests.get(
            f"{MUSIC_CATALOG_URL}/track",
            params={"artist": artist, "title": title},
            timeout=MUSIC_CATALOG_TIMEOUT_S,
        )
    except requests.Timeout as e:
        raise MusicCatalogUnavailable("timeout") from e
    except requests.ConnectionError as e:
        raise MusicCatalogUnavailable("connection error") from e

    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000

    if response.status_code == 404:
        raise TrackNotFound()
    if response.status_code != 200:
        raise MusicCatalogUnavailable(f"unexpected status {response.status_code}")

    return response.json(), elapsed_ms


# Não consulta o catálogo: uma falha da dependência não deve marcar a API como doente.
@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/live-sync/track")
def live_sync_track():
    artist = request.args.get("artist")
    title = request.args.get("title")

    if not artist or not title:
        return jsonify({"error": "the 'artist' and 'title' parameters are required"}), 400

    try:
        track, elapsed_ms = fetch_track(artist, title)
    except TrackNotFound:
        return jsonify({"error": "track not found"}), 404
    except MusicCatalogUnavailable as e:
        # O motivo vai para o log; o cliente recebe uma mensagem genérica.
        logger.warning(
            "music catalog unavailable",
            extra={"dependency": "music-catalog", "reason": str(e), "http_status": 503},
        )
        return jsonify({"error": "music catalog temporarily unavailable"}), 503

    energy = classify_energy(track["bpm"])

    return jsonify({
        "track": track["title"],
        "artist": track["artist"],
        "bpm": track["bpm"],
        "energy_level": energy,
        "visual_preset": VISUAL_PRESETS[energy],
        "sync_delay_ms": round(elapsed_ms),
    })


# Só roda com `python app.py` (desenvolvimento local); no container quem inicia é o Gunicorn.
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))