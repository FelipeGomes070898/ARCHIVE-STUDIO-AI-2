"""Trilha cinematográfica e efeitos sonoros gerados por síntese (sem direitos autorais, sem bloqueio em redes).

`make_bed(out, total, sections, sfx)` cria um WAV estéreo 48 kHz com:
  - pads de cordas em ré menor (Dm, Bb, F, C), grave sub, pulso de percussão e ostinato que crescem com a tensão;
  - impacto na abertura, "risers" antes das mudanças fortes e um final emocional que desaparece devagar;
  - efeitos: vento, água, ronco de máquinas e zumbido de turbinas, posicionados no tempo.
`sections` = [(inicio_s, intensidade 0..1)], `sfx` = [{"name", "start", "dur", "vol"}].
"""
import wave

import numpy as np

SR = 48000
BPM = 72
CHORDS = [  # (fundamental MIDI, notas do acorde MIDI) — i, VI, III, VII em ré menor
    (38, [50, 53, 57, 62]),   # Dm
    (34, [46, 50, 53, 58]),   # Bb
    (41, [48, 53, 57, 60]),   # F
    (36, [48, 52, 55, 60]),   # C
]


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def _env_curve(total, sections, n):
    """Intensidade suave ao longo do tempo (0..1)."""
    t = np.arange(n) / SR
    pts = sorted(sections) or [(0, 0.5)]
    xs = [p[0] for p in pts] + [total]
    ys = [p[1] for p in pts] + [pts[-1][1]]
    curve = np.interp(t, xs, ys)
    k = int(SR * 1.5)                      # suaviza 1,5 s
    if k > 1 and n > k:
        c = np.cumsum(np.concatenate([[0], curve]))
        curve = (c[k:] - c[:-k]) / k
        curve = np.concatenate([curve, np.full(n - len(curve), curve[-1])])
    return curve.astype(np.float32)


def _tone(freq, n, harmonics=6, detune=0.0025, vibrato=0.0, phase=0.0):
    t = np.arange(n, dtype=np.float32) / SR
    out = np.zeros(n, dtype=np.float32)
    for d in (-detune, 0.0, detune):
        f = freq * (1 + d)
        ph = 2 * np.pi * f * t + phase
        if vibrato:
            ph = ph + vibrato * np.sin(2 * np.pi * 4.8 * t)
        for h in range(1, harmonics + 1):
            out += np.sin(h * ph).astype(np.float32) / (h ** 1.6)
    return out / 3


def _colored_noise(n, lo, hi, seed):
    """Ruído filtrado na frequência (uma FFT só, sem emendas), entre lo e hi Hz."""
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n).astype(np.float32))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec *= ((f >= lo) & (f <= hi)) / np.maximum(np.sqrt(np.maximum(f, 20) / 100), 1)   # inclinação "rosa"
    out = np.fft.irfft(spec, n).astype(np.float32)
    return out / (np.abs(out).max() + 1e-9)


def _adsr(n, attack, release):
    e = np.ones(n, dtype=np.float32)
    a, r = min(n, int(attack * SR)), min(n, int(release * SR))
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def _hit(n, freq=55.0, decay=0.45, noise=0.25, seed=0):
    t = np.arange(n, dtype=np.float32) / SR
    f = freq * (1 + 1.2 * np.exp(-t * 18))                 # queda de afinação (tambor grave)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / decay)
    rng = np.random.default_rng(seed)
    click = rng.standard_normal(n).astype(np.float32) * np.exp(-t / 0.03) * noise
    return (body + click).astype(np.float32)


def _impact(n, seed=1):
    t = np.arange(n, dtype=np.float32) / SR
    boom = np.sin(2 * np.pi * np.cumsum(38 + 60 * np.exp(-t * 6)) / SR) * np.exp(-t / 1.6)
    rumble = _colored_noise(n, 25, 400, seed) * np.exp(-t / 0.9) * 0.6
    return (boom + rumble).astype(np.float32)


def _riser(n, seed=2):
    p = np.linspace(0, 1, n, dtype=np.float32)
    return _colored_noise(n, 300, 6000, seed) * p ** 2.2 * 0.5


def _reverb(x, seconds=2.6, mix=0.3, seed=3):
    """Reverb por convolução com resposta sintética (FFT)."""
    rng = np.random.default_rng(seed)
    n_ir = int(SR * seconds)
    ir = rng.standard_normal(n_ir).astype(np.float32) * np.exp(-np.linspace(0, 7, n_ir)).astype(np.float32)
    ir /= np.sqrt((ir ** 2).sum())
    size = 1 << int(np.ceil(np.log2(len(x) + n_ir)))
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:len(x)].astype(np.float32)
    return (1 - mix) * x + mix * wet


def music(total, sections, seed=7):
    n = int(total * SR)
    inten = _env_curve(total, sections, n)
    beat = 60 / BPM
    chord_len = beat * 8
    left = np.zeros(n, dtype=np.float32)
    right = np.zeros(n, dtype=np.float32)
    # Pads e grave: um acorde a cada 8 tempos, com sobreposição suave.
    k = 0
    t0 = 0.0
    while t0 < total:
        root, notes = CHORDS[k % len(CHORDS)]
        a = int(t0 * SR)
        m = min(n - a, int((chord_len + 1.5) * SR))
        if m <= 0:
            break
        env = _adsr(m, 1.6, 1.8)
        pad_l = sum(_tone(midi(nt), m, vibrato=0.002, phase=i) for i, nt in enumerate(notes)) * env
        pad_r = sum(_tone(midi(nt + 0.03), m, vibrato=0.002, phase=i + 1) for i, nt in enumerate(notes)) * env
        bass = (np.sin(2 * np.pi * midi(root) * np.arange(m) / SR) * 0.9
                + np.sin(2 * np.pi * midi(root - 12) * np.arange(m) / SR) * 0.6).astype(np.float32) * env
        left[a:a + m] += 0.10 * pad_l + 0.22 * bass
        right[a:a + m] += 0.10 * pad_r + 0.22 * bass
        # Ostinato grave (colcheias) quando a tensão sobe.
        for j in range(16):
            ts = t0 + j * beat / 2
            s = int(ts * SR)
            if s >= n:
                break
            lvl = float(np.clip((inten[s] - 0.35) / 0.65, 0, 1))
            if lvl <= 0:
                continue
            ln = min(n - s, int(0.28 * SR))
            note = _tone(midi(root + 12 + (7 if j % 4 == 3 else 0)), ln, harmonics=8) * _adsr(ln, 0.005, 0.18)
            left[s:s + ln] += 0.07 * lvl * note
            right[s:s + ln] += 0.07 * lvl * note
        k += 1
        t0 += chord_len
    # Percussão: tambor grave no 1 e 3 (e mais forte no fim).
    tb = 0.0
    j = 0
    while tb < total:
        s = int(tb * SR)
        lvl = float(np.clip((inten[min(s, n - 1)] - 0.45) / 0.55, 0, 1))
        if lvl > 0 and j % 2 == 0:
            ln = min(n - s, int(1.0 * SR))
            h = _hit(ln, 52 if j % 4 == 0 else 62, seed=j) * (0.55 if j % 4 == 0 else 0.35) * lvl
            left[s:s + ln] += h
            right[s:s + ln] += h
        tb += beat
        j += 1
    # Brilho alto (sinos suaves) nas partes calmas.
    rng = np.random.default_rng(seed)
    pent = [62, 65, 67, 69, 72, 74, 77]
    tb = 2.0
    while tb < total - 3:
        s = int(tb * SR)
        calm = float(np.clip(1 - inten[s] * 1.4, 0, 1))
        if calm > 0.05:
            ln = min(n - s, int(2.5 * SR))
            tt = np.arange(ln) / SR
            bell = (np.sin(2 * np.pi * midi(rng.choice(pent) + 12) * tt) * np.exp(-tt / 0.9)).astype(np.float32)
            pan = rng.uniform(0.2, 0.8)
            left[s:s + ln] += 0.035 * calm * bell * (1 - pan)
            right[s:s + ln] += 0.035 * calm * bell * pan
        tb += beat * rng.choice([3, 4, 6])
    # Dinâmica geral pela intensidade.
    gain = 0.45 + 0.75 * inten
    left *= gain
    right *= gain
    # Impactos e risers.
    for when, kind in _accents(total, sections):
        s = int(when * SR)
        if kind == "impact":
            ln = min(n - s, int(4 * SR))
            x = _impact(ln) * 0.9
        else:
            ln = int(2.2 * SR)
            s = max(0, s - ln)
            ln = min(n - s, ln)
            x = _riser(ln)
        left[s:s + ln] += x
        right[s:s + ln] += x
    left, right = _reverb(left), _reverb(right, seed=4)
    # Fim: desaparece nos últimos 4 s.
    fade = min(n, int(4 * SR))
    left[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    right[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    return np.stack([left, right], axis=1)


def _accents(total, sections):
    out = [(0.0, "impact")]
    for (t, lvl), (t_prev, lvl_prev) in zip(sections[1:], sections[:-1]):
        if lvl - lvl_prev >= 0.15 and t > 3:
            out += [(t, "riser"), (t, "impact")]
    return out


SFX = {
    # nome: (banda baixa, banda alta, modulação Hz, profundidade)
    "wind": (60, 900, 0.12, 0.6),
    "water": (150, 4000, 3.5, 0.25),
    "river": (80, 2500, 0.5, 0.3),
    "rumble": (20, 220, 0.3, 0.4),
}


def sfx_track(total, events, seed=11):
    n = int(total * SR)
    out = np.zeros((n, 2), dtype=np.float32)
    for i, ev in enumerate(events):
        s = int(max(0.0, ev["start"]) * SR)
        ln = min(n - s, int(ev["dur"] * SR))
        if ln <= SR // 10:
            continue
        name = ev["name"]
        t = np.arange(ln, dtype=np.float32) / SR
        if name == "turbine":
            x = sum(np.sin(2 * np.pi * f * t) / k for k, f in enumerate((60, 120, 180, 360), 1)).astype(np.float32)
            x = 0.35 * x + 0.5 * _colored_noise(ln, 40, 500, seed + i)
        elif name == "impact":
            x = _impact(ln, seed + i)
        elif name == "whoosh":
            x = _riser(ln, seed + i)[::-1] * np.linspace(1, 0, ln, dtype=np.float32)
        else:
            lo, hi, rate, depth = SFX.get(name, SFX["wind"])
            x = _colored_noise(ln, lo, hi, seed + i)
            x *= (1 - depth + depth * np.sin(2 * np.pi * rate * t + i)).astype(np.float32)
        x = x * _adsr(ln, min(1.0, ev["dur"] / 4), min(1.2, ev["dur"] / 3)) * float(ev.get("vol", 0.2))
        out[s:s + ln, 0] += x
        out[s:s + ln, 1] += np.roll(x, 240)          # leve abertura estéreo
    return out


def make_bed(out, total, sections, sfx=(), music_level=0.5):
    bed = music(total, sections) * music_level + sfx_track(total, list(sfx))
    peak = np.abs(bed).max() + 1e-9
    bed = bed / peak * 0.89
    write_wav_stereo(bed, out)
    return out


def write_wav_stereo(x, out):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return out
