# ARCHIVE STUDIO AI

Estúdio de documentários com IA que roda **de graça na sua GPU**. Você informa um tema (ou cola um roteiro) e ele faz o roteiro, a narração, as imagens, os clipes de vídeo por IA, a câmera nas outras cenas, as legendas e a trilha, e entrega o vídeo final com thumbnail, roteiro e descrição.

```
Tema ─▶ Roteiro ─▶ Narração ─▶ Imagens (GPU) ─▶ Vídeo por IA (GPU) ─▶ Cenas ─▶ Vídeo final
        Gemini/     Edge TTS/    Z-Image/SDXL/    LTX-Video/Wan 2.2/    câmera Ken   legendas,
        LLM local   Kokoro       FLUX schnell     Maestro (WanGP)       Burns+efeito trilha
```

## O que foi aproveitado do Maestro

O [Maestro](https://github.com/blizaine/maestro) é construído sobre o WanGP. Eles têm uma **licença não comercial**, então o código deles não foi copiado para cá. O ARCHIVE STUDIO AI reaproveita o Maestro de duas formas:

1. **Os mesmos modelos abertos**, rodando direto com `diffusers`: LTX-Video, Wan 2.2, FLUX e Z-Image para imagem e vídeo, e Kokoro para voz.
2. **As mesmas ideias**, reescritas aqui:
   - perfis de memória da GPU (rápido, equilibrado e econômico), escolhidos automaticamente pela VRAM;
   - quando falta VRAM, o sistema tenta de novo sozinho no perfil econômico;
   - o modelo é carregado uma vez só e descarregado entre etapas;
   - fila de cenas;
   - LLM local para o roteiro.
3. **Ponte opcional para o Maestro que você já tem instalado:** o estúdio monta uma fila e chama o modo headless oficial (`wgp.py --process`). Assim você usa LTX-2, Wan 2.2 14B, MiniMax H3 e outros com toda a otimização do Maestro. O modelo carrega uma vez para todos os clipes.
   > Pela licença do WanGP, o *programa* só pode ser usado de forma não comercial. Os *vídeos gerados* podem ser usados comercialmente, desde que você indique que foram feitos com WanGP e coloque o link do projeto. O estúdio já escreve esse aviso no `descricao.txt` quando usa a ponte.

## Instalação no PC (Windows)

1. Instale o **Python 3.10 a 3.12** pelo [python.org](https://www.python.org/). Marque a opção **Add to PATH**.
2. Instale o **ffmpeg**: abra o PowerShell, rode `winget install Gyan.FFmpeg` e depois feche e reabra o terminal.
3. Baixe este repositório (Code → Download ZIP) e extraia.
4. Dê dois cliques em **`instalar.bat`**. Ele cria a pasta `.venv` e instala o PyTorch com CUDA e todo o resto.
5. Para abrir o painel, dê dois cliques em **`iniciar.bat`**. Ele abre `http://127.0.0.1:8765` no navegador.

No Linux ou macOS, use `./instalar.sh` e depois `./iniciar.sh`.

Se o seu PC não tiver GPU NVIDIA, o estúdio funciona do mesmo jeito: escolha **Cartão de texto** nas imagens e **Nenhum** no vídeo por IA. Você também pode enviar as suas próprias imagens em cada cena.

## Google Colab

1. Abra `colab/Archive_Studio_Colab.ipynb` no Colab e ative a GPU.
2. **Repositório privado:** nos *Secrets* do Colab (ícone 🔑), crie `GITHUB_TOKEN` e ative "Acesso ao notebook". O token se cria em github.com → Settings → Developer settings → Personal access tokens → Fine-grained, com acesso só a este repositório e permissão *Contents: Read-only*. Sem ele o Colab não consegue baixar o código (erro `git clone ... exit status 128`).
3. Rode as 3 células. O painel aparece dentro do Colab e também num link externo protegido por token.

A célula 1 baixa o branch indicado no campo `BRANCH`.

## Como usar

1. **Configurações:** escolha o motor de roteiro.
   - **Gemini:** é grátis com chave, que você pega em [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
   - **LLM local:** 100% offline. Instale o [Ollama](https://ollama.com), rode `ollama pull qwen2.5:7b` e mantenha o Ollama aberto.
   - **Manual:** você cola o seu próprio texto.

   Depois clique em **Verificar GPU**.
2. **Novo vídeo:** preencha o tema, a duração, o estilo, a voz e os geradores. Depois clique em **Gerar vídeo completo** ou em **Só o roteiro** (se quiser revisar antes).
3. **Projeto:** aqui você pode editar a narração e o prompt de qualquer cena, pedir uma *Nova imagem*, enviar a sua própria imagem, forçar ou desligar o vídeo por IA de uma cena, e enviar uma música. Depois clique em **Produzir / atualizar vídeo**. Só o que mudou é refeito, porque tudo fica em cache por cena.
4. **Resultado:** baixe o vídeo, as legendas `.srt`, a thumbnail, o roteiro e a descrição com capítulos.

Os projetos ficam em `~/archive_studio/projetos/<nome>/`. Para mudar a pasta, defina a variável `ARCHIVE_STUDIO_HOME`.

## Câmera parallax 2.5D

Em **Novo vídeo → Câmera**, escolha **Parallax 2.5D**. Cada imagem ganha um mapa de profundidade, feito pelo Depth Anything V2 Small, um modelo pequeno que roda até na CPU. Com isso, o primeiro plano se move mais que o fundo, dando sensação de 3D. Também dá para escolher o movimento de cada cena: aproximar, afastar, esquerda ou direita.

Sem PyTorch ou sem internet, o sistema usa uma profundidade sintética. O efeito é mais simples, mas o vídeo sai do mesmo jeito.

Exemplo pronto: `python exemplos/segunda_guerra_parallax.py` gera um documentário de 30 s sobre a Segunda Guerra Mundial. Ele usa fotos históricas de domínio público, narração e câmera parallax.

## Documentários verticais (Reels/Shorts) com tomadas, títulos e mapas

Cada cena pode ter várias **tomadas** de 3 a 6 s, unidas por dissolução, com cortes no início das palavras. Cada tomada pode ser:
- uma foto, enquadrada inteira sobre fundo desfocado ou recortada com parallax;
- um **mapa animado** feito com dados do Natural Earth (rio se desenhando, lagos, rotas de aquedutos, cidades);
- um **diagrama** ou um **gráfico** animado (veja `studio/graphics.py`).

O vídeo também traz:
- **títulos grandes na tela** a cada cena;
- legendas sincronizadas palavra por palavra, com números e palavras-chave em amarelo;
- rótulos de fonte, como "ARCHIVAL PHOTO";
- **trilha cinematográfica e efeitos sonoros** (vento, água, turbinas) sintetizados pelo próprio estúdio, sem risco de bloqueio por direitos autorais.

Fotos de arquivo têm as molduras de negativo cortadas automaticamente.

Exemplo completo: `python exemplos/hoover_water_reels.py` gera "How America Supplies Water to 40 Million People in the Desert". É um documentário de ~4 min em 9:16, em inglês, com fotos de domínio público da Library of Congress, mapas animados do Rio Colorado e dos aquedutos, o diagrama do resfriamento do concreto da Represa Hoover e o gráfico do nível do Lago Mead.

## Motores e VRAM aproximada

| Etapa | Motor | Custo | GPU |
|---|---|---|---|
| Roteiro | Gemini | grátis (cota diária) | — |
| Roteiro | LLM local (Ollama / LM Studio) | grátis | opcional |
| Voz | Edge TTS | grátis, precisa de internet | — |
| Voz | Kokoro (`pip install "kokoro>=0.7" soundfile`) | grátis, local | opcional |
| Imagem | Z-Image Turbo | grátis | 8 GB+ (perfil econômico) / 16 GB+ |
| Imagem | SDXL | grátis | 6–8 GB |
| Imagem | FLUX.1 schnell | grátis | 12 GB+ |
| Vídeo IA | LTX-Video | grátis | 8–12 GB |
| Vídeo IA | Wan 2.2 TI2V 5B | grátis | 12–16 GB |
| Vídeo IA | Maestro / WanGP | grátis | conforme o modelo |

- Na primeira vez em que você usa um modelo, ele é baixado do Hugging Face. São vários GB.
- Os IDs dos modelos ficam em `settings.json`, dentro da pasta do estúdio. Dá para trocar por outro modelo compatível.
- As cenas que não viram vídeo por IA ganham movimento de câmera (Ken Burns), que roda na CPU.
- O número de clipes de IA por vídeo é definido em Configurações (padrão: 6).

## Ponte com o Maestro (passo a passo)

1. Instale o Maestro pelo Pinokio e abra-o uma vez para baixar o modelo que você quer usar. Por exemplo, LTX-2.3 Distilled.
2. **Feche o Maestro** antes de produzir, para não disputar a VRAM.
3. No estúdio, vá em **Configurações → Ponte Maestro**:
   - **Pasta com wgp.py:** a pasta `app` do Maestro, por exemplo `C:\pinokio\api\maestro.git\app`.
   - **Python:** deixe vazio. O estúdio procura `env`, `env-sol` e `env-rtx50` dentro da pasta.
   - **Modelo (`model_type`):** é o nome do arquivo em `app/defaults` sem o `.json`. Exemplos: `ltx2_22B_distilled`, `i2v_2_2`, `minimax_h3`.
4. Clique em **Testar pasta do Maestro** e, no novo vídeo, escolha **Vídeo por IA → Maestro / WanGP**.

## Estrutura (fácil de remanejar)

```
run.py                 inicia o painel
studio/
  config.py            todas as opções e padrões (um dicionário)
  styles.py            estilos visuais (copie um bloco para criar outro)
  gpu.py               detecção de GPU e perfis de memória
  media.py             ffmpeg: câmera Ken Burns e parallax, ajuste de clipes, legendas, montagem
  depth.py             mapa de profundidade para o parallax (Depth Anything ou sintético)
  graphics.py          mapas animados, diagramas e gráficos (motion graphics)
  audio.py             trilha cinematográfica e efeitos sonoros sintetizados
  pipeline.py          etapas, projetos, cache e tarefas em segundo plano
  server.py            API Flask
  engines/
    script.py          roteiro (Gemini, LLM local, manual)
    voice.py           voz (Edge TTS, Kokoro)
    image.py           imagens (Z-Image, SDXL, FLUX, cartão)
    video.py           vídeo IA (LTX, Wan, ponte Maestro)
  web/index.html       painel (HTML + JS puro, sem build)
tests/test_studio.py   testes sem GPU e sem internet
exemplos/              exemplos prontos (ex.: Segunda Guerra em parallax)
colab/                 notebook do Colab
```

- **Novo modelo de imagem:** adicione um item em `SPECS` de `engines/image.py` e o ID em `config.DEFAULTS["image_models"]`.
- **Novo modelo de vídeo:** faça o mesmo em `engines/video.py`.
- **Nova voz:** adicione em `LANGS` de `engines/voice.py`.
- **Novo estilo:** adicione em `styles.py`.

## Testes

```bash
python -m unittest discover -s tests -v
```

Os testes simulam só o que depende de serviços externos: a IA de texto, a voz online e o modelo de vídeo. O ffmpeg, a câmera, os cartões, as legendas, o cache, a edição de cenas, a API e a ponte com o Maestro (usando um `wgp.py` falso) rodam de verdade.

As chamadas reais à GPU (Z-Image, SDXL, FLUX, LTX, Wan e o Maestro real) foram escritas conforme a API atual do `diffusers` e a documentação do WanGP, mas não puderam ser executadas no ambiente de desenvolvimento, que não tem GPU. Teste primeiro com um vídeo curto (1 minuto, 480p).

## Problemas comuns

| Sintoma | Solução |
|---|---|
| `ffmpeg não encontrado` | Instale o ffmpeg e reabra o terminal. |
| "Sem GPU CUDA" | Reinstale o PyTorch com CUDA (`instalar.bat`) ou use *Cartão de texto* + *Nenhum*. |
| Falta de memória (out of memory) | Em Configurações, escolha **Perfil Econômico**, use SDXL ou LTX e 720p. |
| Gemini `429` / cota | O sistema troca de modelo sozinho. Se não resolver, espere ou use o LLM local. |
| Edge TTS falhou | Confira a internet ou troque para o Kokoro (local). |
| Download do modelo negado (401/403) | Aceite a licença do modelo no Hugging Face e cole o seu token em Configurações. |
| Maestro não gerou o clipe | Feche o Maestro, confira a pasta e o `model_type`, e veja o log. A cena usa câmera como reserva. |
