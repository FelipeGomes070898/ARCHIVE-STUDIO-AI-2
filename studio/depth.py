"""Mapa de profundidade para o parallax 2.5D.

Usa o Depth Anything V2 Small (pequeno, roda até na CPU) via transformers. Sem torch/transformers
ou sem internet, cai numa profundidade sintética (chão perto, céu longe, centro em destaque).
Saída: PNG em tons de cinza, branco = perto.
"""
import threading

import numpy as np
from PIL import Image, ImageFilter

from . import config

_lock = threading.Lock()
_pipe = {"model": None, "obj": None}


def _model_depth(img):
    from transformers import pipeline  # noqa: PLC0415
    from . import gpu  # noqa: PLC0415
    model = config.settings().get("depth_model")
    with _lock:
        if _pipe["model"] != model:
            device = 0 if gpu.info()["cuda"] else -1
            _pipe.update(model=model, obj=pipeline("depth-estimation", model=model, device=device))
        res = _pipe["obj"](img)
    d = np.asarray(res["depth"], dtype=np.float32)
    if d.shape[:2] != (img.height, img.width):
        d = np.asarray(Image.fromarray(d).resize((img.width, img.height), Image.BICUBIC), dtype=np.float32)
    return d


def synthetic(img):
    """Profundidade aproximada sem IA: parte de baixo perto, alto longe, centro e bordas nítidas à frente."""
    w, h = img.size
    y = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    x = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    ground = np.repeat(y, w, axis=1) ** 1.3
    center = np.exp(-(x ** 2) * 1.8) * np.exp(-((y - 0.6) ** 2) * 4)
    gray = np.asarray(img.convert("L").filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(w / 60)),
                      dtype=np.float32) / 255.0
    return 0.6 * ground + 0.3 * center + 0.1 * gray / (gray.max() + 1e-6)


def estimate(image_path, out, log=print):
    """Gera o mapa de profundidade de `image_path` em `out`. Retorna 'ia' ou 'sintetica'."""
    with Image.open(image_path) as im:
        img = im.convert("RGB")
    kind = "ia"
    try:
        d = _model_depth(img)
    except Exception as e:  # noqa: BLE001 (sem torch, sem internet, modelo indisponível...)
        log(f"Profundidade por IA indisponível ({str(e)[:120]}); usando profundidade sintética.")
        d, kind = synthetic(img), "sintetica"
    d = d - d.min()
    d = d / (d.max() + 1e-6)
    Image.fromarray((d * 255).astype(np.uint8)).save(out)
    return kind
