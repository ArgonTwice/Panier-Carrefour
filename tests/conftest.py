import pytest

from app import ia, stockage


@pytest.fixture(autouse=True)
def quotas_neufs(monkeypatch, tmp_path):
    monkeypatch.setattr(ia, "_epuises", {})
    monkeypatch.setattr(stockage, "_memoire", {})
    monkeypatch.setattr(stockage, "DOSSIER", tmp_path / "data")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_MOT_DE_PASSE", raising=False)
