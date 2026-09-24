@echo off
REM Установка окружения для локального обучения на GPU (Windows).
REM Использование:  install_gpu.bat          (CUDA 12.6 по умолчанию)
REM                 install_gpu.bat cu128    (RTX 50xx, драйвер >= 570)
REM                 install_gpu.bat cu118    (старые драйверы)
setlocal
set CUDA=%1
if "%CUDA%"=="" set CUDA=cu126

python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip wheel setuptools

pip install torch torchvision --index-url https://download.pytorch.org/whl/%CUDA% || exit /b 1
pip install -r requirements.txt || exit /b 1

python scripts\check_gpu.py
endlocal
