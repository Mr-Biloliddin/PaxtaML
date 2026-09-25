#!/usr/bin/env bash
# Запуск локального сайта для проверки модели: http://127.0.0.1:8000
source .venv/bin/activate
python app/server.py "$@"
