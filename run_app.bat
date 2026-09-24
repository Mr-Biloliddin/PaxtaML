@echo off
REM Запуск локального сайта для проверки модели: http://127.0.0.1:8000
REM Доп. параметры передаются дальше, например: run_app.bat --weights runs\growth_stage\...\best.pt
call .venv\Scripts\activate.bat
python app\server.py %*
