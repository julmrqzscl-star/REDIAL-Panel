"""Local Spanish narration voices using Kokoro ONNX."""
import hashlib
import io
import os
import tempfile
import urllib.request
import wave
from pathlib import Path

import numpy as np
import streamlit as st

VOICES = {"Dora": "ef_dora", "Alex": "em_alex", "Santa": "em_santa"}
FILES = {
    "kokoro-v1.0.int8.onnx": "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"

def _valid(path, expected):
    if not path.is_file(): return False
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest() == expected

@st.cache_resource(show_spinner=False, max_entries=1)
def _load():
    from kokoro_onnx import Kokoro
    directory=Path(tempfile.gettempdir()) / "redial-kokoro"
    directory.mkdir(parents=True, exist_ok=True)
    for name, digest in FILES.items():
        path=directory/name
        if _valid(path,digest): continue
        fd, temp = tempfile.mkstemp(prefix="redial-",dir=directory)
        try:
            with os.fdopen(fd,"wb") as out, urllib.request.urlopen(BASE+name, timeout=90) as src:
                while True:
                    chunk=src.read(1024*1024)
                    if not chunk: break
                    out.write(chunk)
            if not _valid(Path(temp),digest): raise ValueError("El modelo de voz no pudo verificarse.")
            os.replace(temp,path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    return Kokoro(str(directory/"kokoro-v1.0.int8.onnx"), str(directory/"voices-v1.0.bin"))

def generate(text, voice, rate):
    if voice not in VOICES: raise ValueError("Voz no reconocida.")
    samples, sample_rate = _load().create(text, voice=VOICES[voice], speed=float(rate), lang="es")
    samples=np.asarray(samples,dtype=np.float32)
    if samples.size < sample_rate//10 or not np.isfinite(samples).all(): raise ValueError("El motor no generó audio válido.")
    peak=float(np.max(np.abs(samples)))
    if peak < 0.001: raise ValueError("El motor generó audio demasiado bajo.")
    samples=np.clip(samples/max(peak, 1e-8)*0.90,-1.0,1.0)
    pcm=(samples*32767).astype("<i2").tobytes()
    output=io.BytesIO()
    with wave.open(output,"wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(sample_rate); wav.writeframes(pcm)
    return output.getvalue()
