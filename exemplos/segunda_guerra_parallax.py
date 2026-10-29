"""Exemplo: documentário de 30 s sobre a Segunda Guerra Mundial com câmera parallax 2.5D.

Rode na raiz do projeto:  python exemplos/segunda_guerra_parallax.py
Usa fotos históricas de domínio público (governo dos EUA, via Wikimedia Commons), narração Edge TTS,
profundidade por IA (Depth Anything, roda até na CPU) e o estilo "Arquivo histórico".
O projeto aparece também no painel (aba Projetos) para você editar e produzir de novo.
"""
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import pipeline  # noqa: E402

ROTEIRO = """Entre 1939 e 1945, a Segunda Guerra Mundial envolveu mais de trinta países e transformou o céu em campo de batalha.

Em dezembro de 1941, o ataque a Pearl Harbor levou os Estados Unidos à guerra.

Em junho de 1944, no Dia D, milhares de soldados desembarcaram na Normandia.

Em setembro de 1945, o Japão se rendeu. A guerra deixou mais de sessenta milhões de mortos."""

# Uma foto por cena, todas em domínio público (créditos no descricao.txt gerado).
FOTOS = [
    ("Boeing B-17F Flying Fortresses in flight with contrails.jpg", "B-17 em formação, USAAF (domínio público)"),
    ("USS Shaw Pearl Harbor-7Dec41.jpg", "Explosão do USS Shaw, Pearl Harbor, U.S. Navy (domínio público)"),
    ("Into the Jaws of Death 23-0455M edit.jpg", "Into the Jaws of Death, Robert F. Sargent, U.S. Coast Guard (domínio público)"),
    ("Surrender of Japan - USS Missouri.jpg", "Rendição do Japão no USS Missouri, Army Signal Corps (domínio público)"),
]
UA = {"User-Agent": "ArchiveStudioAI/2.0 (https://github.com/FelipeGomes070898/ARCHIVE-STUDIO-AI-2)"}


def baixar(nome, destino):
    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + requests.utils.quote(nome) + "?width=1920"
    for tentativa in range(5):
        r = requests.get(url, headers=UA, timeout=60)
        if r.ok and r.headers.get("content-type", "").startswith("image"):
            destino.write_bytes(r.content)
            return destino
        time.sleep(5 * (tentativa + 1))   # o Wikimedia limita pedidos seguidos
    raise RuntimeError(f"Não consegui baixar {nome} (HTTP {r.status_code}).")


def main():
    p = pipeline.Project.create({
        "title": "A Segunda Guerra Mundial em 30 segundos", "script_text": ROTEIRO, "lang": "pt-BR",
        "voice": "pt-BR-AntonioNeural", "style": "arquivo", "aspect": "16:9", "res": 1080,
        "subtitles": True, "camera": "parallax", "image_engine": "cartao", "video_engine": "nenhum"})
    pipeline.stage_plan(p)
    (p.dir / "uploads").mkdir(exist_ok=True)
    for i, (sc, (nome, _)) in enumerate(zip(p.scenes, FOTOS), 1):
        print(f"Baixando foto {i}/{len(FOTOS)}: {nome}")
        sc["image_upload"] = p.rel(baixar(nome, p.dir / "uploads" / f"foto{i}.jpg"))
        time.sleep(2)
    p.save()
    pipeline.start("produce", p.slug, lambda: pipeline.run_produce(p.slug))
    while pipeline.busy():
        time.sleep(1)
    if pipeline.JOB["status"] != "done":
        sys.exit(f"Falhou: {pipeline.JOB['error']}")
    p = pipeline.Project.load(p.slug)
    desc = p.dir / p.data["final"]["descricao"]
    desc.write_text(desc.read_text(encoding="utf-8") + "\nImagens:\n" +
                    "\n".join(f"- {c}" for _, c in FOTOS) + "\n", encoding="utf-8")
    print("\nPronto:", p.dir / p.data["final"]["video"])


if __name__ == "__main__":
    main()
