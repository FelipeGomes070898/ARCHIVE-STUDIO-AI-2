"""Exemplo completo: "How America Supplies Water to 40 Million People in the Desert"
Documentário vertical (9:16, 1080x1920) em inglês para Facebook Reels, ~3 min 55 s.

Rode na raiz do projeto:  python exemplos/hoover_water_reels.py
- Fotos reais: Carol M. Highsmith Archive e fotos de 1934 da Library of Congress (domínio público / sem
  restrições conhecidas) e uma foto CC BY 4.0 do Wikimedia Commons (crédito na descrição).
- Mapas, diagrama e gráfico: animações desenhadas pelo estúdio (studio/graphics.py), rotuladas como tal.
- Voz: Edge TTS (en-US-ChristopherNeural). Trilha e efeitos: sintetizados (studio/audio.py), sem direitos autorais.
Para reaproveitar imagens já baixadas, defina AS_ASSET_CACHE com a pasta que contém aNN.jpg.
"""
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import pipeline  # noqa: E402

HS = "Carol M. Highsmith Archive, Library of Congress (public domain)"
LOC34 = "Library of Congress, Prints & Photographs Division, 1934 (no known restrictions)"
IIIF = "https://tile.loc.gov/image-services/iiif/service:pnp:highsm:"
ST = "https://tile.loc.gov/storage-services/service/pnp/"

# id: (url, crédito)
ASSETS = {
    "a00": (IIIF + "13600:13689", HS), "a01": (IIIF + "16200:16293", HS), "a02": (IIIF + "17900:17916", HS),
    "a03": (IIIF + "13600:13668", HS), "a04": (ST + "highsm/55600/55629v.jpg", HS),
    "a05": (IIIF + "24000:24076", HS), "a06": (IIIF + "25300:25349", HS), "a07": (IIIF + "17800:17844", HS),
    "a08": (IIIF + "35000:35021", HS), "a09": (IIIF + "33500:33536", HS), "a10": (IIIF + "34700:34743", HS),
    "a11": (ST + "highsm/54400/54461v.jpg", HS), "a12": (ST + "highsm/54400/54494v.jpg", HS),
    "a13": (IIIF + "20900:20975", HS), "a14": (IIIF + "23700:23775", HS), "a15": (IIIF + "21000:21030", HS),
    "a17": (IIIF + "21000:21006", HS), "a18": (IIIF + "21000:21026", HS),
    "a19": (ST + "cph/3b30000/3b36000/3b36000/3b36019r.jpg", LOC34),
    "a20": (ST + "cph/3b30000/3b36000/3b36000/3b36020r.jpg", LOC34),
    "a21": (ST + "cph/3b30000/3b36000/3b36000/3b36023r.jpg", LOC34),
    "a22": (ST + "cph/3b30000/3b36000/3b36000/3b36027r.jpg", LOC34),
    "a24": (ST + "cph/3b30000/3b36000/3b36000/3b36016r.jpg", LOC34),
    "a25": (ST + "cph/3c10000/3c14000/3c14300/3c14360v.jpg", LOC34),
    "a26": (ST + "cph/3b30000/3b36000/3b36000/3b36025v.jpg", LOC34),
    "a27": (ST + "cph/3c10000/3c14000/3c14300/3c14357v.jpg", LOC34),
    "a28": (ST + "cph/3b30000/3b36000/3b36000/3b36028r.jpg", LOC34),
    "a31": (IIIF + "12000:12084", HS), "a34": (ST + "highsm/54400/54401v.jpg", HS),
    "a35": (IIIF + "24000:24058", HS), "a36": (ST + "highsm/55800/55876v.jpg", HS),
    "a37": (ST + "highsm/55800/55877v.jpg", HS), "a39": (ST + "highsm/54400/54402v.jpg", HS),
    "a40": (IIIF + "04500:04588", HS), "a41": (ST + "highsm/54400/54424v.jpg", HS),
    "a42": (IIIF + "16200:16290", HS), "a43": (IIIF + "16300:16335", HS), "a44": (IIIF + "12100:12141", HS),
    "a45": (ST + "highsm/54400/54413v.jpg", HS), "a46": (ST + "highsm/49700/49748v.jpg", HS),
    "a51": ("commons:Hoover Dam Main Turbine Hall.jpg",
            "\"Hoover Dam Main Turbine Hall\" by Alexander Mason, CC BY 4.0 "
            "(https://creativecommons.org/licenses/by/4.0/), via Wikimedia Commons"),
}
ARCHIVAL = "ARCHIVAL PHOTO · 1934 · LIBRARY OF CONGRESS"
NOTE = "Simplified animated map · Data: Natural Earth"


def img(aid, motion="", fit="cover", weight=1.0, label="", trim=False):
    return {"asset": aid, "motion": motion, "fit": fit, "weight": weight, "label": label, "trim": trim}


def arch(aid, weight=1.0, motion="zoom_in"):
    return img(aid, motion, fit="frame", weight=weight, label=ARCHIVAL, trim=True)


def graphic(spec, weight=1.0):
    return {"kind": "graphic", "graphic": spec, "weight": weight}


RIVER_MAP = {
    "type": "map", "bbox": [-119.5, -104.5, 31.2, 41.5], "focus": [-112, 36], "zoom": 1.06, "note": NOTE,
    "rivers": [{"name": "Colorado", "from": [-105.83, 40.47], "to": [-114.75, 31.85], "t0": 0.05, "t1": 0.75}],
    "lakes": [{"name": "Lake Powell", "t": 0.35}, {"name": "Lake Mead", "t": 0.5}],
    "points": [{"name": "Rocky Mountains", "lon": -105.83, "lat": 40.4, "t": 0.05, "dx": -1},
               {"name": "Lake Powell", "lon": -111.2, "lat": 37.2, "t": 0.38},
               {"name": "Hoover Dam", "lon": -114.737, "lat": 36.016, "t": 0.52, "kind": "dam", "dx": -1},
               {"name": "Gulf of California", "lon": -114.7, "lat": 31.6, "t": 0.78}],
}
FLOOD_MAP = {
    "type": "map", "bbox": [-117.0, -113.7, 31.9, 34.0], "focus": [-115.4, 33.0], "zoom": 1.06,
    "note": "Animated map reconstruction, simplified · Data: Natural Earth",
    "rivers": [{"name": "Colorado", "from": [-114.57, 34.85], "to": [-114.75, 31.85], "t0": 0.0, "t1": 0.12}],
    "routes": [{"coords": [[-114.80, 32.62], [-115.10, 32.55], [-115.45, 32.66], [-115.56, 32.98],
                           [-115.75, 33.22]], "t0": 0.15, "t1": 0.45, "color": [90, 170, 255], "width": 6}],
    "fill": {"lake": "Salton Sea", "t0": 0.4, "t1": 0.95},
    "points": [{"name": "1905 breach", "lon": -114.80, "lat": 32.62, "t": 0.12, "kind": "dam", "dx": -1, "dy": 1.2},
               {"name": "Yuma", "lon": -114.62, "lat": 32.69, "t": 0.05, "dx": 1, "dy": -1.0},
               {"name": "Salton Sea", "lon": -115.65, "lat": 33.45, "t": 0.85, "dx": 1}],
    "labels": [{"text": "SALTON SINK", "lon": -116.15, "lat": 33.05, "t": 0.3, "scale": 0.8}],
}
AQUEDUCT_MAP = {
    "type": "map", "bbox": [-119.2, -110.4, 31.4, 37.0], "focus": [-114.8, 33.8], "zoom": 1.05,
    "note": "Approximate routes, simplified · Data: Natural Earth",
    "rivers": [{"name": "Colorado", "from": [-114.0, 36.1], "to": [-114.75, 31.85], "t0": 0.0, "t1": 0.15}],
    "routes": [
        {"coords": [[-114.15, 34.30], [-114.6, 34.25], [-115.13, 34.13], [-115.48, 33.86], [-115.75, 33.75],
                    [-116.30, 33.80], [-116.95, 33.80], [-117.45, 33.84]], "t0": 0.15, "t1": 0.45,
         "color": [255, 200, 40]},
        {"coords": [[-114.13, 34.30], [-113.70, 33.90], [-113.10, 33.75], [-112.50, 33.75], [-112.27, 33.85],
                    [-111.90, 33.62], [-111.65, 33.40], [-111.55, 33.00], [-111.20, 32.50], [-110.98, 32.20]],
         "t0": 0.38, "t1": 0.72, "color": [255, 140, 60]},
        {"coords": [[-114.46, 32.88], [-114.62, 32.73], [-114.85, 32.71], [-115.10, 32.68], [-115.40, 32.67]],
         "t0": 0.68, "t1": 0.85, "color": [120, 230, 140]},
    ],
    "points": [{"name": "Las Vegas", "lon": -115.14, "lat": 36.17, "t": 0.08, "dx": -1},
               {"name": "Lake Havasu", "lon": -114.15, "lat": 34.45, "t": 0.14},
               {"name": "Los Angeles", "lon": -118.24, "lat": 34.05, "t": 0.45, "dy": -1.1},
               {"name": "Phoenix", "lon": -112.07, "lat": 33.45, "t": 0.6, "dy": 1.1},
               {"name": "Tucson", "lon": -110.97, "lat": 32.22, "t": 0.72, "dx": -1},
               {"name": "Imperial Valley", "lon": -115.55, "lat": 32.85, "t": 0.85, "dx": -1, "dy": 1.1}],
    "labels": [{"text": "COLORADO RIVER AQUEDUCT", "lon": -116.3, "lat": 34.25, "t": 0.4, "color": (255, 210, 80),
                "scale": 0.75},
               {"text": "CENTRAL ARIZONA PROJECT", "lon": -112.7, "lat": 34.25, "t": 0.66, "color": (255, 160, 80),
                "scale": 0.75},
               {"text": "ALL-AMERICAN CANAL", "lon": -115.0, "lat": 32.35, "t": 0.82, "color": (140, 235, 160),
                "scale": 0.75}],
}
LEVELS = {"type": "levels", "high": {"value": 1225, "label": "1983: about 1,225 ft"},
          "low": {"value": 1041, "label": "2022: about 1,041 ft"}, "ring_label": "MINERAL 'BATHTUB RING'",
          "note": "Lake Mead surface elevation (approx.). Source: U.S. Bureau of Reclamation"}

SCENES = [
    dict(title="40 MILLION PEOPLE. ONE MASSIVE WATER CHALLENGE.", intensity=0.6,
         highlight=["million", "driest", "water", "engineering"],
         sfx=[{"name": "wind", "start": 0, "dur": 7, "vol": 0.25}],
         narration="Forty million people live in one of the driest regions of America. Cities like Las Vegas, "
                   "Phoenix, Los Angeles, and San Diego depend on water to survive and grow. But where does all "
                   "that water come from? The answer involves one of the greatest engineering achievements in "
                   "human history.",
         shots=[img("a13", "pan_right", weight=1.4), img("a00", "parallax_in", weight=0.9),
                img("a04", "zoom_in", fit="frame", weight=0.7), img("a05", "pan_left", weight=0.7),
                img("a06", "pan_right", weight=0.8), img("a01", "parallax_in", weight=1.1),
                img("a07", "parallax_in", weight=1.7)]),
    dict(title="THE COLORADO RIVER: A LIFELINE IN THE DESERT", intensity=0.35,
         highlight=["Colorado", "floods", "drought"],
         sfx=[{"name": "river", "start": 0, "dur": 23, "vol": 0.18}],
         narration="The story begins with the Colorado River, a lifeline stretching hundreds of miles across the "
                   "American West. For generations, its water has supported cities, farms, and entire "
                   "communities. But the river has always been unpredictable. Floods could destroy everything "
                   "in their path, while drought could leave entire regions desperate for water.",
         shots=[img("a08", "parallax_right"), graphic(RIVER_MAP, 1.9), img("a11", "zoom_in", fit="frame"),
                img("a09", "parallax_left"), img("a14", "pan_right")]),
    dict(title="1905: WHEN THE RIVER ESCAPED CONTROL", intensity=0.55, highlight=["breach", "Salton"],
         sfx=[{"name": "water", "start": 0, "dur": 9, "vol": 0.2}, {"name": "rumble", "start": 0, "dur": 9,
                                                                    "vol": 0.15}],
         narration="In 1905, a catastrophic breach in an irrigation system allowed the Colorado River to pour into "
                   "a desert basin in Southern California. The uncontrolled flow continued for nearly two years "
                   "before engineers finally stopped it. The disaster helped create the Salton Sea, a striking "
                   "reminder that controlling a powerful river can be far more difficult than it seems.",
         shots=[graphic(FLOOD_MAP, 2.3), img("a15", "parallax_in"), img("a17", "pan_left"),
                img("a18", "parallax_out")]),
    dict(title="HOOVER DAM — AN ENGINEERING GIANT", intensity=0.62, highlight=["Hoover", "tunnels", "heat"],
         sfx=[{"name": "rumble", "start": 0, "dur": 24, "vol": 0.16}, {"name": "wind", "start": 8, "dur": 10,
                                                                      "vol": 0.12}],
         narration="In the 1930s, engineers took on an extraordinary challenge: building Hoover Dam. First, they "
                   "had to divert the river through enormous tunnels blasted into the canyon walls. Thousands of "
                   "workers faced extreme heat, dangerous heights, and hazardous conditions. Every stage demanded "
                   "precision, courage, and engineering on an unprecedented scale.",
         shots=[arch("a19", 1.2), arch("a20"), arch("a21"), arch("a22"), arch("a24"), arch("a25", 1.2)]),
    dict(title="ENGINEERING THE IMPOSSIBLE", intensity=0.5, highlight=["heat", "cracks", "chilled", "pipes"],
         sfx=[{"name": "rumble", "start": 0, "dur": 8, "vol": 0.12}, {"name": "water", "start": 12, "dur": 12,
                                                                     "vol": 0.12}],
         narration="But the biggest challenge was hiding inside the concrete itself. A structure this massive "
                   "generates enormous heat as the concrete hardens. Without a cooling system, the process could "
                   "take many decades, increasing the risk of cracks. Engineers built the dam in sections and "
                   "circulated chilled water through an extensive network of pipes, dramatically accelerating "
                   "the cooling process.",
         shots=[arch("a26"), arch("a27"), graphic({"type": "cooling"}, 2.6), arch("a28")]),
    dict(title="WATER STORAGE. HYDROPOWER. SURVIVAL.", intensity=0.5,
         highlight=["Lake", "Mead", "electricity", "storing"],
         sfx=[{"name": "turbine", "start": 8, "dur": 9, "vol": 0.16}],
         narration="The dam created Lake Mead, one of America's largest reservoirs by capacity, and helped "
                   "transform the region's energy supply. Its hydroelectric generators convert the power of "
                   "moving water into electricity. But the reservoir serves another crucial purpose: storing "
                   "water for communities that depend on a river flowing through an increasingly dry landscape.",
         shots=[img("a42", "parallax_in"), img("a44", "parallax_out"), img("a51", "zoom_in", weight=1.2),
                img("a34", "zoom_in", fit="frame"), img("a31", "parallax_in", weight=1.3)]),
    dict(title="HUNDREDS OF MILES OF WATER INFRASTRUCTURE", intensity=0.6,
         highlight=["Aqueducts", "uphill", "energy", "farms"],
         sfx=[{"name": "water", "start": 0, "dur": 6, "vol": 0.18}],
         narration="Hoover Dam is only part of the story. Aqueducts, pipelines, tunnels, and pumping stations move "
                   "water across enormous distances. Some systems must push water uphill, consuming significant "
                   "amounts of energy along the way. This network supports homes, businesses, and farms, "
                   "including agricultural regions that supply food far beyond the desert itself.",
         shots=[img("a35", "parallax_in"), graphic(AQUEDUCT_MAP, 2.4), img("a36", "zoom_in", fit="frame"),
                img("a46", "zoom_in", fit="frame"), img("a37", "zoom_out", fit="frame")]),
    dict(title="THE WATER CRISIS IS REAL", intensity=0.8, highlight=["weakness", "drought", "pressure"],
         sfx=[{"name": "wind", "start": 0, "dur": 23, "vol": 0.18}],
         narration="But this incredible system has a serious weakness: it cannot manufacture water. The Colorado "
                   "River Compact of 1922 allocated water based on estimates that proved overly optimistic for "
                   "the river's long-term supply. Prolonged drought, rising temperatures, and heavy demand have "
                   "put enormous pressure on the Colorado River Basin and its reservoirs.",
         shots=[img("a40", "parallax_in"), img("a41", "zoom_in", fit="frame"), img("a10", "pan_left"),
                graphic(LEVELS, 2.0), img("a39", "zoom_out", fit="frame")]),
    dict(title="THE FUTURE OF THE DESERT DEPENDS ON WATER.", intensity=0.95,
         highlight=["every", "drop", "infinite", "faster"],
         sfx=[{"name": "water", "start": 0, "dur": 6, "vol": 0.2}],
         narration="Today, millions of people depend on decisions made about every drop of this river. "
                   "Conservation, smarter water management, and cooperation between states will help determine "
                   "what happens next. Hoover Dam proves that humans can reshape a landscape on an extraordinary "
                   "scale. But it also teaches us a critical lesson: engineering can move water across a desert, "
                   "but it cannot make a limited resource infinite. What happens when a city grows faster than "
                   "its water supply?",
         shots=[img("a46", "zoom_out", fit="frame", weight=1.1), img("a12", "zoom_in", fit="frame"),
                img("a43", "parallax_in"), img("a45", "zoom_in", fit="frame"), img("a02", "parallax_in", weight=1.3),
                img("a03", "parallax_out", weight=1.2)]),
    dict(title="WOULD YOU LIVE HERE? COMMENT BELOW.", title_full=True, intensity=0.6, pause_after=2.6, highlight=["Comment", "follow"],
         narration="Would you live in a city that depends on water traveling hundreds of miles? Comment below and "
                   "follow for more incredible engineering stories.",
         shots=[img("a44", "parallax_in", weight=1.0)]),
]

DESCRIPTION = (
    "How does the desert Southwest supply water to 40 million people? From the Colorado River and the 1905 flood "
    "that created the Salton Sea, to the construction of Hoover Dam, Lake Mead, the aqueducts, and today's water "
    "crisis.\n\nWould you live in a city that depends on water traveling hundreds of miles? Comment below and "
    "follow for more incredible engineering stories.\n\n#HooverDam #ColoradoRiver #LakeMead #Engineering "
    "#Documentary #WaterCrisis #LasVegas #Desert #History #Reels\n\n"
    "Maps and diagrams are simplified animated illustrations. Lake Mead elevations are approximate "
    "(source: U.S. Bureau of Reclamation). Music and sound effects were synthesized for this video.")

UA = {"User-Agent": "ArchiveStudioAI/2.0 (https://github.com/FelipeGomes070898/ARCHIVE-STUDIO-AI-2)"}


def fetch(aid, dest):
    cache = os.environ.get("AS_ASSET_CACHE")
    if cache and (Path(cache) / f"{aid}.jpg").exists():
        dest.write_bytes((Path(cache) / f"{aid}.jpg").read_bytes())
        return dest
    url = ASSETS[aid][0]
    if url.startswith("commons:"):
        url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + requests.utils.quote(url[8:]) + "?width=1920"
    elif "image-services/iiif" in url:
        url += "/full/!2400,2400/0/default.jpg"
    for attempt in range(5):
        r = requests.get(url, headers=UA, timeout=120)
        if r.ok and r.headers.get("content-type", "").startswith("image"):
            dest.write_bytes(r.content)
            return dest
        time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"Não consegui baixar {aid}: HTTP {r.status_code}")


def main():
    p = pipeline.Project.create({
        "title": "How America Supplies Water to 40 Million People in the Desert", "script_text": "-",
        "lang": "en-US", "voice": "en-US-ChristopherNeural", "speed": 0.94, "pitch": -4, "style": "cinematico",
        "aspect": "9:16", "res": 1080, "subtitles": True, "music": "auto", "music_volume": 0.30,
        "scene_fade": 0.15, "image_engine": "cartao", "video_engine": "nenhum", "camera": "parallax",
        "description": DESCRIPTION})
    up = p.dir / "uploads"
    up.mkdir(exist_ok=True)
    scenes = []
    for i, sc in enumerate(SCENES):
        s = pipeline.new_scene(i, sc["narration"], sc["title"])
        s.update({k: v for k, v in sc.items() if k not in ("narration", "shots")})
        shots = []
        for sh in sc["shots"]:
            sh = dict(sh)
            if "asset" in sh:
                aid = sh.pop("asset")
                dest = up / f"{aid}.jpg"
                if not dest.exists():
                    print("Baixando", aid)
                    fetch(aid, dest)
                sh.update(image_upload=p.rel(dest), credit=ASSETS[aid][1])
            shots.append(sh)
        s["shots"] = shots
        scenes.append(s)
    p.data["scenes"] = scenes
    p.data["title"] = "How America Supplies Water to 40 Million People in the Desert"
    p.save()
    pipeline.start("produce", p.slug, lambda: pipeline.run_produce(p.slug))
    while pipeline.busy():
        time.sleep(2)
    if pipeline.JOB["status"] != "done":
        sys.exit(f"Falhou: {pipeline.JOB['error']}")
    p = pipeline.Project.load(p.slug)
    print("\nPronto:", p.dir / p.data["final"]["video"], f"({p.data['final']['duration']:.1f} s)")


if __name__ == "__main__":
    main()
