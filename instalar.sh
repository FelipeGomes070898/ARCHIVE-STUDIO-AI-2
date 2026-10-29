#!/usr/bin/env bash
# Instala o ARCHIVE STUDIO AI no Linux/macOS (cria a pasta .venv).
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || echo "AVISO: instale o ffmpeg (sudo apt install ffmpeg | brew install ffmpeg)"
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
if command -v nvidia-smi >/dev/null; then
  pip install torch --index-url https://download.pytorch.org/whl/cu128
  pip install -r requirements-gpu.txt
else
  echo "Sem GPU NVIDIA: instalando só a base (cartões de texto + câmera)."
  pip install -r requirements.txt
fi
echo "Pronto! Rode ./iniciar.sh"
