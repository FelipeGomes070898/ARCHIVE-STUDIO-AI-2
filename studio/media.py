"""Tudo que mexe com arquivos de mídia: ffmpeg, câmera Ken Burns, ajuste de clipes, legendas e montagem."""
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 30
FADE = 0.25
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
        "-maxrate", "14M", "-bufsize", "28M"]
AAC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


# ------------------------------------------------------------------ ffmpeg básico
def ffmpeg_bin():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg não encontrado. Instale-o e coloque no PATH (veja o README).")
    return exe


def has_ffmpeg():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run(args, cwd=None):
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y"] + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-6:])
        raise RuntimeError(f"ffmpeg falhou: {tail}")


def duration(path):
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe não encontrado (vem junto com o ffmpeg).")
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError as e:
        raise RuntimeError(f"Não consegui ler a duração de {Path(path).name}") from e


def has_audio(path):
    exe = shutil.which("ffprobe")
    r = subprocess.run([exe, "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return bool(r.stdout.strip())


def trim_silence(src, out, threshold="-45dB", keep=0.08):
    """Remove o silêncio do começo e do fim da fala (deixa `keep` s de respiro)."""
    cut = f"silenceremove=start_periods=1:start_threshold={threshold}:start_silence={keep}"
    run(["-i", src, "-af", f"{cut},areverse,{cut},areverse", "-ar", "48000", "-ac", "1", out])
    return out


class FrameWriter:
    """Recebe quadros RGB (numpy HxWx3 uint8) e grava um MP4 H.264."""

    def __init__(self, out, w, h, fps=FPS):
        self.proc = subprocess.Popen(
            [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-an", *X264, str(out)],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.w, self.h = w, h

    def write(self, frame):
        self.proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        self.proc.stderr.close()
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg falhou ao gravar quadros: {err[-400:]}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            self.proc.kill()
            self.proc.wait()
            self.proc.stderr.close()


def save_frames(frames, out, fps):
    """Grava uma lista de quadros (PIL ou numpy 0-1 / 0-255) como MP4."""
    arr = [np.asarray(f) for f in frames]
    if not arr:
        raise RuntimeError("O modelo de vídeo não devolveu quadros.")
    if arr[0].dtype != np.uint8:
        arr = [np.clip(a * 255.0, 0, 255).astype(np.uint8) for a in arr]
    h, w = arr[0].shape[:2]
    with FrameWriter(out, w, h, fps) as wr:
        for a in arr:
            wr.write(a[..., :3])
    return out


# ------------------------------------------------------------------ imagens
def load_rgb(path):
    """Lê imagem como RGB numpy (funciona com acentos no caminho, inclusive no Windows)."""
    with Image.open(path) as im:
        return np.array(im.convert("RGB"))


def _font(size, bold=True):
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf"] if bold
             else ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    lines, line = [], ""
    for word in text.split():
        test = (line + " " + word).strip()
        if draw.textlength(test, font=font) <= max_w or not line:
            line = test
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def text_card(text, out, w, h, seed=0, title=""):
    """Imagem simples com degradê e texto (gerador sem GPU, útil para rascunhos)."""
    rng = np.random.default_rng(seed)
    c1, c2 = rng.integers(10, 90, 3), rng.integers(60, 160, 3)
    y = np.linspace(0, 1, h)[:, None, None]
    grad = (c1 * (1 - y) + c2 * y).astype(np.uint8)
    img = Image.fromarray(np.repeat(grad, w, axis=1))
    d = ImageDraw.Draw(img)
    f = _font(max(18, h // 18))
    lines = _wrap(d, text[:220], f, w * 0.8)[:5]
    lh = f.size * 1.25 if hasattr(f, "size") else 30
    y0 = h / 2 - lh * len(lines) / 2
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f)
        d.text(((w - tw) / 2, y0 + i * lh), ln, font=f, fill=(245, 240, 230))
    if title:
        d.text((w * 0.05, h * 0.05), title[:60], font=_font(max(14, h // 32), False), fill=(220, 220, 220))
    img.save(out, quality=95)
    return out


def thumbnail(image_path, title, out, w=1280, h=720):
    """Thumbnail 1280x720 com o título desenhado."""
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        scale = max(w / im.width, h / im.height)
        im = im.resize((math.ceil(im.width * scale), math.ceil(im.height * scale)), Image.LANCZOS)
        left, top = (im.width - w) // 2, (im.height - h) // 2
        im = im.crop((left, top, left + w, top + h))
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle((0, int(h * 0.55), w, h), fill=(0, 0, 0, 150))
    im = Image.alpha_composite(im.convert("RGBA"), shade).convert("RGB")
    d = ImageDraw.Draw(im)
    f = _font(72)
    lines = _wrap(d, title.upper(), f, w * 0.9)[:3]
    y = h - 40 - len(lines) * 84
    for ln in lines:
        d.text((40, y), ln, font=f, fill=(255, 220, 60), stroke_width=4, stroke_fill=(0, 0, 0))
        y += 84
    im.save(out, quality=90)
    return out


# ------------------------------------------------------------------ câmera Ken Burns (CPU)
def _ease(p):
    return 0.5 - 0.5 * math.cos(math.pi * p)


def kenburns(image_path, out, seconds, w, h, motion="zoom_in", fps=FPS, strength=0.12):
    """Movimento de câmera suave sobre uma imagem, com interpolação bicúbica (sem tremor)."""
    import cv2  # noqa: PLC0415 (só carrega quando precisa)
    src = load_rgb(image_path)
    ih, iw = src.shape[:2]
    aspect = w / h
    cw, ch = (ih * aspect, ih) if iw / ih > aspect else (iw, iw / aspect)
    cx, cy = iw / 2, ih / 2
    n = max(1, round(seconds * fps))
    with FrameWriter(out, w, h, fps) as wr:
        for i in range(n):
            p = _ease(i / (n - 1)) if n > 1 else 0.0
            if motion == "zoom_out":
                z, ox, oy = 1 + strength * (1 - p), 0, 0
            elif motion in ("pan_left", "pan_right", "pan_up", "pan_down"):
                z = 1 + strength * 0.5
                horiz = motion in ("pan_left", "pan_right")
                room = ((iw - cw / z) if horiz else (ih - ch / z)) / 2          # quanto a imagem permite andar
                half = min(room, (cw if horiz else ch) * 0.03 * seconds)       # ~6% do quadro por segundo
                sign = -1 if motion in ("pan_left", "pan_up") else 1
                off = sign * (p - 0.5) * 2 * half
                ox, oy = (off, 0) if horiz else (0, off)
            else:  # zoom_in
                z, ox, oy = 1 + strength * p, 0, 0
            ww, wh = cw / z, ch / z
            x0, y0 = cx + ox - ww / 2, cy + oy - wh / 2
            s = w / ww
            m = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
            frame = cv2.warpAffine(src, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            wr.write(frame)
    return out


# ------------------------------------------------------------------ parallax 2.5D (CPU)
PARALLAX_MOTIONS = ("parallax_in", "parallax_out", "parallax_left", "parallax_right")
TO_PARALLAX = {"zoom_in": "parallax_in", "zoom_out": "parallax_out", "pan_left": "parallax_left",
               "pan_right": "parallax_right", "pan_up": "parallax_in", "pan_down": "parallax_out"}


def _cover_array(arr, w, h, interp):
    import cv2  # noqa: PLC0415
    ih, iw = arr.shape[:2]
    aspect = w / h
    cw, ch = (round(ih * aspect), ih) if iw / ih > aspect else (iw, round(iw / aspect))
    x0, y0 = (iw - cw) // 2, (ih - ch) // 2
    return cv2.resize(arr[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=interp)


def parallax(image_path, depth_path, out, seconds, w, h, motion="parallax_in", fps=FPS, strength=1.0):
    """Câmera 2.5D: cada pixel se move conforme a profundidade (perto mexe mais que longe)."""
    import cv2  # noqa: PLC0415
    margin = 1.2
    bw, bh = round(w * margin), round(h * margin)
    src = _cover_array(load_rgb(image_path), bw, bh, cv2.INTER_AREA)
    with Image.open(depth_path) as im:
        dep = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    dep = _cover_array(dep, bw, bh, cv2.INTER_LINEAR)
    # Dilata o que está perto (evita "halo" do fundo grudado no contorno) e suaviza para não rasgar.
    k = max(3, (bw // 160) | 1)
    dep = cv2.dilate(dep, np.ones((k, k), np.uint8))
    dep = cv2.GaussianBlur(dep, (0, 0), bw / 200)
    focus = float(np.median(dep))
    rel = dep - focus
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ux, uy = xx - w / 2, yy - h / 2
    cx, cy = bw / 2, bh / 2
    n = max(1, round(seconds * fps))
    direction = -1 if motion == "parallax_left" else 1
    with FrameWriter(out, w, h, fps) as wr:
        for i in range(n):
            p = _ease(i / (n - 1)) if n > 1 else 0.0
            if motion in ("parallax_left", "parallax_right"):
                zf = 1.05
                cam = direction * (p - 0.5) * w * 0.05 * strength
                bx0, by0 = cx + ux / zf + cam, cy + uy / zf
                d = cv2.remap(rel, bx0, by0, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                bx, by = bx0 + cam * 1.3 * d, by0
            else:
                q = 1 - p if motion == "parallax_out" else p
                zf = 1 + 0.05 * q * strength
                bx0, by0 = cx + ux / zf, cy + uy / zf
                d = cv2.remap(rel, bx0, by0, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                extra = 1 + 0.10 * q * strength * d
                bx, by = cx + ux / (zf * extra), cy + uy / (zf * extra) - h * 0.012 * q * strength * d
            frame = cv2.remap(src, bx.astype(np.float32), by.astype(np.float32), cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REFLECT)
            wr.write(frame)
    return out


# ------------------------------------------------------------------ clipes
def fit_clip(src, out, seconds, w, h, fps=FPS):
    """Ajusta um clipe de IA à cena: recorta na proporção, sem áudio, com a duração exata.
    Curto demais -> câmera lenta (até 1,6x) ou vai-e-volta."""
    d = duration(src)
    base = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    if d >= seconds - 0.04:
        vf = f"{base},fps={fps}"
        run(["-i", src, "-an", "-vf", vf, "-t", f"{seconds:.3f}", *X264, out])
    elif seconds / d <= 1.6:
        vf = f"setpts={seconds / d:.4f}*PTS,{base},fps={fps}"
        run(["-i", src, "-an", "-vf", vf, "-t", f"{seconds:.3f}", *X264, out])
    else:
        fc = (f"[0:v]{base},fps={fps},split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0,"
              f"loop=loop=-1:size=32767[v]")
        run(["-i", src, "-an", "-filter_complex", fc, "-map", "[v]", "-t", f"{seconds:.3f}", *X264, out])
    return out


def scene_clip(visual, audio, out, seconds, fx="", fade_in=FADE, fade_out=FADE):
    """Junta visual + narração da cena, aplica o filtro do estilo e fades (0 = corte seco)."""
    chain = [fx]
    if fade_in > 0:
        chain.append(f"fade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        chain.append(f"fade=t=out:st={max(0.0, seconds - fade_out):.3f}:d={fade_out}")
    chain = [x for x in chain + ["format=yuv420p"] if x]
    args = ["-i", visual]
    if audio:
        args += ["-i", audio]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    fc = f"[0:v]{','.join(chain)}[v];[1:a]aresample=48000,apad,atrim=0:{seconds:.3f}[a]"
    run(args + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{seconds:.3f}",
                "-r", str(FPS), *X264, *AAC, out])
    return out


def cut_audio(src, out, start, end):
    """Recorta a fala entre `start` e `end` (s) e grava WAV mono 48 kHz."""
    run(["-ss", f"{max(0.0, start):.3f}", "-to", f"{end:.3f}", "-i", src, "-ar", "48000", "-ac", "1", out])
    return Path(out)


def trim_borders(im, max_frac=0.2, tol=14):
    """Remove molduras lisas (brancas/pretas) de fotos de arquivo e negativos escaneados."""
    g = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = g.shape

    def score(line):
        if line.size == 0:
            return 0.0, 128.0
        med = float(np.median(line))
        return float(np.mean(np.abs(line - med) < tol * 2)), med

    def is_border(lines):
        """A linha é moldura se for lisa (clara/escura) ou se for transição curta seguida de linha lisa."""
        f, med = score(lines[0])
        if f > 0.9 and (med > 170 or med < 90):
            return True
        if f > 0.4 and (med > 150 or med < 110):
            return any(score(x)[0] > 0.9 and (score(x)[1] > 170 or score(x)[1] < 90) for x in lines[1:4])
        return False

    top, bot, left, right = 0, h, 0, w
    changed = True
    while changed:                          # alterna os lados: molduras pretas e brancas em camadas
        changed = False
        cx0, cx1 = left + (right - left) // 6, right - (right - left) // 6     # ignora os cantos
        cy0, cy1 = top + (bot - top) // 6, bot - (bot - top) // 6
        if top < h * max_frac and is_border([g[top + k, cx0:cx1] for k in range(4)]):
            top, changed = top + 1, True
        if h - bot < h * max_frac and is_border([g[bot - 1 - k, cx0:cx1] for k in range(4)]):
            bot, changed = bot - 1, True
        if left < w * max_frac and is_border([g[cy0:cy1, left + k] for k in range(4)]):
            left, changed = left + 1, True
        if w - right < w * max_frac and is_border([g[cy0:cy1, right - 1 - k] for k in range(4)]):
            right, changed = right - 1, True
    m = round(min(w, h) * 0.012)          # tira também o resto da borda irregular
    box = (min(left + m, w - 2), min(top + m, h - 2), max(right - m, left + m + 2), max(bot - m, top + m + 2))
    return im.crop(box)


def frame_composite(image_path, out, w, h, width_frac=0.96, center_y=0.46, trim=False, max_h=0.5):
    """Foto inteira sobre o próprio fundo desfocado (bom para fotos horizontais em vídeo vertical)."""
    from PIL import ImageEnhance, ImageFilter  # noqa: PLC0415
    with Image.open(image_path) as im:
        im = im.convert("RGB")
    if trim:
        im = trim_borders(im)
    scale = max(w / im.width, h / im.height)
    bg = im.resize((math.ceil(im.width * scale), math.ceil(im.height * scale)), Image.LANCZOS)
    left, top = (bg.width - w) // 2, (bg.height - h) // 2
    bg = bg.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(w / 30))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    fw = round(w * width_frac)
    fh = round(im.height * fw / im.width)
    if fh > h * max_h:
        fh = round(h * max_h)
        fw = round(im.width * fh / im.height)
    fg = im.resize((fw, fh), Image.LANCZOS)
    bg.paste(fg, ((w - fw) // 2, round(h * center_y - fh / 2)))
    bg.save(out, quality=95)
    return out


def xfade_join(clips, durations, out, overlap=0.4, fps=FPS):
    """Une clipes com dissolução cruzada. `durations` = duração de cada clipe (já com a sobreposição)."""
    if len(clips) == 1:
        os.replace(clips[0], out)
        return out
    args, chain, last, t = [], [], "[0:v]", 0.0
    for c in clips:
        args += ["-i", c]
    for i in range(1, len(clips)):
        t += durations[i - 1] - overlap
        label = f"[x{i}]" if i < len(clips) - 1 else "[v]"
        chain.append(f"{last}[{i}:v]xfade=transition=fade:duration={overlap}:offset={t:.3f}{label}")
        last = label
    run(args + ["-filter_complex", ";".join(chain) + ";[v]format=yuv420p,fps=" + str(fps) + "[o]",
                "-map", "[o]", "-an", *X264, out])
    return out


def concat(clips, out):
    lst = Path(out).with_suffix(".txt")
    lines = []
    for c in clips:
        p = Path(c).resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{p}'")
    lst.write_text("\n".join(lines), encoding="utf-8")
    run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    lst.unlink(missing_ok=True)
    return out


def finalize(video, out, music=None, ass=None, music_volume=0.12):
    """Trilha (abaixa sob a fala), normalização de volume e legendas queimadas (opcional)."""
    out = Path(out)
    args = ["-i", Path(video).resolve()]
    if music:
        args += ["-stream_loop", "-1", "-i", Path(music).resolve()]
        afc = (f"[0:a]asplit=2[voz][sc];[1:a]volume={music_volume},aresample=48000[m];"
               f"[m][sc]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=500[md];"
               f"[voz][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]")
    else:
        afc = "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    cwd = None
    if ass:
        # O filtro de legendas sofre com caminhos do Windows; rodamos na pasta do arquivo.
        cwd = str(Path(ass).parent)
        fc = f"[0:v]subtitles={Path(ass).name}[v];{afc}"
        vargs = ["-map", "[v]", *X264]
    else:
        fc = afc
        vargs = ["-map", "0:v", "-c:v", "copy"]
    total = duration(video)
    run(args + ["-filter_complex", fc, *vargs, "-map", "[a]", *AAC, "-t", f"{total:.3f}",
                "-movflags", "+faststart", out.resolve()], cwd=cwd)
    return out


# ------------------------------------------------------------------ legendas
def _chunks(text, max_chars=42):
    words, out, cur = text.split(), [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        ends_sentence = re.search(r"[.!?;:]$", wd) and len(test) <= max_chars + 10
        if len(test) > max_chars and cur and not ends_sentence:
            out.append(cur)
            cur = wd
        else:
            cur = test
        if re.search(r"[.!?;:]$", cur) and len(cur) > max_chars * 0.5:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def build_cues(scenes):
    """[(inicio, fim, texto)] distribuindo cada narração pelo tempo da sua fala."""
    cues = []
    for s in scenes:
        start, speak = s.get("start", 0.0), s.get("speech_seconds") or s.get("duration", 0)
        parts = _chunks(s.get("narration", ""))
        total = sum(len(p) for p in parts) or 1
        t = start
        for p in parts:
            dt = speak * len(p) / total
            cues.append((t, t + dt, p))
            t += dt
    return cues


def _ts(t, sep=","):
    t = max(0.0, t)
    hh, rem = divmod(t, 3600)
    mm, ss = divmod(rem, 60)
    if sep == ".":  # ASS: h:mm:ss.cc
        return f"{int(hh)}:{int(mm):02d}:{ss:05.2f}"
    return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}{sep}{int(round((ss % 1) * 1000)) % 1000:03d}"


def write_srt(cues, out):
    rows = [f"{i}\n{_ts(a)} --> {_ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(cues, 1)]
    Path(out).write_text("\n".join(rows), encoding="utf-8")
    return out


def build_word_cues(scenes, max_chars=42):
    """Legendas a partir do tempo de cada palavra (Edge TTS). Volta ao modo proporcional sem palavras."""
    cues = []
    for s in scenes:
        words = s.get("words") or []
        if not words:
            cues += build_cues([s])
            continue
        start, group = s.get("start", 0.0), []
        for k, (a, b, wd) in enumerate(words):
            group.append((a, b, wd))
            text = " ".join(x[2] for x in group)
            nxt = words[k + 1][2] if k + 1 < len(words) else ""
            proper = wd[:1].isupper() and nxt[:1].isupper() and len(text + " " + nxt) <= max_chars + 10
            ends = re.search(r"[.!?;:,]$", wd) or not nxt or (len(text + " " + nxt) > max_chars and not proper)
            if ends:
                cues.append((start + group[0][0], start + group[-1][1], text))
                group = []
    # Sem buracos curtos entre legendas (evita piscar).
    out = []
    for i, (a, b, t) in enumerate(cues):
        if i + 1 < len(cues) and 0 < cues[i + 1][0] - b < 0.35:
            b = cues[i + 1][0]
        out.append((a, b, t))
    return out


YELLOW = "&H0028D7FF&"
WHITE = "&H00FFFFFF&"


def _highlight(text, words):
    """Pinta de amarelo números e palavras-chave."""
    keys = {re.sub(r"[^\w]", "", k).lower() for k in words or []}
    out = []
    for tok in text.split(" "):
        bare = re.sub(r"[^\w]", "", tok).lower()
        if bare and (bare in keys or re.search(r"\d", tok)):
            out.append("{\\c" + YELLOW + "}" + tok + "{\\c" + WHITE + "}")
        else:
            out.append(tok)
    return " ".join(out)


def write_ass(cues, out, w, h, titles=(), labels=(), highlight=()):
    """ASS próprio com tamanhos em pixels do vídeo real.
    cues = [(ini, fim, texto)], titles = [(ini, fim, texto)], labels = [(ini, fim, texto)]."""
    vertical = h > w
    base = min(w, h)
    size = round(base * (0.072 if vertical else 0.052))
    margin_v = round(h * (0.30 if vertical else 0.07))
    tsize, lsize = round(base * 0.074), round(base * 0.03)
    side = round(w * (0.08 if vertical else 0.08))
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,DejaVu Sans,{size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(2, size // 11)},2,2,{side},{side},{margin_v},1\n"
        f"Style: Title,DejaVu Sans,{tsize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
        f"-1,0,0,0,100,100,1,0,1,{max(3, tsize // 12)},3,8,{side},{side},{round(h * 0.13)},1\n"
        f"Style: Label,DejaVu Sans,{lsize},&H00E6E6E6,&H00FFFFFF,&H00000000,&H78000000,"
        f"0,0,0,0,100,100,1,0,3,6,0,7,{round(w * 0.05)},{side},{round(h * 0.075)},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    for a, b, t in cues:
        txt = _highlight(t.replace("\n", " "), highlight)
        ev.append(f"Dialogue: 1,{_ts(a, '.')},{_ts(b, '.')},Default,,0,0,0,,"
                  "{\\fad(60,40)\\fscx94\\fscy94\\t(0,120,\\fscx100\\fscy100)}" + txt)
    for a, b, t in titles:
        lines = [x.strip() for x in re.split(r"(?<=[.!?])\s+", t.strip()) if x.strip()]
        if len(lines) > 1:
            txt = "{\\c" + YELLOW + "}" + lines[0] + "{\\c" + WHITE + "}\\N" + "\\N".join(lines[1:])
        else:
            txt = _highlight(lines[0] if lines else t, highlight)
        ev.append(f"Dialogue: 2,{_ts(a, '.')},{_ts(b, '.')},Title,,0,0,0,,"
                  "{\\fad(300,350)\\fscx86\\fscy86\\t(0,350,\\fscx100\\fscy100)}" + txt)
    for a, b, t in labels:
        ev.append(f"Dialogue: 0,{_ts(a, '.')},{_ts(b, '.')},Label,,0,0,0,,{{\\fad(200,200)}}{t}")
    Path(out).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")
    return out


def sizes(aspect, res):
    """Resolução de saída (pares, múltiplos de 2)."""
    res = int(res)
    if aspect == "9:16":
        return res, round(res * 16 / 9 / 2) * 2
    if aspect == "1:1":
        return res, res
    return round(res * 16 / 9 / 2) * 2, res


def safe_name(text, fallback="projeto"):
    import unicodedata  # noqa: PLC0415
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()[:50]
    return t or fallback


def file_size_mb(path):
    return round(os.path.getsize(path) / 1024 ** 2, 1)
