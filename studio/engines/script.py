"""Roteiro: transforma um tema (ou um texto seu) em cenas {narration, image_prompt}.

Motores:
  gemini  API do Google Gemini (plano gratuito; chave em aistudio.google.com/apikey)
  local   qualquer LLM local com API compatível OpenAI: Ollama, LM Studio, llama.cpp (100% grátis e offline)
  manual  você cola o texto; o sistema divide em cenas (sem IA de texto)
"""
import json
import re
import time

import requests

from .. import config

SYSTEM = ("Você é roteirista de documentários para YouTube. Responda SOMENTE com JSON válido, "
          "sem comentários e sem markdown.")
WORDS_PER_SCENE = 22      # ~8-9 s de fala por cena
SECONDS_PER_SCENE = 8.5
BATCH = 14                # cenas por pedido ao modelo


# ------------------------------------------------------------------ chamadas ao modelo
def _gemini(prompt, s):
    try:
        from google import genai  # noqa: PLC0415
        from google.genai import types  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError("Pacote google-genai não instalado: pip install google-genai") from e
    if not s.get("gemini_key"):
        raise RuntimeError("Falta a chave do Gemini (Configurações). É gratuita em aistudio.google.com/apikey")
    client = genai.Client(api_key=s["gemini_key"])
    models = [s["gemini_model"]] + [m for m in s.get("gemini_fallbacks", []) if m != s["gemini_model"]]
    last = None
    for model in models:
        for attempt in range(3):
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.8,
                                                       response_mime_type="application/json"))
                if r.text:
                    return r.text
                last = RuntimeError("resposta vazia")
            except Exception as e:  # noqa: BLE001 (o SDK lança vários tipos)
                last = e
                msg = str(e)
                if "PerDay" in msg or "404" in msg or "NOT_FOUND" in msg:
                    break                      # cota diária/modelo inexistente: tenta o próximo modelo
                if "429" in msg or "503" in msg or "UNAVAILABLE" in msg:
                    time.sleep(8 * (attempt + 1))
                    continue
                if "API_KEY" in msg or "401" in msg or "403" in msg:
                    raise RuntimeError("Chave do Gemini recusada. Confira em Configurações.") from e
                break
    raise RuntimeError(f"Gemini não respondeu: {last}")


def _local(prompt, s):
    url = s["local_llm_url"].rstrip("/") + "/chat/completions"
    body = {"model": s["local_llm_model"], "temperature": 0.8,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    try:
        r = requests.post(url, json=body, timeout=600)
    except requests.RequestException as e:
        raise RuntimeError(f"Não consegui falar com o LLM local em {s['local_llm_url']}. "
                           "Abra o Ollama/LM Studio e confira o endereço.") from e
    if r.status_code != 200:
        raise RuntimeError(f"LLM local respondeu {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


ENGINES = {"gemini": _gemini, "local": _local}


def available(s=None):
    s = s or config.settings()
    e = s.get("script_engine")
    return e == "local" or (e == "gemini" and bool(s.get("gemini_key")))


def ask_json(prompt, s=None):
    s = s or config.settings()
    fn = ENGINES.get(s.get("script_engine"))
    if not fn:
        raise RuntimeError("Motor de roteiro 'manual' não gera texto: cole o seu roteiro no campo Texto.")
    last = None
    for _ in range(2):
        try:
            return parse_json(fn(prompt, s))
        except ValueError as e:
            last = e
    raise RuntimeError(f"O modelo não devolveu JSON válido: {last}")


def parse_json(text):
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        raise ValueError("sem JSON na resposta")
    i = min(starts)
    j = max(t.rfind("}"), t.rfind("]"))
    return json.loads(t[i:j + 1])


def test_connection(s=None):
    out = ask_json('Responda {"ok": true}', s)
    return bool(out.get("ok")) if isinstance(out, dict) else False


# ------------------------------------------------------------------ roteiro a partir de um tema
def write_script(topic, minutes, lang, style, title="", log=print):
    n = max(3, round(minutes * 60 / SECONDS_PER_SCENE))
    parts = max(1, -(-n // BATCH))
    log(f"Planejando {n} cenas em {parts} parte(s)...")
    outline = ask_json(
        f"Tema do documentário: {topic}\nTítulo sugerido: {title or '(crie um)'}\n"
        f"Idioma da narração: {lang}\nDuração: {minutes} minutos.\nEstilo: {style['writer']}\n"
        f'Crie um título forte e divida o documentário em exatamente {parts} partes em ordem. '
        'Formato: {"title": "...", "parts": ["resumo da parte 1", "..."]}')
    title = title or outline.get("title") or topic
    part_list = list(outline.get("parts") or [])[:parts]
    while len(part_list) < parts:
        part_list.append(f"continuação do tema ({len(part_list) + 1})")
    scenes = []
    for i, part in enumerate(part_list):
        want = min(BATCH, n - len(scenes))
        if want <= 0:
            break
        prev = " ".join(sc["narration"] for sc in scenes[-2:])
        log(f"Escrevendo parte {i + 1}/{parts}: {part[:60]}")
        data = ask_json(
            f"Documentário: {title}\nTema: {topic}\nIdioma da narração: {lang}\nEstilo: {style['writer']}\n"
            f"Parte {i + 1} de {parts}: {part}\n"
            f"Narração anterior (para continuidade): {prev or '(início do vídeo — comece com um gancho forte)'}\n"
            f"{'Esta é a última parte: termine com uma conclusão.' if i == parts - 1 else ''}\n"
            f"Escreva exatamente {want} cenas. Cada cena tem narração de {WORDS_PER_SCENE - 6} a "
            f"{WORDS_PER_SCENE + 6} palavras em {lang}, e um image_prompt em INGLÊS descrevendo uma "
            "imagem concreta (lugar, época, pessoas, objetos, luz), sem texto escrito na imagem. "
            'Formato: {"scenes": [{"narration": "...", "image_prompt": "..."}]}')
        for sc in _scene_list(data)[:want]:
            scenes.append(sc)
    if not scenes:
        raise RuntimeError("O modelo não devolveu cenas. Tente de novo ou use o motor 'manual'.")
    return title, scenes


def _scene_list(data):
    items = data.get("scenes", []) if isinstance(data, dict) else data
    out = []
    for it in items or []:
        if isinstance(it, dict) and str(it.get("narration", "")).strip():
            out.append({"narration": str(it["narration"]).strip(),
                        "image_prompt": str(it.get("image_prompt") or it["narration"]).strip()})
    return out


# ------------------------------------------------------------------ roteiro a partir do seu texto
def split_text(text, max_words=30):
    """Divide um texto em cenas de até ~max_words palavras, respeitando frases."""
    scenes = []
    for para in re.split(r"\n\s*\n", text.strip()):
        sentences = re.split(r"(?<=[.!?…])\s+", " ".join(para.split()))
        cur = []
        for snt in sentences:
            if cur and len(" ".join(cur + [snt]).split()) > max_words:
                scenes.append(" ".join(cur))
                cur = []
            cur.append(snt)
        if cur:
            scenes.append(" ".join(cur))
    return [s for s in scenes if s.strip()]


def script_from_text(text, style, lang, log=print):
    narrs = split_text(text)
    if not narrs:
        raise RuntimeError("O texto do roteiro está vazio.")
    scenes = [{"narration": n, "image_prompt": n} for n in narrs]
    if available():
        log("Criando descrições de imagem com a IA de texto...")
        for i in range(0, len(scenes), BATCH):
            chunk = scenes[i:i + BATCH]
            try:
                data = ask_json(
                    f"Para cada narração abaixo ({lang}), escreva um image_prompt em INGLÊS com uma imagem "
                    f"concreta para ilustrá-la, sem texto escrito. Estilo: {style['name']}.\n"
                    + "\n".join(f"{k + 1}. {c['narration']}" for k, c in enumerate(chunk))
                    + '\nFormato: {"prompts": ["...", "..."]}')
                for c, p in zip(chunk, data.get("prompts", []) if isinstance(data, dict) else []):
                    if str(p).strip():
                        c["image_prompt"] = str(p).strip()
            except RuntimeError as e:
                log(f"Aviso: descrições automáticas falharam ({e}); usando a própria narração.")
                break
    return scenes
