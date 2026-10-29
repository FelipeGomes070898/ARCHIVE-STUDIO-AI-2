"""Vídeo por IA (imagem -> vídeo) na sua GPU, grátis.

Motores:
  ltx      LTX-Video (diffusers) — leve e rápido
  wan      Wan 2.2 TI2V 5B (diffusers) — melhor movimento, mais pesado
  maestro  usa o Maestro/WanGP que você já instalou (LTX-2, Wan 2.2 14B, MiniMax H3...) pelo modo
           headless oficial `wgp.py --process`. Nenhum código do Maestro é copiado para cá.
  nenhum   só câmera Ken Burns (CPU)

Cada trabalho é um dict: {image, prompt, seconds, aspect, seed, out}. `generate(engine, jobs)` devolve
{out: None | "mensagem de erro"} e grava os MP4 em job["out"].
"""
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import config, gpu, media

NEGATIVE = "worst quality, inconsistent motion, blurry, jittery, distorted, deformed, text, watermark"

SPECS = {
    "nenhum": dict(label="Nenhum — só movimento de câmera (sem GPU)"),
    "ltx": dict(label="LTX-Video — leve e rápido (8-12 GB)", cls="LTXImageToVideoPipeline", fps=24,
                max_frames=161, steps=30, guidance=3.0, need_gb=20,
                sizes={"16:9": (960, 544), "9:16": (544, 960), "1:1": (640, 640)}),
    "wan": dict(label="Wan 2.2 5B — movimento melhor (12-16 GB)", cls="WanImageToVideoPipeline", fps=24,
                max_frames=121, steps=30, guidance=5.0, need_gb=26,
                sizes={"16:9": (1280, 704), "9:16": (704, 1280), "1:1": (960, 960)}),
    "maestro": dict(label="Maestro / WanGP instalado (LTX-2, Wan 14B, H3...)", fps=24,
                    sizes={"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960)}),
}

_lock = threading.Lock()
_state = {"key": None, "pipe": None}


def labels():
    return {k: v["label"] for k, v in SPECS.items()}


def frames_for(seconds, fps, max_frames=10_000):
    """Quadros no formato 8k+1 (aceito por LTX e Wan)."""
    n = 8 * max(1, round(seconds * fps / 8)) + 1
    return min(n, max_frames)


def unload():
    with _lock:
        _state.update(key=None, pipe=None)
    gpu.free()


def generate(engine, jobs, log=print, cancel=lambda: None):
    if engine in ("nenhum", "", None) or not jobs:
        return {}
    if engine == "maestro":
        return _maestro(jobs, log, cancel)
    return _diffusers(engine, jobs, log, cancel)


# ------------------------------------------------------------------ diffusers (LTX / Wan)
def _load(engine, profile):
    import diffusers  # noqa: PLC0415
    spec, s = SPECS[engine], config.settings()
    model_id = s["video_models"][engine]
    kw = {"torch_dtype": gpu.dtype()}
    if s.get("hf_token"):
        kw["token"] = s["hf_token"]
    if engine == "wan":
        t = gpu.torch()
        vae = diffusers.AutoencoderKLWan.from_pretrained(model_id, subfolder="vae", torch_dtype=t.float32,
                                                         **({"token": kw["token"]} if "token" in kw else {}))
        pipe = diffusers.WanImageToVideoPipeline.from_pretrained(model_id, vae=vae, **kw)
    else:
        pipe = getattr(diffusers, spec["cls"]).from_pretrained(model_id, **kw)
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)
    return gpu.apply_profile(pipe, profile)


def _diffusers(engine, jobs, log, cancel):
    from PIL import Image  # noqa: PLC0415
    gpu.require_cuda()
    spec, s = SPECS[engine], config.settings()
    t = gpu.torch()
    results = {}
    with _lock:
        profile = gpu.pick_profile(s.get("gpu_profile", "auto"), spec["need_gb"])
        for i, job in enumerate(jobs, 1):
            cancel()
            key = (engine, s["video_models"][engine], profile)
            if _state["key"] != key:
                _state.update(key=None, pipe=None)
                gpu.free()
                log(f"Carregando {engine} (perfil: {profile}). Na 1ª vez o download é grande.")
                _state.update(pipe=_load(engine, profile), key=key)
            w, h = spec["sizes"].get(job["aspect"], spec["sizes"]["16:9"])
            nf = frames_for(job["seconds"], spec["fps"], spec["max_frames"])
            log(f"Clipe de IA {i}/{len(jobs)} ({nf} quadros, {w}x{h})...")
            with Image.open(job["image"]) as im:
                img = _cover(im.convert("RGB"), w, h)
            kw = dict(image=img, prompt=job["prompt"], negative_prompt=NEGATIVE, width=w, height=h,
                      num_frames=nf, num_inference_steps=spec["steps"], guidance_scale=spec["guidance"],
                      generator=t.Generator("cpu").manual_seed(int(job["seed"])))
            if engine == "ltx":
                kw["frame_rate"] = spec["fps"]
            started = time.time()
            try:
                with t.inference_mode():
                    frames = _state["pipe"](**kw).frames[0]
                media.save_frames(frames, job["out"], spec["fps"])
                results[job["out"]] = None
                log(f"  pronto em {time.time() - started:.0f} s")
            except Exception as e:  # noqa: BLE001
                if gpu.is_oom(e):
                    gpu.free()
                    if profile != "economico":
                        profile = "economico"
                        log("  Sem memória de vídeo: próximos clipes no perfil econômico.")
                results[job["out"]] = str(e)[:300]
                log(f"  falhou: {str(e)[:200]} (a cena usará movimento de câmera)")
    return results


def _cover(im, w, h):
    from PIL import Image  # noqa: PLC0415
    scale = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


# ------------------------------------------------------------------ ponte Maestro / WanGP
def find_maestro_python(app_dir, configured=""):
    if configured:
        return configured
    app = Path(app_dir)
    for env in ("env-sol", "env-rtx50", "env", ".venv", "venv"):
        for exe in ("bin/python", "Scripts/python.exe"):
            p = app / env / exe
            if p.exists():
                return str(p)
    return sys.executable


def maestro_check():
    s = config.settings()
    d = Path(s.get("maestro_dir") or "")
    if not s.get("maestro_dir") or not (d / "wgp.py").exists():
        return False, ("Pasta do Maestro/WanGP inválida: aponte para a pasta que contém wgp.py "
                       "(no Maestro instalado pelo Pinokio é .../maestro/app).")
    py = find_maestro_python(d, s.get("maestro_python", ""))
    return True, f"OK: {d / 'wgp.py'} com {py}"


def maestro_tasks(jobs, s):
    """Monta a lista de tarefas no formato de configurações do WanGP (`--process arquivo.json`)."""
    w_h = SPECS["maestro"]["sizes"]
    tasks = []
    for job in jobs:
        w, h = w_h.get(job["aspect"], w_h["16:9"])
        task = {"model_type": s["maestro_model"], "prompt": job["prompt"],
                "image_start": str(Path(job["image"]).resolve()), "image_prompt_type": "S",
                "resolution": f"{w}x{h}", "video_length": frames_for(job["seconds"], 24),
                "seed": int(job["seed"]), "output_filename": Path(job["out"]).stem}
        if int(s.get("maestro_steps") or 0) > 0:
            task["num_inference_steps"] = int(s["maestro_steps"])
        tasks.append(task)
    return tasks


def _maestro(jobs, log, cancel):
    s = config.settings()
    ok, msg = maestro_check()
    if not ok:
        raise RuntimeError(msg)
    app = Path(s["maestro_dir"])
    py = find_maestro_python(app, s.get("maestro_python", ""))
    work = Path(jobs[0]["out"]).parent / "maestro_saida"
    work.mkdir(parents=True, exist_ok=True)
    queue = work / "fila.json"
    queue.write_text(json.dumps(maestro_tasks(jobs, s), ensure_ascii=False, indent=1), encoding="utf-8")
    cmd = [py, "wgp.py", "--process", str(queue.resolve()), "--output-dir", str(work.resolve())]
    cmd += shlex.split(s.get("maestro_args") or "", posix=os.name != "nt")
    log(f"Maestro/WanGP: gerando {len(jobs)} clipe(s) com {s['maestro_model']} (o modelo carrega uma vez).")
    proc = subprocess.Popen(cmd, cwd=str(app), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    try:
        for line in proc.stdout:
            line = line.strip()
            if line and any(k in line for k in ("Task", "ERROR", "Error", "saved", "completed", "Queue")):
                log("  [Maestro] " + line[:200])
            cancel()
    except BaseException:
        proc.kill()
        raise
    finally:
        proc.stdout.close()
    code = proc.wait()
    results = {}
    for job in jobs:
        stem = Path(job["out"]).stem
        found = sorted(work.glob(stem + "*.mp4"), key=lambda p: p.stat().st_mtime)
        if found:
            os.replace(found[-1], job["out"])
            results[job["out"]] = None
        else:
            results[job["out"]] = f"Maestro não gerou o clipe (código {code})."
    if code != 0:
        log(f"Aviso: o Maestro terminou com código {code}; cenas sem clipe usarão movimento de câmera.")
    return results
