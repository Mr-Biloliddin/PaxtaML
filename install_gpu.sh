#!/usr/bin/env bash
# Установка окружения для локального обучения на GPU (Linux).
# Использование:  ./install_gpu.sh            (CUDA 12.6 — по умолчанию)
#                 CUDA=cu128 ./install_gpu.sh (RTX 50xx / Blackwell, драйвер >= 570)
#                 CUDA=cu118 ./install_gpu.sh (старые драйверы)
set -euo pipefail

CUDA="${CUDA:-cu126}"
VENV="${VENV:-.venv}"
PY="${PYTHON:-python3}"

echo ">> Создаю виртуальное окружение $VENV"
"$PY" -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel setuptools

echo ">> Ставлю PyTorch ($CUDA)"
pip install torch torchvision --index-url "https://download.pytorch.org/whl/${CUDA}"

echo ">> Ставлю остальные библиотеки"
pip install -r requirements.txt

echo ">> Проверка GPU"
python scripts/check_gpu.py
