"""Detecção de GPU e perfis de memória (ideia dos perfis do WanGP/Maestro, reimplementada com diffusers).

Perfis:
  rapido      modelo inteiro na VRAM (GPUs de 24 GB ou mais)
  equilibrado partes do modelo vão para a VRAM só quando usadas (model offload, ~12-16 GB)
  economico   camada por camada (sequential offload): roda em 6-8 GB, porém mais lento
"""
import gc
import os

_TORCH = None


def torch():
    """Importa o torch só quando precisa (o estúdio abre sem ele)."""
    global _TORCH
    if _TORCH is None:
        import torch as t  # noqa: PLC0415
        _TORCH = t
    return _TORCH


def has_torch():
    try:
        torch()
        return True
    except ImportError:
        return False


def info():
    out = {"torch": False, "cuda": False, "name": "", "vram_gb": 0.0, "ram_gb": _ram_gb()}
    try:
        t = torch()
    except ImportError:
        return out
    out["torch"] = True
    out["torch_version"] = t.__version__
    if t.cuda.is_available():
        p = t.cuda.get_device_properties(0)
        out.update(cuda=True, name=p.name, vram_gb=round(p.total_memory / 1024 ** 3, 1))
    return out


def _ram_gb():
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 1)
    except (ValueError, OSError, AttributeError):
        return 0.0


def pick_profile(requested="auto", need_gb=16):
    """Escolhe o perfil. `need_gb` = VRAM aproximada para o modelo inteiro."""
    if requested in ("rapido", "equilibrado", "economico"):
        return requested
    vram = info()["vram_gb"]
    if vram >= need_gb * 1.15:
        return "rapido"
    if vram >= 10:
        return "equilibrado"
    return "economico"


def dtype():
    t = torch()
    if t.cuda.is_available() and t.cuda.is_bf16_supported():
        return t.bfloat16
    return t.float16 if t.cuda.is_available() else t.float32


def require_cuda():
    if not info()["cuda"]:
        raise RuntimeError(
            "Nenhuma GPU NVIDIA (CUDA) encontrada. Instale o PyTorch com CUDA "
            "(veja o README) ou escolha 'Cartão de texto' / 'Nenhum' nos geradores.")


def apply_profile(pipe, profile):
    """Coloca o pipeline do diffusers na GPU conforme o perfil e liga as economias de VRAM."""
    if profile == "rapido":
        pipe.to("cuda")
    elif profile == "equilibrado":
        pipe.enable_model_cpu_offload()
    else:
        pipe.enable_sequential_cpu_offload()
    vae = getattr(pipe, "vae", None)
    for name in ("enable_tiling", "enable_slicing"):
        fn = getattr(vae, name, None)
        if fn:
            try:
                fn()
            except (NotImplementedError, AttributeError, ValueError):
                pass
    return pipe


def free():
    gc.collect()
    try:
        t = torch()
        if t.cuda.is_available():
            t.cuda.empty_cache()
            t.cuda.ipc_collect()
    except ImportError:
        pass


def is_oom(err):
    return "out of memory" in str(err).lower() or type(err).__name__ == "OutOfMemoryError"
