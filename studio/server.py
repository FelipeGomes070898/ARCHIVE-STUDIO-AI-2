"""Servidor do painel (Flask). Rotas pequenas e diretas; a lógica fica em pipeline.py."""
import argparse
import os
import secrets
import threading
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from . import __version__, config, gpu, media, pipeline, styles
from .engines import image as image_engine
from .engines import script as script_engine
from .engines import video as video_engine
from .engines import voice as voice_engine

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
TOKEN = {"value": ""}   # exigido só quando o servidor é exposto (Colab/túnel/rede)
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


@app.before_request
def _auth():
    if not TOKEN["value"] or request.path == "/" or request.path.startswith("/static"):
        return None
    if request.args.get("t") == TOKEN["value"] or request.headers.get("X-Token") == TOKEN["value"]:
        return None
    return jsonify(error="Acesso negado: abra o link completo impresso no terminal."), 403


@app.errorhandler(Exception)
def _err(e):
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    if code == 500:
        pipeline.log(f"Erro na API: {e}")
    return jsonify(error=getattr(e, "description", None) or str(e)), code


def _project(slug):
    try:
        return pipeline.Project.load(slug)
    except FileNotFoundError as e:
        abort(404, str(e))


def _view(p):
    d = dict(p.data)
    d["ai_ids"] = sorted(pipeline.ai_scene_ids(p)) if p.scenes else []
    return d


# ------------------------------------------------------------------ páginas e estado
@app.get("/")
def index():
    return send_from_directory(config.WEB, "index.html", max_age=0)


@app.get("/api/status")
def status():
    return jsonify(job=pipeline.JOB, version=__version__, gpu=gpu.info(), ffmpeg=media.has_ffmpeg(),
                   settings=config.public_settings(), script_ready=script_engine.available())


@app.get("/api/options")
def options():
    return jsonify(
        styles=styles.listing(),
        langs={k: v["name"] for k, v in voice_engine.LANGS.items()},
        voices={eng: {lang: voice_engine.voices(eng, lang) for lang in voice_engine.LANGS}
                for eng in voice_engine.ENGINES},
        tts=voice_engine.ENGINES, images=image_engine.labels(), videos=video_engine.labels(),
        script={"gemini": "Gemini (grátis com chave)", "local": "LLM local (Ollama / LM Studio)",
                "manual": "Manual (eu colo o texto)"},
        form=pipeline.FORM_DEFAULTS)


@app.get("/api/settings")
def get_settings():
    return jsonify(config.public_settings())


@app.post("/api/settings")
def post_settings():
    config.update(request.get_json(force=True) or {})
    return jsonify(config.public_settings())


@app.post("/api/settings/test")
def test_settings():
    what = (request.get_json(force=True) or {}).get("what")
    if what == "script":
        ok = script_engine.test_connection()
        return jsonify(ok=ok, message="IA de texto respondeu." if ok else "Resposta inesperada.")
    if what == "maestro":
        ok, msg = video_engine.maestro_check()
        return jsonify(ok=ok, message=msg)
    info = gpu.info()
    msg = (f"{info['name']} com {info['vram_gb']} GB" if info["cuda"]
           else "Sem GPU CUDA: use 'Cartão de texto' e 'Nenhum', ou instale o PyTorch com CUDA.")
    return jsonify(ok=info["cuda"], message=msg)


# ------------------------------------------------------------------ tarefas
@app.get("/api/job")
def job():
    return jsonify(pipeline.JOB)


@app.post("/api/cancel")
def cancel():
    pipeline.cancel()
    return jsonify(ok=True)


# ------------------------------------------------------------------ projetos
@app.get("/api/projects")
def projects():
    return jsonify(pipeline.list_projects())


@app.post("/api/projects")
def create_project():
    body = request.get_json(force=True) or {}
    p = pipeline.Project.create(body.get("form") or {})
    action = body.get("action", "plan")
    if action in ("plan", "auto"):
        fn = pipeline.run_auto if action == "auto" else pipeline.run_plan
        pipeline.start(action, p.slug, lambda: fn(p.slug))
    return jsonify(_view(p))


@app.get("/api/projects/<slug>")
def get_project(slug):
    return jsonify(_view(_project(slug)))


@app.put("/api/projects/<slug>")
def update_project(slug):
    if pipeline.busy() and pipeline.JOB["slug"] == slug:
        abort(409, "Espere a tarefa deste projeto terminar para editar.")
    p = _project(slug)
    body = request.get_json(force=True) or {}
    if "form" in body:
        p.data["form"] = pipeline.normalize_form({**p.form, **body["form"]})
    if "title" in body:
        p.data["title"] = str(body["title"])[:200]
    if "scenes" in body:
        pipeline.set_scenes(p, body["scenes"])
    p.save()
    return jsonify(_view(p))


@app.post("/api/projects/<slug>/<action>")
def project_action(slug, action):
    p = _project(slug)
    fns = {"plan": lambda: pipeline.run_plan(p.slug, force=True),
           "produce": lambda: pipeline.run_produce(p.slug),
           "auto": lambda: pipeline.run_auto(p.slug)}
    if action not in fns:
        abort(404, "Ação desconhecida.")
    pipeline.start(action, p.slug, fns[action])
    return jsonify(ok=True, job=pipeline.JOB)


@app.post("/api/projects/<slug>/scenes/<int:sid>/new-image")
def new_image(slug, sid):
    p = _project(slug)
    for sc in p.scenes:
        if sc["id"] == sid:
            sc["seed"] = int(sc.get("seed", 0)) + 1
            sc["image_upload"] = ""
            p.save()
            return jsonify(_view(p))
    abort(404, "Cena não encontrada.")


@app.post("/api/projects/<slug>/scenes/<int:sid>/upload")
def upload_image(slug, sid):
    p = _project(slug)
    f = request.files.get("file")
    ext = Path(f.filename).suffix.lower() if f and f.filename else ""
    if ext not in MEDIA_EXT:
        abort(400, "Envie uma imagem JPG, PNG ou WEBP.")
    for sc in p.scenes:
        if sc["id"] == sid:
            (p.dir / "uploads").mkdir(exist_ok=True)
            dest = p.dir / "uploads" / f"s{sid:03d}_{secrets.token_hex(3)}{ext}"
            f.save(dest)
            sc["image_upload"] = p.rel(dest)
            p.save()
            return jsonify(_view(p))
    abort(404, "Cena não encontrada.")


@app.post("/api/projects/<slug>/music")
def upload_music(slug):
    p = _project(slug)
    f = request.files.get("file")
    ext = Path(f.filename).suffix.lower() if f and f.filename else ""
    if ext not in AUDIO_EXT:
        abort(400, "Envie um áudio MP3, WAV, M4A, OGG ou FLAC.")
    dest = p.dir / f"musica{ext}"
    f.save(dest)
    p.data["form"]["music"] = dest.name
    p.save()
    return jsonify(_view(p))


@app.get("/files/<slug>/<path:rel>")
def files(slug, rel):
    p = _project(slug)
    target = (p.dir / rel).resolve()
    if p.dir.resolve() not in target.parents or not target.is_file():
        abort(404, "Arquivo não encontrado.")
    return send_file(target, as_attachment=request.args.get("download") == "1", conditional=True)


# ------------------------------------------------------------------ inicialização
def main(argv=None):
    ap = argparse.ArgumentParser(description="ARCHIVE STUDIO AI")
    ap.add_argument("--host", default=os.environ.get("AS_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("AS_PORT", 8765)))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--token", default=os.environ.get("AS_TOKEN", ""),
                    help="Exige este token na URL (automático quando --host não é 127.0.0.1)")
    a = ap.parse_args(argv)
    config.ensure_dirs()
    if a.token or a.host not in ("127.0.0.1", "localhost"):
        TOKEN["value"] = a.token or secrets.token_urlsafe(12)
    if not media.has_ffmpeg():
        print("AVISO: ffmpeg/ffprobe não encontrados no PATH. Instale antes de produzir (veja o README).")
    url = f"http://127.0.0.1:{a.port}/" + (f"?t={TOKEN['value']}" if TOKEN["value"] else "")
    print(f"\nARCHIVE STUDIO AI {__version__}\nProjetos em: {config.PROJECTS}\nAbra: {url}\n", flush=True)
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=a.host, port=a.port, threaded=True, use_reloader=False)
