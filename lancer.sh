#!/bin/sh
# Met à jour, installe si besoin et ouvre l'appli dans le navigateur (Mac / Linux).
cd "$(dirname "$0")"
git pull --ff-only -q 2>/dev/null
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Colle ta clé Gemini dans .env puis relance."; exit 1; }
(sleep 4; open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000) &
uvicorn app.main:app --env-file .env
