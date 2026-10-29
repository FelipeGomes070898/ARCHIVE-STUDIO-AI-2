"""Testes sem GPU e sem internet: rode `python -m unittest discover -s tests -v` na raiz do projeto.

Simula só o que depende de serviços externos (IA de texto, voz online, modelo de vídeo).
ffmpeg, câmera Ken Burns, cartões de imagem, legendas, cache e montagem rodam de verdade.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

import numpy as np

TMP = Path(tempfile.mkdtemp(prefix="as_test_"))
os.environ["ARCHIVE_STUDIO_HOME"] = str(TMP)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import config, media, pipeline  # noqa: E402
from studio.engines import script as script_engine  # noqa: E402
from studio.engines import video as video_engine  # noqa: E402
from studio.engines import voice as voice_engine  # noqa: E402

CALLS = {"tts": 0, "ai": 0}


def fake_tts(engine, text, voice, speed, out, lang="pt-BR", pitch=0):
    """Áudio de teste: silêncio inicial, um tom com 0,3 s por palavra e os tempos das palavras (como o Edge TTS)."""
    CALLS["tts"] += 1
    words = text.split()
    secs = 0.2 + 0.3 * len(words) + 0.4
    t = np.linspace(0, secs, int(24000 * secs), endpoint=False)
    out = Path(out).with_suffix(".wav")
    voice_engine.write_wav(0.2 * np.sin(2 * np.pi * 220 * t) * (t > 0.2), out, 24000)
    voice_engine.words_file(out).write_text(
        json.dumps([[0.2 + 0.3 * k, 0.2 + 0.3 * k + 0.25, wd] for k, wd in enumerate(words)]), encoding="utf-8")
    return out


def fake_ai(engine, jobs, log=print, cancel=lambda: None):
    """'Modelo de vídeo' de teste: clipe de 2 s do ffmpeg (força o ajuste de duração)."""
    res = {}
    for j in jobs:
        CALLS["ai"] += 1
        media.run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24", "-t", "2", "-pix_fmt", "yuv420p", j["out"]])
        log("  pronto")
        res[j["out"]] = None
    return res


TEXT = ("O Canal do Panamá mudou o comércio mundial. Antes dele, navios davam a volta na América do Sul.\n\n"
        "A primeira tentativa foi francesa, liderada por Ferdinand de Lesseps. Doenças tropicais mataram milhares.\n\n"
        "Os Estados Unidos assumiram em 1904 e terminaram a obra em 1914, com eclusas gigantes.")


def wait_job(timeout=240):
    t0 = time.time()
    while pipeline.busy():
        if time.time() - t0 > timeout:
            raise TimeoutError("tarefa demorou demais")
        time.sleep(0.2)
    return pipeline.JOB


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from studio import depth
        depth._model_depth = lambda img: depth.synthetic(img)   # sem baixar modelo nos testes
        voice_engine.synthesize = fake_tts
        pipeline.voice_engine.synthesize = fake_tts
        video_engine.generate = fake_ai
        config.update({"image_engine": "cartao", "video_engine": "nenhum", "script_engine": "manual",
                       "max_ai_clips": 2})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    # ---------------------------------------------------------- unidades
    def test_parse_json(self):
        self.assertEqual(script_engine.parse_json('```json\n{"a": [1, 2]}\n```'), {"a": [1, 2]})
        self.assertEqual(script_engine.parse_json('texto antes {"ok": true} depois'), {"ok": True})
        with self.assertRaises(ValueError):
            script_engine.parse_json("nada")

    def test_split_text(self):
        parts = script_engine.split_text(TEXT, max_words=12)
        self.assertGreaterEqual(len(parts), 4)
        self.assertTrue(all(len(p.split()) <= 20 for p in parts))

    def test_frames(self):
        self.assertEqual(video_engine.frames_for(5, 24) % 8, 1)
        self.assertLessEqual(video_engine.frames_for(30, 24, 161), 161)

    def test_sizes(self):
        self.assertEqual(media.sizes("16:9", 1080), (1920, 1080))
        self.assertEqual(media.sizes("9:16", 720), (720, 1280))
        self.assertEqual(media.sizes("1:1", 480), (480, 480))

    def test_subtitles(self):
        scenes = [{"start": 0, "speech_seconds": 4, "duration": 4.5, "narration": "Uma frase curta. Outra frase aqui."},
                  {"start": 4.5, "speech_seconds": 3, "duration": 3.5, "narration": "Segunda cena com texto."}]
        cues = media.build_cues(scenes)
        self.assertAlmostEqual(cues[-1][1], 7.5, places=2)
        srt = media.write_srt(cues, TMP / "t.srt")
        self.assertIn("00:00:04,500 -->", Path(srt).read_text(encoding="utf-8"))
        ass = Path(media.write_ass(cues, TMP / "t.ass", 1920, 1080)).read_text(encoding="utf-8")
        self.assertIn("PlayResY: 1080", ass)
        self.assertIn("0:00:04.50", ass)

    def test_styles_fx_are_valid_ffmpeg(self):
        from studio import styles
        src = TMP / "fx.mp4"
        media.run(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "0.5", "-pix_fmt", "yuv420p", src])
        for key, st in styles.STYLES.items():
            if st["fx"]:
                media.run(["-i", src, "-vf", st["fx"], "-f", "null", "-"])

    def test_kenburns_all_motions(self):
        img = media.text_card("Teste de câmera", TMP / "kb.jpg", 960, 540)
        for m in ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"):
            out = media.kenburns(img, TMP / f"kb_{m}.mp4", 1.0, 640, 360, motion=m)
            self.assertAlmostEqual(media.duration(out), 1.0, delta=0.1)

    def test_parallax_all_motions(self):
        from studio import depth
        img = media.text_card("Parallax", TMP / "px.jpg", 960, 540)
        dmap = TMP / "px_depth.png"
        with unittest.mock.patch.object(depth, "_model_depth", side_effect=RuntimeError("sem modelo")):
            self.assertEqual(depth.estimate(img, dmap, log=lambda m: None), "sintetica")
        for m in media.PARALLAX_MOTIONS:
            out = media.parallax(img, dmap, TMP / f"{m}.mp4", 1.0, 640, 360, motion=m)
            self.assertAlmostEqual(media.duration(out), 1.0, delta=0.1)

    def test_fit_clip_modes(self):
        src = TMP / "src.mp4"
        media.run(["-f", "lavfi", "-i", "testsrc2=size=640x480:rate=24", "-t", "2", "-pix_fmt", "yuv420p", src])
        for secs in (1.5, 3.0, 7.0):   # cortar, câmera lenta, vai-e-volta
            out = media.fit_clip(src, TMP / f"fit_{secs}.mp4", secs, 640, 360)
            self.assertAlmostEqual(media.duration(out), secs, delta=0.1)
            self.assertFalse(media.has_audio(out))

    def test_maestro_tasks(self):
        s = dict(config.settings(), maestro_model="ltx2_22B_distilled", maestro_steps=8)
        jobs = [{"image": str(TMP / "a.jpg"), "prompt": "um trem", "seconds": 5, "aspect": "9:16", "seed": 7,
                 "out": str(TMP / "ia" / "s001_abc.mp4")}]
        t = video_engine.maestro_tasks(jobs, s)[0]
        self.assertEqual(t["model_type"], "ltx2_22B_distilled")
        self.assertEqual(t["image_prompt_type"], "S")
        self.assertEqual(t["resolution"], "720x1280")
        self.assertEqual(t["output_filename"], "s001_abc")
        self.assertEqual(t["num_inference_steps"], 8)
        self.assertEqual(t["video_length"] % 8, 1)

    def test_maestro_bridge_with_fake_wgp(self):
        """Simula um wgp.py que lê a fila e grava os clipes com output_filename (como o WanGP faz)."""
        app = TMP / "fake_maestro"
        app.mkdir(exist_ok=True)
        (app / "wgp.py").write_text(
            "import json,sys,subprocess\n"
            "a=sys.argv; q=json.load(open(a[a.index('--process')+1])); out=a[a.index('--output-dir')+1]\n"
            "for t in q:\n"
            "    print('Task', t['model_type'], flush=True)\n"
            "    subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24',"
            "'-t','1',out+'/'+t['output_filename']+'.mp4'],check=True)\n", encoding="utf-8")
        config.update({"maestro_dir": str(app), "maestro_python": sys.executable})
        img = media.text_card("x", TMP / "m.jpg", 320, 180)
        out = TMP / "mout" / "s002_k.mp4"
        out.parent.mkdir(exist_ok=True)
        res = video_engine._maestro([{"image": str(img), "prompt": "p", "seconds": 1, "aspect": "16:9", "seed": 1,
                                      "out": str(out)}], log=lambda m: None, cancel=lambda: None)
        self.assertIsNone(res[str(out)])
        self.assertTrue(out.exists())
        config.update({"maestro_dir": "", "maestro_python": ""})

    def test_write_script_with_fake_llm(self):
        replies = iter([
            '{"title": "Panamá", "parts": ["origem", "obra"]}',
            json.dumps({"scenes": [{"narration": f"Narração {i}", "image_prompt": f"ship {i}"} for i in range(14)]}),
            json.dumps({"scenes": [{"narration": f"Fim {i}", "image_prompt": f"canal {i}"} for i in range(14)]}),
        ])
        script_engine.ENGINES["fake"] = lambda prompt, s: next(replies)
        config.update({"script_engine": "fake"})
        try:
            from studio import styles
            title, scenes = script_engine.write_script("Canal do Panamá", 3, "pt-BR", styles.get("arquivo"), log=lambda m: None)
        finally:
            config.update({"script_engine": "manual"})
            del script_engine.ENGINES["fake"]
        self.assertEqual(title, "Panamá")
        self.assertEqual(len(scenes), 21)            # 3 min / 8,5 s
        self.assertEqual(scenes[0]["image_prompt"], "ship 0")

    # ---------------------------------------------------------- fluxo completo
    def test_full_production_cache_and_edit(self):
        p = pipeline.Project.create({"title": "Canal do Panamá", "script_text": TEXT, "aspect": "16:9", "res": 480,
                                     "style": "arquivo", "video_engine": "maestro", "subtitles": True,
                                     "camera": "parallax"})
        pipeline.start("auto", p.slug, lambda: pipeline.run_auto(p.slug))
        job = wait_job()
        self.assertEqual(job["status"], "done", job["error"] + "\n" + "\n".join(job["log"][-15:]))
        p = pipeline.Project.load(p.slug)
        final = p.dir / p.data["final"]["video"]
        self.assertTrue(final.exists())
        expected = sum(s["duration"] for s in p.scenes)
        self.assertAlmostEqual(media.duration(final), expected, delta=0.6)
        self.assertTrue(media.has_audio(final))
        self.assertEqual(sum(1 for s in p.scenes if s.get("visual") == "ia"), 2)   # max_ai_clips = 2
        self.assertTrue(all(s["visual"].startswith("parallax") for s in p.scenes if s["visual"] != "ia"))
        self.assertTrue((p.dir / "final" / "thumbnail.jpg").exists())
        self.assertIn("WanGP", (p.dir / "final" / "descricao.txt").read_text(encoding="utf-8"))
        w, h = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                                        "stream=width,height", "-of", "csv=p=0", str(final)],
                                       capture_output=True, text=True).stdout.strip().split(","))
        self.assertEqual((w, h), (854, 480))

        # Produzir de novo sem mudanças: nada de voz/IA refeito.
        tts, ai = CALLS["tts"], CALLS["ai"]
        pipeline.start("produce", p.slug, lambda: pipeline.run_produce(p.slug))
        self.assertEqual(wait_job()["status"], "done")
        self.assertEqual((CALLS["tts"], CALLS["ai"]), (tts, ai))

        # Editar uma cena: só ela refaz a voz.
        items = [{"id": s["id"], "narration": s["narration"], "image_prompt": s["image_prompt"]} for s in p.scenes]
        items[1]["narration"] = "Texto novo para a segunda cena."
        pipeline.set_scenes(p, items)
        pipeline.start("produce", p.slug, lambda: pipeline.run_produce(p.slug))
        self.assertEqual(wait_job()["status"], "done")
        self.assertEqual(CALLS["tts"], tts + 1)

    def test_shots_titles_graphics_music(self):
        """Cena com várias tomadas (foto enquadrada, pan e animação), título, rótulo, destaque e trilha gerada."""
        from studio import graphics
        graphics.GRAPHICS["teste"] = lambda spec, out, secs, w, h: media.kenburns(
            media.text_card("grafico", TMP / "g.jpg", 640, 360), out, secs, w, h)
        p = pipeline.Project.create({"title": "Water", "script_text": "x", "aspect": "9:16", "res": 480,
                                     "lang": "en-US", "music": "auto", "scene_fade": 0.1, "video_engine": "nenhum"})
        img = media.text_card("Hoover Dam", TMP / "wide.jpg", 1200, 700)
        (p.dir / "uploads").mkdir()
        shutil.copy(img, p.dir / "uploads" / "wide.jpg")
        sc = pipeline.new_scene(0, "Forty million people live in one of the driest regions of America today.", "dam")
        sc.update(title="40 MILLION PEOPLE. ONE MASSIVE WATER CHALLENGE.", highlight=["driest"], intensity=0.7,
                  sfx=[{"name": "wind", "vol": 0.2}], pause_after=1.0,
                  shots=[{"image_upload": "uploads/wide.jpg", "fit": "frame", "label": "ARCHIVAL PHOTO"},
                         {"image_upload": "uploads/wide.jpg", "motion": "pan_right", "weight": 1.5},
                         {"kind": "graphic", "graphic": {"type": "teste"}}])
        p.data["scenes"] = [sc]
        p.save()
        pipeline.start("produce", p.slug, lambda: pipeline.run_produce(p.slug))
        job = wait_job()
        self.assertEqual(job["status"], "done", job["error"] + "\n" + "\n".join(job["log"][-10:]))
        p = pipeline.Project.load(p.slug)
        final = p.dir / p.data["final"]["video"]
        sc = p.scenes[0]
        self.assertAlmostEqual(sc["words"][0][0], 0.08, delta=0.02)        # silêncio inicial cortado
        self.assertAlmostEqual(media.duration(final), sc["duration"], delta=0.3)
        ass = (p.dir / "final" / "legendas.ass").read_text(encoding="utf-8")
        self.assertIn("Title", ass)
        self.assertIn("ARCHIVAL PHOTO", ass)
        self.assertIn("driest", ass)
        self.assertTrue((p.dir / "final" / "trilha.wav").exists())
        self.assertEqual([round(sh["t1"] - sh["t0"], 1) > 1 for sh in sc["shots"]], [True] * 3)

    def test_long_title_duplicates_open(self):
        """Títulos longos repetidos geram nomes com sufixo (-2, -3...) que precisam abrir de novo."""
        title = "The Insane 200 Year Journey of the Channel Tunnel Between England and France"
        slugs = [pipeline.Project.create({"title": title, "script_text": "x"}).slug for _ in range(4)]
        self.assertEqual(len(set(slugs)), 4)
        for slug in slugs:
            self.assertLessEqual(len(slug), 50)
            self.assertEqual(pipeline.Project.load(slug).slug, slug)
        with self.assertRaises(FileNotFoundError):
            pipeline.Project.load("../settings")

    def test_server_api(self):
        from studio import server
        c = server.app.test_client()
        self.assertEqual(c.get("/").status_code, 200)
        st = c.get("/api/status").get_json()
        self.assertIn("gpu", st)
        self.assertEqual(st["settings"]["gemini_key"], "")
        opt = c.get("/api/options").get_json()
        self.assertIn("arquivo", [s["id"] for s in opt["styles"]])
        r = c.post("/api/settings", json={"gemini_key": "segredo123", "max_ai_clips": 3, "bogus": 1}).get_json()
        self.assertEqual(r["gemini_key"], "")
        self.assertTrue(r["gemini_key_set"])
        self.assertNotIn("segredo123", json.dumps(c.get("/api/status").get_json()))
        config.update({"gemini_key": ""})
        config.settings()["gemini_key"] = ""
        p = c.post("/api/projects", json={"form": {"script_text": TEXT, "res": 480}, "action": "plan"}).get_json()
        wait_job()
        d = c.get(f"/api/projects/{p['slug']}").get_json()
        self.assertGreaterEqual(len(d["scenes"]), 3)
        d = c.put(f"/api/projects/{p['slug']}", json={"scenes": d["scenes"][:2]}).get_json()
        self.assertEqual(len(d["scenes"]), 2)
        self.assertEqual(c.get(f"/files/{p['slug']}/../settings.json").status_code, 404)
        self.assertEqual(c.get("/api/projects/nao-existe").status_code, 404)
        server.TOKEN["value"] = "abc"
        try:
            self.assertEqual(c.get("/api/status").status_code, 403)
            self.assertEqual(c.get("/api/status?t=abc").status_code, 200)
        finally:
            server.TOKEN["value"] = ""


if __name__ == "__main__":
    unittest.main(verbosity=2)
