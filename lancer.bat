@echo off
rem Double-clic : met a jour, installe si besoin et ouvre l appli dans le navigateur.
cd /d "%~dp0"
git pull --ff-only -q 2>nul
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  echo Colle ta cle Gemini dans le fichier qui s ouvre, enregistre et ferme-le.
  notepad .env
)
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
uvicorn app.main:app --env-file .env
pause
