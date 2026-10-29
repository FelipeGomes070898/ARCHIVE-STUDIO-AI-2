"""Narração. Para adicionar uma voz, acrescente-a em LANGS; para outro motor, crie uma função
`_meu_motor(texto, voz, velocidade, saida) -> caminho` e registre em ENGINES."""
import asyncio
import json
import threading
import time
import wave
from pathlib import Path

import numpy as np

LANGS = {
    "pt-BR": {"name": "Português (Brasil)",
              "edge": [("pt-BR-AntonioNeural", "Antonio (masc.)"), ("pt-BR-FranciscaNeural", "Francisca (fem.)"),
                       ("pt-BR-ThalitaMultilingualNeural", "Thalita (fem.)")],
              "kokoro": ("p", [("pm_alex", "Alex (masc.)"), ("pf_dora", "Dora (fem.)"), ("pm_santa", "Santa (masc.)")])},
    "pt-PT": {"name": "Português (Portugal)",
              "edge": [("pt-PT-DuarteNeural", "Duarte (masc.)"), ("pt-PT-RaquelNeural", "Raquel (fem.)")],
              "kokoro": ("p", [("pm_alex", "Alex (masc.)"), ("pf_dora", "Dora (fem.)")])},
    "en-US": {"name": "English (US)",
              "edge": [("en-US-ChristopherNeural", "Christopher (male, deep)"), ("en-US-AndrewNeural", "Andrew (male)"),
                       ("en-US-BrianNeural", "Brian (male)"), ("en-US-GuyNeural", "Guy (male)"),
                       ("en-US-AriaNeural", "Aria (female)"), ("en-US-JennyNeural", "Jenny (female)")],
              "kokoro": ("a", [("am_michael", "Michael (male)"), ("af_heart", "Heart (female)"),
                               ("am_fenrir", "Fenrir (male)")])},
    "es-ES": {"name": "Español",
              "edge": [("es-ES-AlvaroNeural", "Álvaro (masc.)"), ("es-MX-DaliaNeural", "Dalia (fem.)")],
              "kokoro": ("e", [("em_alex", "Alex (masc.)"), ("ef_dora", "Dora (fem.)")])},
    "fr-FR": {"name": "Français",
              "edge": [("fr-FR-HenriNeural", "Henri (masc.)"), ("fr-FR-DeniseNeural", "Denise (fém.)")],
              "kokoro": ("f", [("ff_siwis", "Siwis (fém.)")])},
    "it-IT": {"name": "Italiano",
              "edge": [("it-IT-DiegoNeural", "Diego (masc.)"), ("it-IT-ElsaNeural", "Elsa (femm.)")],
              "kokoro": ("i", [("im_nicola", "Nicola (masc.)"), ("if_sara", "Sara (femm.)")])},
}
DEFAULT_LANG = "pt-BR"


def voices(engine, lang):
    info = LANGS.get(lang) or LANGS[DEFAULT_LANG]
    return info["kokoro"][1] if engine == "kokoro" else info["edge"]


def default_voice(engine, lang):
    return voices(engine, lang)[0][0]


# ------------------------------------------------------------------ Edge TTS (grátis, precisa de internet)
def _edge(text, voice, speed, out, pitch=0):
    """Gera MP3 e, ao lado, `<arquivo>.words.json` com [inicio, fim, palavra] de cada palavra (para legendas exatas)."""
    try:
        import edge_tts  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError("Pacote edge-tts não instalado: pip install edge-tts") from e
    rate = f"{round((speed - 1) * 100):+d}%"
    out = Path(out).with_suffix(".mp3")

    async def run():
        com = edge_tts.Communicate(text, voice, rate=rate, pitch=f"{int(pitch):+d}Hz", boundary="WordBoundary")
        words = []
        with open(out, "wb") as f:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    a = ch["offset"] / 1e7
                    words.append([round(a, 3), round(a + ch["duration"] / 1e7, 3), ch["text"]])
        return words

    last = None
    for attempt in range(4):
        try:
            words = asyncio.run(run())
            if out.exists() and out.stat().st_size > 1000:
                words_file(out).write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
                return out
            last = RuntimeError("áudio vazio")
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Edge TTS falhou ({last}). Confira a internet ou use o motor Kokoro (local).")


def words_file(audio):
    return Path(audio).with_suffix(".words.json")


def load_words(audio):
    f = words_file(audio)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except ValueError:
        return []


# ------------------------------------------------------------------ Kokoro (grátis, local)
_kokoro = {}
_kokoro_lock = threading.Lock()


def _kokoro_tts(text, voice, speed, out, lang_code="p"):
    try:
        from kokoro import KPipeline  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError("Kokoro não instalado: pip install kokoro soundfile (veja o README).") from e
    with _kokoro_lock:
        if lang_code not in _kokoro:
            _kokoro[lang_code] = KPipeline(lang_code=lang_code)
        pipe = _kokoro[lang_code]
        chunks = []
        for _, _, audio in pipe(text, voice=voice, speed=speed):
            a = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            chunks.append(a.astype(np.float32).reshape(-1))
    if not chunks:
        raise RuntimeError("Kokoro não gerou áudio para esta cena.")
    out = Path(out).with_suffix(".wav")
    write_wav(np.concatenate(chunks), out, 24000)
    return out


def write_wav(samples, out, rate):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return out


def synthesize(engine, text, voice, speed, out, lang=DEFAULT_LANG, pitch=0):
    if engine == "kokoro":
        code = (LANGS.get(lang) or LANGS[DEFAULT_LANG])["kokoro"][0]
        return _kokoro_tts(text, voice, speed, out, code)
    return _edge(text, voice, speed, out, pitch)


ENGINES = {"edge": "Edge TTS (grátis, online)", "kokoro": "Kokoro (grátis, local)"}
