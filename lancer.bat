@echo off
chcp 65001 >nul
title Panier Carrefour
rem Double-clic : installe si besoin et ouvre l'appli dans le navigateur.
cd /d "%~dp0"
echo.
echo === Panier Carrefour ===
echo Dossier : %CD%
echo.

rem Le dossier doit etre extrait du zip, pas ouvert directement dedans
if not exist "app\main.py" (
  echo [ERREUR] Fichiers introuvables. Fais clic droit sur le zip ^> "Extraire tout", puis lance lancer.bat depuis le dossier extrait.
  goto fin
)

rem Python : le lanceur "py" est installe par python.org meme sans la case PATH
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
  python --version >nul 2>&1 && set PY=python
)
if not defined PY (
  echo [ERREUR] Python n'est pas installe.
  echo Installe-le depuis https://www.python.org/downloads/ en cochant "Add Python to PATH", puis relance.
  start "" https://www.python.org/downloads/
  goto fin
)
echo [1/4] Python trouve :
%PY% --version

where git >nul 2>&1 && if exist ".git" git pull --ff-only -q

if not exist ".venv\Scripts\python.exe" (
  echo [2/4] Creation de l'environnement, premiere fois seulement...
  %PY% -m venv .venv || (echo [ERREUR] Impossible de creer l'environnement Python. & goto fin)
)
echo [3/4] Installation des dependances, 1 a 2 minutes la premiere fois...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || (echo [ERREUR] Installation impossible : verifie ta connexion internet. & goto fin)

if not exist ".env" copy ".env.example" ".env" >nul
findstr /c:"colle_ta_cle_ici" ".env" >nul && (
  echo.
  echo Colle ta cle Gemini a la place de colle_ta_cle_ici dans le Bloc-notes qui s'ouvre, enregistre ^(Ctrl+S^) et ferme-le.
  notepad ".env"
)

echo [4/4] Demarrage. L'appli s'ouvre dans ton navigateur : laisse cette fenetre ouverte pendant que tu l'utilises.
start "" cmd /c "timeout /t 5 >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn app.main:app --env-file .env

:fin
echo.
pause
