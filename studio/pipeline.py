"""Linha de produção: roteiro -> narração -> imagens -> vídeo por IA -> cenas -> montagem final.

Cada etapa é uma função `stage_x(project, ctx)` e tudo é cacheado por cena (hash das entradas):
editar uma cena e mandar produzir de novo só refaz o que mudou.
"""
import hashlib
import re
import json
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import audio, config, depth, graphics, media, styles
from .engines import image as image_engine
from .engines import script as script_engine
from .engines import video as video_engine
from .engines import voice as voice_engine

PAD_SECONDS = 0.5        # respiro depois de cada fala
MIN_SCENE = 2.5

FORM_DEFAULTS = {
    "title": "", "topic": "", "script_text": "", "minutes": 3, "lang": "pt-BR", "voice": "", "speed": 1.0,
    "style": styles.DEFAULT_STYLE, "aspect": "16:9", "res": 1080, "subtitles": True, "music": "",
    "music_volume": 0.12, "camera": "kenburns", "pitch": 0, "scene_fade": 0.25, "description": "", "tts_engine": None, "image_engine": None, "video_engine": None,
}


# ------------------------------------------------------------------ projetos
def key_of(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:10]


class Project:
    def __init__(self, slug):
        self.slug = slug
        self.dir = config.PROJECTS / slug
        self.file = self.dir / "project.json"
        self.data = {}
        self._lock = threading.Lock()

    @classmethod
    def create(cls, form):
        config.ensure_dirs()
        base = media.safe_name(form.get("title") or form.get("topic") or "projeto")
        slug, n = base, 2
        while (config.PROJECTS / slug).exists():
            slug, n = f"{base}-{n}", n + 1
        p = cls(slug)
        p.dir.mkdir(parents=True)
        p.data = {"slug": slug, "created": datetime.now().isoformat(timespec="seconds"),
                  "form": normalize_form(form), "title": form.get("title", ""), "scenes": [], "final": {}}
        p.save()
        return p

    @classmethod
    def load(cls, slug):
        p = cls(media.safe_name(slug, ""))
        if not p.slug or not p.file.exists():
            raise FileNotFoundError(f"Projeto '{slug}' não encontrado.")
        p.data = json.loads(p.file.read_text(encoding="utf-8"))
        p.data["form"] = normalize_form(p.data.get("form", {}))
        return p

    def save(self):
        with self._lock:
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.file)

    def path(self, rel):
        return self.dir / rel if rel else None

    def rel(self, path):
        return Path(path).resolve().relative_to(self.dir.resolve()).as_posix()

    def exists(self, rel):
        return bool(rel) and (self.dir / rel).exists()

    @property
    def form(self):
        return self.data["form"]

    @property
    def scenes(self):
        return self.data["scenes"]


def normalize_form(form):
    s = config.settings()
    f = {**FORM_DEFAULTS, **{k: v for k, v in (form or {}).items() if k in FORM_DEFAULTS}}
    f["tts_engine"] = f["tts_engine"] or s["tts_engine"]
    f["image_engine"] = f["image_engine"] or s["image_engine"]
    f["video_engine"] = f["video_engine"] or s["video_engine"]
    if f["lang"] not in voice_engine.LANGS:
        f["lang"] = voice_engine.DEFAULT_LANG
    valid = [v for v, _ in voice_engine.voices(f["tts_engine"], f["lang"])]
    if f["voice"] not in valid:
        f["voice"] = valid[0]
    f["minutes"] = max(0.5, min(60.0, float(f["minutes"] or 3)))
    f["speed"] = max(0.7, min(1.4, float(f["speed"] or 1.0)))
    f["res"] = int(f["res"]) if int(f["res"] or 0) in (480, 720, 1080) else 1080
    f["aspect"] = f["aspect"] if f["aspect"] in ("16:9", "9:16", "1:1") else "16:9"
    f["camera"] = f["camera"] if f["camera"] in ("kenburns", "parallax") else "kenburns"
    if f["style"] not in styles.STYLES:
        f["style"] = styles.DEFAULT_STYLE
    return f


def list_projects():
    config.ensure_dirs()
    out = []
    for f in sorted(config.PROJECTS.glob("*/project.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({"slug": d["slug"], "title": d.get("title") or d["form"].get("topic", ""),
                        "scenes": len(d.get("scenes", [])), "final": bool(d.get("final", {}).get("video")),
                        "created": d.get("created", "")})
        except (OSError, ValueError, KeyError):
            continue
    return out


def new_scene(i, narration, prompt):
    return {"id": i, "narration": narration, "image_prompt": prompt, "use_ai": None, "motion": "",
            "seed": 1000 + i, "image_upload": ""}


def set_scenes(p, items):
    """Recebe a lista editada do painel e preserva o que já foi gerado (cache) de cada cena."""
    old = {s["id"]: s for s in p.scenes}
    next_id = max(list(old) + [-1]) + 1
    out = []
    for it in items:
        sid = it.get("id")
        if sid in old:
            base = dict(old[sid])
        else:
            base = new_scene(next_id, "", "")
            next_id += 1
        for k in ("narration", "image_prompt", "motion", "use_ai", "seed"):
            if k in it:
                base[k] = it[k]
        base["narration"] = str(base.get("narration", "")).strip()
        base["image_prompt"] = str(base.get("image_prompt", "")).strip() or base["narration"]
        if base["narration"]:
            out.append(base)
    p.data["scenes"] = out
    p.save()


# ------------------------------------------------------------------ tarefas em segundo plano
class Cancelled(Exception):
    pass


JOB = {"id": 0, "kind": "", "slug": "", "status": "idle", "stage": "", "progress": 0.0, "log": [],
       "error": "", "started": 0, "finished": 0}
_job_lock = threading.Lock()
_cancel = threading.Event()


def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    JOB["log"] = (JOB["log"] + [line])[-400:]
    print(line, flush=True)


def check_cancel():
    if _cancel.is_set():
        raise Cancelled()


def busy():
    return JOB["status"] == "running"


def start(kind, slug, fn):
    with _job_lock:
        if busy():
            raise RuntimeError("Já existe uma tarefa rodando. Espere terminar ou cancele.")
        _cancel.clear()
        JOB.update(id=JOB["id"] + 1, kind=kind, slug=slug, status="running", stage="", progress=0.0,
                   log=[], error="", started=time.time(), finished=0)

    def runner():
        try:
            fn()
            JOB.update(status="done", progress=1.0, stage="Concluído")
            log("Concluído.")
        except Cancelled:
            JOB.update(status="cancelled", stage="Cancelado")
            log("Cancelado pelo usuário.")
        except Exception as e:  # noqa: BLE001
            JOB.update(status="error", error=str(e))
            log(f"ERRO: {e}")
            traceback.print_exc()
        finally:
            JOB["finished"] = time.time()

    threading.Thread(target=runner, daemon=True).start()
    return JOB["id"]


def cancel():
    _cancel.set()


def _stage(name, lo, hi):
    JOB.update(stage=name, progress=lo)
    log(f"== {name} ==")
    return lambda frac: JOB.update(progress=lo + (hi - lo) * max(0.0, min(1.0, frac)))


# ------------------------------------------------------------------ etapas
def stage_plan(p, force=False):
    if p.scenes and not force:
        return
    f = p.form
    style = styles.get(f["style"])
    if f["script_text"].strip():
        log("Dividindo o seu texto em cenas...")
        items = script_engine.script_from_text(f["script_text"], style, f["lang"], log=log)
        title = f["title"] or f["topic"] or items[0]["narration"][:60]
    else:
        if not f["topic"].strip():
            raise RuntimeError("Informe um tema ou cole o texto do roteiro.")
        title, items = script_engine.write_script(f["topic"], f["minutes"], f["lang"], style,
                                                  title=f["title"], log=log)
    p.data["title"] = title
    p.data["scenes"] = [new_scene(i, it["narration"], it["image_prompt"]) for i, it in enumerate(items)]
    p.save()
    log(f"Roteiro com {len(p.scenes)} cenas: {title}")


def stage_voice(p, prog):
    f = p.form
    for i, sc in enumerate(p.scenes):
        check_cancel()
        k = key_of("voz", f["tts_engine"], f["voice"], f["speed"], f.get("pitch", 0), sc["narration"])
        if sc.get("audio_key") != k or not p.exists(sc.get("audio")):
            (p.dir / "audio").mkdir(exist_ok=True)
            raw = voice_engine.synthesize(f["tts_engine"], sc["narration"], f["voice"], f["speed"],
                                          p.dir / "audio" / f"s{sc['id']:03d}_{k}_bruto", lang=f["lang"],
                                          pitch=f.get("pitch", 0))
            out = p.dir / "audio" / f"s{sc['id']:03d}_{k}.wav"
            words = voice_engine.load_words(raw)
            if words:   # corta exatamente da 1ª à última palavra e alinha os tempos
                a = max(0.0, words[0][0] - 0.08)
                media.cut_audio(raw, out, a, min(media.duration(raw), words[-1][1] + 0.22))
                words = align_words([[round(x - a, 3), round(y - a, 3), wd] for x, y, wd in words], sc["narration"])
            else:
                media.trim_silence(raw, out)
                if media.duration(out) < 0.3:      # fala muito baixa: mantém o original
                    out.unlink(missing_ok=True)
                    out = Path(raw)
            if out != Path(raw):
                Path(raw).unlink(missing_ok=True)
                voice_engine.words_file(raw).unlink(missing_ok=True)
            sc.update(audio=p.rel(out), audio_key=k, speech_seconds=round(media.duration(out), 3), words=words)
            log(f"Narração cena {i + 1}/{len(p.scenes)}: {sc['speech_seconds']:.1f} s")
        pad = float(sc.get("pause_after", PAD_SECONDS))
        sc["duration"] = round(max(MIN_SCENE, sc["speech_seconds"] + pad), 3)
        prog((i + 1) / len(p.scenes))
    p.save()


def _norm(t):
    return re.sub(r"[^\w]", "", t).lower()


def align_words(words, text):
    """O TTS devolve palavras sem pontuação (e às vezes junta duas, como "In 1905");
    recupera a grafia original (vírgulas, pontos, aspas) do roteiro."""
    tokens = text.split()
    j, out = 0, []
    for a, b, wd in words:
        target = _norm(wd)
        hit = None
        for k in range(j, min(j + 4, len(tokens))):
            for m in (1, 2, 3):
                joined = "".join(_norm(t) for t in tokens[k:k + m])
                if target and (joined == target or (m == 1 and joined.startswith(target))):
                    hit = (k, m)
                    break
            if hit:
                break
        if hit is None:
            out.append([a, b, wd])
            continue
        k, m = hit
        out.append([a, b, " ".join(tokens[k:k + m])])
        j = k + m
    return out


def full_prompt(p, sc):
    return f"{sc['image_prompt']}, {styles.get(p.form['style'])['prompt']}"


def _image_for(p, owner, prompt, seed, tag, card_text):
    """Garante a imagem de uma cena ou tomada (enviada pelo usuário ou gerada). Usa cache por assinatura."""
    f = p.form
    if owner.get("image_upload") and p.exists(owner["image_upload"]):
        k = key_of("upload", owner["image_upload"], (p.dir / owner["image_upload"]).stat().st_mtime)
        owner.update(image=owner["image_upload"], image_key=k)
        return
    eng = f["image_engine"]
    model = config.settings()["image_models"].get(eng, "")
    style = styles.get(f["style"])
    full = f"{prompt}, {style['prompt']}"
    k = key_of("img", eng, model, full, f["aspect"], seed, card_text if eng == "cartao" else "")
    if owner.get("image_key") != k or not p.exists(owner.get("image")):
        (p.dir / "imagens").mkdir(exist_ok=True)
        out = p.dir / "imagens" / f"{tag}_{k}.jpg"
        image_engine.generate(eng, full, style["negative"], f["aspect"], seed, out, log=log, card_text=card_text)
        owner.update(image=p.rel(out), image_key=k)
        p.save()


def stage_images(p, prog):
    for i, sc in enumerate(p.scenes):
        check_cancel()
        shots = sc.get("shots") or []
        if shots:
            for j, sh in enumerate(shots):
                if sh.get("kind", "image") == "image":
                    log(f"Imagem cena {i + 1}/{len(p.scenes)}, tomada {j + 1}/{len(shots)}...")
                    _image_for(p, sh, sh.get("image_prompt") or sc["image_prompt"], int(sc["seed"]) * 10 + j,
                               f"s{sc['id']:03d}_{j:02d}", sh.get("card_text") or sc["narration"])
            first = next((sh for sh in shots if sh.get("image")), None)
            if first:
                sc.update(image=first["image"], image_key=first["image_key"])
        else:
            log(f"Imagem cena {i + 1}/{len(p.scenes)}...")
            _image_for(p, sc, sc["image_prompt"], sc["seed"], f"s{sc['id']:03d}", sc["narration"])
        prog((i + 1) / len(p.scenes))
    image_engine.unload()   # libera a VRAM para o modelo de vídeo
    p.save()


def ai_scene_ids(p):
    """Cenas que viram vídeo por IA: as marcadas, senão até `max_ai_clips` distribuídas pelo vídeo."""
    if p.form["video_engine"] in ("nenhum", "", None):
        return set()
    marked = {s["id"] for s in p.scenes if s.get("use_ai") is True}
    if marked:
        return marked
    pool = [s["id"] for s in p.scenes if s.get("use_ai") is not False and not s.get("shots")]
    n = min(len(pool), int(config.settings().get("max_ai_clips", 0)))
    if n <= 0:
        return set()
    step = len(pool) / n
    return {pool[int(i * step)] for i in range(n)}


def stage_ai_video(p, prog):
    f = p.form
    eng = f["video_engine"]
    s = config.settings()
    model = s["maestro_model"] if eng == "maestro" else s["video_models"].get(eng, "")
    wanted = ai_scene_ids(p)
    jobs, by_out = [], {}
    for sc in p.scenes:
        if sc["id"] not in wanted:
            continue
        secs = round(min(sc["duration"], float(s.get("ai_clip_seconds", 5))), 2)
        k = key_of("ai", eng, model, sc.get("image_key"), sc["image_prompt"], secs, f["aspect"], sc["seed"])
        if sc.get("ai_key") == k and p.exists(sc.get("ai_clip")):
            continue
        (p.dir / "ia").mkdir(exist_ok=True)
        out = p.dir / "ia" / f"s{sc['id']:03d}_{k}.mp4"
        jobs.append({"image": str(p.dir / sc["image"]), "prompt": full_prompt(p, sc), "seconds": secs,
                     "aspect": f["aspect"], "seed": sc["seed"], "out": str(out)})
        by_out[str(out)] = (sc, k)
    if not jobs:
        prog(1)
        return
    log(f"{len(jobs)} cena(s) para vídeo por IA com '{eng}'.")
    done = {"n": 0}

    def vlog(msg):
        log(msg)
        if "pronto" in msg or "falhou" in msg:
            done["n"] += 1
            prog(done["n"] / len(jobs))

    try:
        results = video_engine.generate(eng, jobs, log=vlog, cancel=check_cancel)
    finally:
        video_engine.unload()
    for out, err in results.items():
        sc, k = by_out[out]
        if err is None and Path(out).exists():
            sc.update(ai_clip=p.rel(out), ai_key=k, ai_error="")
        else:
            sc.update(ai_clip="", ai_key="", ai_error=err or "sem arquivo")
    p.save()
    prog(1)


def scene_motion(p, sc, i):
    """Movimento da cena: o escolhido nela, senão o do estilo (convertido para parallax se a câmera for 2.5D)."""
    if sc.get("motion"):
        return sc["motion"]
    style = styles.get(p.form["style"])
    m = style["motion"][i % len(style["motion"])]
    return media.TO_PARALLAX.get(m, m) if p.form["camera"] == "parallax" else m


def depth_for(p, owner, tag=None):
    """Mapa de profundidade da imagem de uma cena/tomada (cacheado pela imagem e pelo modelo)."""
    k = key_of("prof", owner.get("image_key"), config.settings().get("depth_model"))
    if owner.get("depth_key") == k and p.exists(owner.get("depth")):
        return p.dir / owner["depth"]
    (p.dir / "profundidade").mkdir(exist_ok=True)
    out = p.dir / "profundidade" / f"{tag or 's%03d' % owner['id']}_{k}.png"
    kind = depth.estimate(p.dir / owner["image"], out, log=log)
    owner.update(depth=p.rel(out), depth_key=k, depth_kind=kind)
    log(f"Profundidade {out.stem} ({'IA' if kind == 'ia' else 'sintética'}).")
    return out


XFADE = 0.4


def shot_times(sc):
    """Divide a cena entre as tomadas pelo peso de cada uma, cortando no início de uma palavra quando possível."""
    shots, total = sc["shots"], sc["duration"]
    weights = [float(sh.get("weight", 1)) for sh in shots]
    cuts, acc = [0.0], 0.0
    starts = [w[0] for w in sc.get("words") or []]
    for wgt in weights[:-1]:
        acc += wgt / sum(weights) * total
        if starts:
            near = min(starts, key=lambda x: abs(x - acc))
            if abs(near - acc) < 0.7 and near - cuts[-1] > 1.5:
                acc = near
        cuts.append(round(acc, 3))
    cuts.append(total)
    return [(cuts[j], cuts[j + 1]) for j in range(len(shots))]


def render_shots(p, sc, i, w, h, out):
    """Renderiza as tomadas da cena e une com dissolução cruzada."""
    times = shot_times(sc)
    parts, durs = [], []
    for j, (sh, (a, b)) in enumerate(zip(sc["shots"], times)):
        check_cancel()
        dur = (b - a) + (XFADE if j < len(times) - 1 else 0)
        part = p.dir / "cenas" / f"t{sc['id']:03d}_{j:02d}.mp4"
        kind = sh.get("kind", "image")
        if kind == "graphic":
            graphics.render(sh["graphic"], part, dur, w, h)
        elif kind == "video":
            media.fit_clip(p.dir / sh["video"], part, dur, w, h)
        else:
            motion = sh.get("motion") or scene_motion(p, sc, i + j)
            img = p.dir / sh["image"]
            if sh.get("fit") == "frame":
                comp = p.dir / "cenas" / f"t{sc['id']:03d}_{j:02d}_quadro.jpg"
                media.frame_composite(img, comp, w, h, trim=bool(sh.get("trim")))
                media.kenburns(comp, part, dur, w, h, motion="zoom_out" if "out" in motion else "zoom_in",
                               strength=0.05)
                comp.unlink(missing_ok=True)
            elif motion in media.PARALLAX_MOTIONS:
                dep = depth_for(p, sh, tag=f"s{sc['id']:03d}_{j:02d}")
                media.parallax(img, dep, part, dur, w, h, motion=motion)
            else:
                media.kenburns(img, part, dur, w, h, motion=motion)
        parts.append(part)
        durs.append(dur)
        sh["t0"], sh["t1"] = a, b
    media.xfade_join(parts, durs, out, overlap=XFADE)
    for part in parts:
        Path(part).unlink(missing_ok=True)
    return out


def scene_fades(p, i):
    """Fade curto entre cenas; o vídeo abre do preto e termina com um fade mais longo."""
    f = float(p.form.get("scene_fade", media.FADE))
    first, last = i == 0, i == len(p.scenes) - 1
    return (max(f, 0.3) if first else f), (1.2 if last else f)


def stage_clips(p, prog):
    f = p.form
    w, h = media.sizes(f["aspect"], f["res"])
    style = styles.get(f["style"])
    wanted = ai_scene_ids(p)
    (p.dir / "cenas").mkdir(exist_ok=True)
    for i, sc in enumerate(p.scenes):
        check_cancel()
        use_ai = sc["id"] in wanted and p.exists(sc.get("ai_clip"))
        shots = sc.get("shots") or []
        motion = scene_motion(p, sc, i)
        dep = depth_for(p, sc) if not use_ai and not shots and motion in media.PARALLAX_MOTIONS else None
        if shots:
            vis_src = ("tomadas", [{k2: v for k2, v in sh.items() if k2 not in ("t0", "t1", "depth", "depth_key",
                                                                               "depth_kind")} for sh in shots],
                       shot_times(sc))
        else:
            vis_src = ("ai", sc.get("ai_key")) if use_ai else ("cam", sc.get("image_key"), motion, sc.get("depth_key"))
        fade_in, fade_out = scene_fades(p, i)
        k = key_of("cena", vis_src, sc.get("audio_key"), sc["duration"], style["fx"], w, h, media.FPS,
                   fade_in, fade_out)
        if sc.get("clip_key") == k and p.exists(sc.get("clip")):
            prog((i + 1) / len(p.scenes))
            continue
        vis = p.dir / "cenas" / f"v{sc['id']:03d}_{k}.mp4"
        if shots:
            render_shots(p, sc, i, w, h, vis)
        elif use_ai:
            media.fit_clip(p.dir / sc["ai_clip"], vis, sc["duration"], w, h)
        elif dep:
            media.parallax(p.dir / sc["image"], dep, vis, sc["duration"], w, h, motion=motion)
        else:
            media.kenburns(p.dir / sc["image"], vis, sc["duration"], w, h, motion=motion)
        out = p.dir / "cenas" / f"s{sc['id']:03d}_{k}.mp4"
        media.scene_clip(vis, p.dir / sc["audio"], out, sc["duration"], style["fx"], fade_in, fade_out)
        vis.unlink(missing_ok=True)
        visual = f"{len(shots)} tomadas" if shots else ("ia" if use_ai else motion)
        sc.update(clip=p.rel(out), clip_key=k, visual=visual)
        log(f"Cena {i + 1}/{len(p.scenes)} montada ({'vídeo IA' if use_ai else visual}).")
        prog((i + 1) / len(p.scenes))
    p.save()


def stage_final(p, prog):
    f = p.form
    w, h = media.sizes(f["aspect"], f["res"])
    t = 0.0
    for sc in p.scenes:
        sc["start"] = round(t, 3)
        t += sc["duration"]
    out_dir = p.dir / "final"
    out_dir.mkdir(exist_ok=True)
    joined = out_dir / "_juncao.mp4"
    media.concat([p.dir / sc["clip"] for sc in p.scenes], joined)
    prog(0.3)
    cues = media.build_word_cues(p.scenes, max_chars=20 if h > w else 42)
    srt = media.write_srt(cues, out_dir / "legendas.srt")
    titles = [(sc["start"] + 0.15, sc["start"] + (sc["duration"] if sc.get("title_full") else min(4.5, sc["duration"]))
               - 0.2, sc["title"]) for sc in p.scenes if sc.get("title")]
    labels = [(sc["start"] + sh["t0"] + 0.2, sc["start"] + sh["t1"] - 0.1, sh["label"])
              for sc in p.scenes for sh in sc.get("shots") or [] if sh.get("label") and "t0" in sh]
    keys = [k for sc in p.scenes for k in sc.get("highlight", [])]
    ass = (media.write_ass(cues, out_dir / "legendas.ass", w, h, titles=titles, labels=labels, highlight=keys)
           if f["subtitles"] or titles else None)
    music, volume = None, float(f["music_volume"])
    if f["music"] == "auto":
        log("Gerando trilha cinematográfica e efeitos sonoros...")
        total = sum(sc["duration"] for sc in p.scenes)
        sections = [(sc["start"], float(sc.get("intensity", 0.5))) for sc in p.scenes]
        sfx = [dict(ev, start=sc["start"] + ev.get("start", 0), dur=ev.get("dur", sc["duration"]))
               for sc in p.scenes for ev in sc.get("sfx", [])]
        music = audio.make_bed(out_dir / "trilha.wav", total, sections, sfx)
    elif f["music"] and (p.dir / f["music"]).exists():
        music = p.dir / f["music"]
    name = media.safe_name(p.data.get("title") or p.slug)
    final = out_dir / f"{name}.mp4"
    check_cancel()
    log("Montagem final (trilha, volume e legendas)...")
    media.finalize(joined, final, music=music, ass=ass, music_volume=volume)
    joined.unlink(missing_ok=True)
    prog(0.8)
    thumb = media.thumbnail(p.dir / p.scenes[0]["image"], p.data.get("title") or p.slug, out_dir / "thumbnail.jpg")
    (out_dir / "roteiro.txt").write_text(
        "\n\n".join(f"[{sc['start']:.1f}s] {sc['narration']}" for sc in p.scenes), encoding="utf-8")
    (out_dir / "descricao.txt").write_text(description(p), encoding="utf-8")
    real = media.duration(final)
    p.data["final"] = {"video": p.rel(final), "srt": p.rel(srt), "thumb": p.rel(thumb),
                       "roteiro": "final/roteiro.txt", "descricao": "final/descricao.txt",
                       "duration": round(real, 2), "size_mb": media.file_size_mb(final),
                       "created": datetime.now().isoformat(timespec="seconds")}
    expected = sum(sc["duration"] for sc in p.scenes)
    if abs(real - expected) > 1.0:
        log(f"Aviso: duração final {real:.1f}s difere da soma das cenas ({expected:.1f}s).")
    p.save()
    log(f"Vídeo final: {final.name} ({real / 60:.1f} min, {p.data['final']['size_mb']} MB)")


def description(p):
    lines = [p.data.get("title", "")]
    if p.form.get("description"):
        lines += ["", p.form["description"].strip()]
    lines += ["", "Capítulos:" if p.form["lang"].startswith("pt") else "Chapters:"]
    titled = [sc for sc in p.scenes if sc.get("title")]
    every = max(1, len(p.scenes) // 8)
    for i, sc in enumerate(titled or p.scenes):
        if titled or i % every == 0:
            m, s = divmod(int(sc.get("start", 0)), 60)
            text = sc.get("title") or sc["narration"][:60].rstrip(" ,.") + "..."
            lines.append(f"{m:02d}:{s:02d} {text}")
    credits = []
    for sc in p.scenes:
        for sh in [sc] + list(sc.get("shots") or []):
            if sh.get("credit") and sh["credit"] not in credits:
                credits.append(sh["credit"])
    if credits:
        lines += ["", "Créditos das imagens:" if p.form["lang"].startswith("pt") else "Image credits:"]
        lines += [f"- {c}" for c in credits]
    ai_images = any(not sc.get("image_upload") and not sc.get("shots") for sc in p.scenes) \
        and p.form["image_engine"] != "cartao"
    if p.form["lang"].startswith("pt"):
        lines += ["", "Narração e imagens geradas com IA." if ai_images else "Narração gerada com IA."]
    else:
        lines += ["", "AI-generated narration and images." if ai_images else "AI-generated narration."]
    if p.form["video_engine"] == "maestro" and any(sc.get("visual") == "ia" for sc in p.scenes):
        lines.append("Parte dos clipes foi gerada com WanGP (https://github.com/deepbeepmeep/Wan2GP).")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ fluxos completos
def run_plan(slug, force=True):
    p = Project.load(slug)
    _stage("Roteiro", 0, 1)
    stage_plan(p, force=force)


def run_produce(slug):
    p = Project.load(slug)
    stage_plan(p)
    if not p.scenes:
        raise RuntimeError("O projeto não tem cenas.")
    stage_voice(p, _stage("Narração", 0.02, 0.15))
    stage_images(p, _stage("Imagens", 0.15, 0.45))
    stage_ai_video(p, _stage("Vídeo por IA", 0.45, 0.75))
    stage_clips(p, _stage("Cenas", 0.75, 0.92))
    stage_final(p, _stage("Montagem final", 0.92, 1.0))


def run_auto(slug):
    p = Project.load(slug)
    _stage("Roteiro", 0, 0.02)
    stage_plan(p)
    run_produce(slug)
