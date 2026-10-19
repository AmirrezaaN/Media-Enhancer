@echo off
rem Starts the web site and the GPU worker in two windows.
cd /d "%~dp0"
start "Media Enhancer - web" cmd /k ".venv\Scripts\waitress-serve --listen=127.0.0.1:8000 --threads=8 config.wsgi:application"
start "Media Enhancer - worker" cmd /k ".venv\Scripts\python manage.py run_worker"
echo Site: http://127.0.0.1:8000   Admin: http://127.0.0.1:8000/manage/
