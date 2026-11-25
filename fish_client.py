"""Fish Audio free-model preview; never silently switch to a paid model."""
import json
import re
import urllib.error
import urllib.request

def synthesize(key, text, reference_id=""):
    if not text.strip() or len(text) > 2000:
        raise ValueError("El mensaje debe contener entre 1 y 2000 caracteres.")
    if reference_id and not re.fullmatch(r"[a-fA-F0-9]{32}", reference_id):
        raise ValueError("El identificador de voz debe tener 32 caracteres hexadecimales.")
    payload = {"text": text, "format": "mp3"}
    if reference_id:
        payload["reference_id"] = reference_id
    request = urllib.request.Request(
        "https://api.fish.audio/v1/tts",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "model": "s2.1-pro-free"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            audio = response.read(20 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("Fish Audio rechazó la clave o el acceso a la voz.") from None
        if exc.code in (402, 429):
            raise RuntimeError("El modelo gratuito no está disponible o alcanzó un límite; no se cambió a un modelo de pago.") from None
        raise RuntimeError(f"Fish Audio no pudo procesar la solicitud (HTTP {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("No se pudo conectar con Fish Audio.") from None
    if len(audio) < 1024 or len(audio) > 20 * 1024 * 1024 or "json" in content_type:
        raise RuntimeError("Fish Audio no devolvió un audio MP3 válido.")
    if not (audio.startswith(b"ID3") or (audio[0] == 255 and audio[1] & 0xE0 == 0xE0)):
        raise RuntimeError("El archivo recibido no tiene una cabecera MP3 reconocible.")
    return audio
