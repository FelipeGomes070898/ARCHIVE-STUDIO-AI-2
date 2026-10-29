"""Configurações globais (um único arquivo JSON) e pastas do estúdio.

Tudo que o usuário pode trocar fica em DEFAULTS. Para adicionar uma opção nova:
1) coloque o valor padrão aqui; 2) use `settings()["minha_opcao"]` no código;
3) (opcional) crie o campo na aba Configurações de `web/index.html`.
"""
import json
import os
import threading
from pathlib import Path

HOME = Path(os.environ.get("ARCHIVE_STUDIO_HOME", Path.home() / "archive_studio")).expanduser()
PROJECTS = HOME / "projetos"
CACHE = HOME / "cache"
SETTINGS_FILE = HOME / "settings.json"
WEB = Path(__file__).parent / "web"

# Campos secretos: nunca voltam para o navegador, só "configurado: sim/não".
SECRETS = ("gemini_key", "hf_token")

DEFAULTS = {
    # ---- Roteiro (texto) ----
    "script_engine": "gemini",          # gemini | local | manual
    "gemini_key": "",
    "gemini_model": "gemini-flash-latest",
    "gemini_fallbacks": ["gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "local_llm_url": "http://127.0.0.1:11434/v1",   # Ollama, LM Studio, llama.cpp (API compatível OpenAI)
    "local_llm_model": "qwen2.5:7b",

    # ---- Voz ----
    "tts_engine": "edge",               # edge (grátis, online) | kokoro (grátis, local na GPU/CPU)

    # ---- Imagens (GPU) ----
    "image_engine": "zimage",           # zimage | sdxl | flux | cartao
    "image_models": {
        "zimage": "Tongyi-MAI/Z-Image-Turbo",
        "sdxl": "stabilityai/stable-diffusion-xl-base-1.0",
        "flux": "black-forest-labs/FLUX.1-schnell",
    },

    # ---- Vídeo por IA (GPU) ----
    "video_engine": "nenhum",           # nenhum | ltx | wan | maestro
    "video_models": {
        "ltx": "Lightricks/LTX-Video",
        "wan": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
    },
    "max_ai_clips": 6,                  # quantas cenas viram vídeo por IA (o resto usa câmera Ken Burns)
    "ai_clip_seconds": 5,

    # ---- Ponte Maestro / WanGP (usa a instalação do usuário, sem copiar código) ----
    "maestro_dir": "",                  # pasta que contém wgp.py (no Maestro/Pinokio: .../maestro/app)
    "maestro_python": "",               # python do ambiente do Maestro (vazio = detectar)
    "maestro_model": "ltx2_22B_distilled",
    "maestro_args": "--profile 4",
    "maestro_steps": 0,                 # 0 = padrão do modelo

    # ---- Desempenho ----
    "gpu_profile": "auto",              # auto | rapido | equilibrado | economico
    "depth_model": "depth-anything/Depth-Anything-V2-Small-hf",   # profundidade do parallax 2.5D
    "hf_token": "",
}

_lock = threading.Lock()
_cache = None


def ensure_dirs():
    for p in (HOME, PROJECTS, CACHE):
        p.mkdir(parents=True, exist_ok=True)


def _merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def settings():
    """Configurações atuais (padrões + arquivo + variáveis de ambiente)."""
    global _cache
    with _lock:
        if _cache is None:
            data = {}
            if SETTINGS_FILE.exists():
                try:
                    data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}
            _cache = _merge(DEFAULTS, data)
            if not _cache["gemini_key"]:
                _cache["gemini_key"] = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
            if not _cache["hf_token"]:
                _cache["hf_token"] = os.environ.get("HF_TOKEN", "")
        return _cache


def update(changes):
    """Grava só as chaves conhecidas. Segredo vazio não apaga o salvo."""
    global _cache
    cur = settings()
    clean = {}
    for k, v in (changes or {}).items():
        if k not in DEFAULTS:
            continue
        if k in SECRETS and not v:
            continue
        clean[k] = v
    with _lock:
        _cache = _merge(cur, clean)
        ensure_dirs()
        SETTINGS_FILE.write_text(json.dumps(_cache, ensure_ascii=False, indent=2), encoding="utf-8")
        if _cache.get("hf_token"):
            os.environ["HF_TOKEN"] = _cache["hf_token"]
    return _cache


def public_settings():
    """Cópia segura para o navegador (sem segredos)."""
    s = dict(settings())
    for k in SECRETS:
        s[k] = ""
        s[k + "_set"] = bool(settings().get(k))
    return s


def reset_cache():
    """Usado pelos testes para recarregar o arquivo."""
    global _cache
    with _lock:
        _cache = None
