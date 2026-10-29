"""Geração de imagens na GPU com diffusers (modelos abertos, grátis).

Para adicionar um modelo: acrescente um item em SPECS com a classe do diffusers, passos e tamanhos,
e o id do Hugging Face em config.DEFAULTS["image_models"].
"""
import threading

from .. import config, gpu, media

SPECS = {
    "zimage": dict(label="Z-Image Turbo — rápido e realista (8 GB+)", cls="ZImagePipeline",
                   steps=8, guidance=0.0, negative=False, need_gb=22,
                   sizes={"16:9": (1536, 864), "9:16": (864, 1536), "1:1": (1152, 1152)}),
    "sdxl": dict(label="SDXL — leve, roda em GPUs de 6-8 GB", cls="StableDiffusionXLPipeline",
                 steps=28, guidance=6.0, negative=True, need_gb=10, variant="fp16",
                 sizes={"16:9": (1344, 768), "9:16": (768, 1344), "1:1": (1024, 1024)}),
    "flux": dict(label="FLUX.1 schnell — alta qualidade, pesado (12 GB+)", cls="FluxPipeline",
                 steps=4, guidance=0.0, negative=False, need_gb=34, extra={"max_sequence_length": 256},
                 sizes={"16:9": (1360, 768), "9:16": (768, 1360), "1:1": (1024, 1024)}),
    "cartao": dict(label="Cartão de texto — sem GPU (rascunho rápido)", cls=None,
                   sizes={"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}),
}

_lock = threading.Lock()
_state = {"key": None, "pipe": None, "profile": None}


def labels():
    return {k: v["label"] for k, v in SPECS.items()}


def _load(engine, profile):
    import diffusers  # noqa: PLC0415
    spec = SPECS[engine]
    s = config.settings()
    model_id = s["image_models"].get(engine)
    cls = getattr(diffusers, spec["cls"], None)
    if cls is None:
        raise RuntimeError(f"Sua versão do diffusers não tem {spec['cls']}. Rode: pip install -U diffusers")
    kw = {"torch_dtype": gpu.dtype()}
    if s.get("hf_token"):
        kw["token"] = s["hf_token"]
    try:
        pipe = cls.from_pretrained(model_id, variant=spec["variant"], **kw) if spec.get("variant") \
            else cls.from_pretrained(model_id, **kw)
    except (OSError, ValueError):
        if not spec.get("variant"):
            raise
        pipe = cls.from_pretrained(model_id, **kw)
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)
    return gpu.apply_profile(pipe, profile)


def unload():
    with _lock:
        _state.update(key=None, pipe=None, profile=None)
    gpu.free()


def generate(engine, prompt, negative, aspect, seed, out, log=print, card_text=""):
    """Gera uma imagem e salva em `out`. Retorna o caminho."""
    spec = SPECS.get(engine) or SPECS["cartao"]
    w, h = spec["sizes"].get(aspect, spec["sizes"]["16:9"])
    if spec["cls"] is None:
        return media.text_card(card_text or prompt, out, w, h, seed=seed)
    gpu.require_cuda()
    s = config.settings()
    with _lock:
        profile = gpu.pick_profile(s.get("gpu_profile", "auto"), spec["need_gb"])
        for attempt in range(2):
            key = (engine, s["image_models"].get(engine), profile)
            if _state["key"] != key:
                _state.update(key=None, pipe=None)
                gpu.free()
                log(f"Carregando {engine} (perfil de memória: {profile}). Na 1ª vez o download demora.")
                _state.update(pipe=_load(engine, profile), key=key, profile=profile)
            try:
                return _run(_state["pipe"], spec, prompt, negative, w, h, seed, out)
            except Exception as e:  # noqa: BLE001
                if not gpu.is_oom(e) or attempt == 1 or profile == "economico":
                    raise
                log("Memória de vídeo insuficiente: mudando para o perfil econômico e tentando de novo.")
                profile = "economico"
    return out


def _run(pipe, spec, prompt, negative, w, h, seed, out):
    t = gpu.torch()
    kw = dict(prompt=prompt, width=w, height=h, num_inference_steps=spec["steps"],
              guidance_scale=spec["guidance"], generator=t.Generator("cpu").manual_seed(int(seed)))
    if spec["negative"] and negative:
        kw["negative_prompt"] = negative
    kw.update(spec.get("extra", {}))
    with t.inference_mode():
        img = pipe(**kw).images[0]
    img.save(out, quality=95)
    return out
