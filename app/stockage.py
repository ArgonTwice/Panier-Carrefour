"""Stockage clé → texte.

En ligne (DATABASE_URL défini, ex. base Neon gratuite) : base Postgres, qui survit à la mise en veille de Render
et partage les données entre le téléphone et le PC. Sur le PC sans base : fichiers dans data/.
"""
import os
from pathlib import Path

DOSSIER = Path(__file__).parent.parent / "data"
# Ce processus est le seul à écrire : ce qui a été lu ou écrit est gardé en mémoire
_memoire: dict[str, str] = {}


def _base():
    import psycopg  # seulement en ligne

    connexion = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    connexion.execute("CREATE TABLE IF NOT EXISTS stockage (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL)")
    return connexion


def _fichier(cle: str) -> Path:
    return DOSSIER / f"{cle}.json"


def lire(cle: str) -> str | None:
    if cle in _memoire:
        return _memoire[cle]
    if os.environ.get("DATABASE_URL"):
        with _base() as c:
            ligne = c.execute("SELECT valeur FROM stockage WHERE cle = %s", (cle,)).fetchone()
        valeur = ligne[0] if ligne else None
    else:
        brut = _fichier(cle).read_bytes() if _fichier(cle).exists() else b""
        try:
            valeur = brut.decode("utf-8")
        except UnicodeDecodeError:
            valeur = brut.decode("cp1252", errors="replace")  # fichier écrit par une ancienne version sous Windows
        valeur = valeur or None  # fichier vide : écriture interrompue
    if valeur is not None:
        _memoire[cle] = valeur
    return valeur


def ecrire(cle: str, valeur: str) -> None:
    if os.environ.get("DATABASE_URL"):
        with _base() as c:
            c.execute("INSERT INTO stockage VALUES (%s, %s) ON CONFLICT (cle) DO UPDATE SET valeur = EXCLUDED.valeur",
                      (cle, valeur))
    else:
        _fichier(cle).parent.mkdir(parents=True, exist_ok=True)
        # Fichier temporaire puis renommage : jamais de fichier à moitié écrit
        temporaire = _fichier(cle).with_suffix(".tmp")
        temporaire.write_bytes(valeur.encode("utf-8"))
        temporaire.replace(_fichier(cle))
    _memoire[cle] = valeur


def cles(prefixe: str) -> list[str]:
    if os.environ.get("DATABASE_URL"):
        with _base() as c:
            return [l[0] for l in c.execute("SELECT cle FROM stockage WHERE cle LIKE %s", (prefixe + "%",))]
    return [f"{prefixe}{f.stem}" for f in (DOSSIER / prefixe).glob("*.json")]


def supprimer(cle: str) -> None:
    _memoire.pop(cle, None)
    if os.environ.get("DATABASE_URL"):
        with _base() as c:
            c.execute("DELETE FROM stockage WHERE cle = %s", (cle,))
    else:
        _fichier(cle).unlink(missing_ok=True)
