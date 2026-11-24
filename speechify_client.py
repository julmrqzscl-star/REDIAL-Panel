"""Speechify preview client. API credentials stay on the server."""
import base64
import io
import json
import urllib.error
import urllib.parse
import urllib.request
import wave

BASE = "https://api.speechify.ai/v1/"
MODEL = "simba-3.5"

def _request(key, path, payload=None):
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("Speechify rechazó la clave o el acceso a esta voz.") from None
        if exc.code == 429:
            raise RuntimeError("Speechify alcanzó un límite de uso o de solicitudes. Revisa tu plan gratuito.") from None
        raise RuntimeError(f"Speechify no pudo atender la solicitud (HTTP {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("No se pudo conectar con Speechify. Comprueba la conexión.") from None

def list_voices(key):
    voices = []
    cursor = None
    seen = set()
    for _ in range(30):
        query = {"locale": "es", "model": MODEL, "limit": 200}
        if cursor:
            query["cursor"] = cursor
        page = _request(key, "voices?" + urllib.parse.urlencode(query))
        for voice in page.get("voices", []):
            if voice.get("id") and voice.get("locale"):
                voices.append({"id": voice["id"], "name": voice.get("display_name") or voice["id"], "locale": voice["locale"]})
        if not page.get("has_more"):
            return sorted(voices, key=lambda v: (v["locale"].lower() != "es-mx", v["name"].casefold(), v["id"]))
        cursor = page.get("next_cursor")
        if not cursor or cursor in seen:
            raise RuntimeError("No se pudo completar el catálogo de Speechify.")
        seen.add(cursor)
    raise RuntimeError("El catálogo de Speechify supera el límite de páginas.")

def synthesize(key, text, voice_id, locale="es-MX"):
    if not text.strip() or len(text) > 2000:
        raise ValueError("El mensaje debe contener entre 1 y 2000 caracteres.")
    result = _request(key, "audio/speech", {"input": text, "voice_id": voice_id, "model": MODEL, "language": locale, "audio_format": "wav"})
    try:
        audio = base64.b64decode(result["audio_data"], validate=True)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getnframes() < wav.getframerate() // 10 or wav.getsampwidth() != 2:
                raise ValueError("Audio vacío o incompatible.")
            frames = wav.readframes(wav.getnframes())
        if not any(frames):
            raise ValueError("Audio silencioso.")
    except (KeyError, ValueError, wave.Error, EOFError) as exc:
        raise RuntimeError("Speechify no devolvió un WAV válido y audible.") from exc
    return audio
