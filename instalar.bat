@echo off
REM Instala o ARCHIVE STUDIO AI no Windows (cria a pasta .venv com tudo dentro).
cd /d "%~dp0"
where python >nul 2>nul || (echo Instale o Python 3.10+ em python.org marcando "Add to PATH". & pause & exit /b 1)
where ffmpeg >nul 2>nul || echo AVISO: ffmpeg nao encontrado. Rode: winget install Gyan.FFmpeg  (e reabra o terminal)
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -U pip
REM PyTorch com CUDA (GPUs NVIDIA). Troque cu128 se o site pytorch.org indicar outra versao.
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements-gpu.txt
echo.
echo Pronto! Use iniciar.bat para abrir o painel.
pause
