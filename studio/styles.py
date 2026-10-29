"""Biblioteca de estilos. Para criar um estilo novo, copie um bloco e mude os textos.

Campos:
  name     nome mostrado no painel
  desc     descrição curta
  prompt   o que é acrescentado ao prompt de imagem (em inglês, os modelos entendem melhor)
  negative o que evitar
  fx       filtro do ffmpeg aplicado em cada cena ("" = nenhum)
  motion   movimentos de câmera usados em sequência (zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down)
  writer   orientação para o roteirista
"""

STYLES = {
    "cinematico": dict(
        name="Cinematográfico",
        desc="Documentário moderno, luz dramática e cores ricas.",
        prompt="cinematic documentary still, dramatic lighting, rich colors, shallow depth of field, 35mm, highly detailed",
        negative="text, watermark, logo, blurry, deformed, low quality",
        fx="eq=contrast=1.05:saturation=1.08,vignette=PI/6",
        motion=["zoom_in", "pan_right", "zoom_out", "pan_left"],
        writer="Tom envolvente e cinematográfico, frases claras, ritmo de documentário de TV.",
    ),
    "arquivo": dict(
        name="Arquivo histórico",
        desc="Fotos antigas em sépia, granulação e vinheta.",
        prompt="aged archival photograph, sepia toned, film grain, historical, realistic, scanned photo",
        negative="modern objects, color photo, text, watermark, logo, blurry",
        fx="colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131,noise=alls=12:allf=t,vignette=PI/5",
        motion=["zoom_in", "pan_left", "zoom_out", "pan_right"],
        writer="Narrativa histórica sóbria, com datas e contexto. Cenas como fotografias de época.",
    ),
    "preto_branco": dict(
        name="Filme antigo P&B",
        desc="Película preto e branco com alto contraste.",
        prompt="black and white film still, 1930s, high contrast, heavy film grain, vintage cinema",
        negative="color, modern, text, watermark, digital look",
        fx="hue=s=0,eq=contrast=1.2,noise=alls=18:allf=t,vignette=PI/4",
        motion=["zoom_in", "zoom_out", "pan_right", "pan_left"],
        writer="Narração clássica, tom de cinejornal antigo.",
    ),
    "misterio": dict(
        name="Mistério e crime",
        desc="Sombrio, neblina e luz fria (true crime, enigmas).",
        prompt="dark moody atmosphere, fog, cold blue light, mysterious, cinematic, high detail",
        negative="bright, cheerful, text, watermark, cartoon",
        fx="eq=brightness=-0.03:saturation=0.8,colorbalance=bs=0.08:bm=0.05,vignette=PI/4",
        motion=["zoom_in", "pan_left", "zoom_in", "pan_right"],
        writer="Suspense crescente, perguntas abertas, revelações no fim de cada bloco.",
    ),
    "natureza": dict(
        name="Natureza e ciência",
        desc="Paisagens, animais e macro, cores naturais.",
        prompt="nature documentary photography, national geographic style, natural light, ultra detailed, 8k",
        negative="text, watermark, people, cartoon, blurry",
        fx="eq=saturation=1.12",
        motion=["pan_right", "zoom_in", "pan_left", "zoom_out"],
        writer="Didático e contemplativo, curiosidades científicas verificáveis.",
    ),
    "anime": dict(
        name="Animação",
        desc="Ilustração estilo anime/animação 2D.",
        prompt="anime illustration, studio quality, vibrant colors, detailed background, cel shading",
        negative="photo, realistic, text, watermark, deformed",
        fx="",
        motion=["zoom_in", "pan_right", "pan_left", "zoom_out"],
        writer="Linguagem leve e dinâmica, boa para curiosidades e histórias.",
    ),
    "pintura": dict(
        name="Pintura a óleo",
        desc="Quadros clássicos, pinceladas visíveis.",
        prompt="classical oil painting, visible brush strokes, museum masterpiece, dramatic chiaroscuro",
        negative="photo, text, watermark, modern",
        fx="vignette=PI/5",
        motion=["zoom_in", "pan_up", "zoom_out", "pan_down"],
        writer="Narrativa épica e histórica, imagens como pinturas de época.",
    ),
    "futurista": dict(
        name="Tecnologia e futuro",
        desc="Sci-fi, neon e tecnologia.",
        prompt="futuristic sci-fi concept art, neon lights, high tech, volumetric lighting, ultra detailed",
        negative="text, watermark, low quality, blurry",
        fx="eq=contrast=1.08:saturation=1.15",
        motion=["zoom_in", "pan_right", "zoom_out", "pan_left"],
        writer="Explicações claras sobre tecnologia, tom curioso e otimista.",
    ),
}

DEFAULT_STYLE = "cinematico"


def get(key):
    return STYLES.get(key) or STYLES[DEFAULT_STYLE]


def listing():
    return [{"id": k, "name": v["name"], "desc": v["desc"]} for k, v in STYLES.items()]
