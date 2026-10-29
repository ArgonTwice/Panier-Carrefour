from fastapi.testclient import TestClient

from app import claude, main
from app.models import Extraction, LignePanier, Offre, PropositionPanier

client = TestClient(main.app)

OFFRE = Offre(
    type="bon", produit="Lessive", marque="X", remise_texte="-2€", remise_euros=2,
    seuil_achat=None, conditions=None, date_fin="2026-11-02",
)


def ligne(prix, eco, besoin=True):
    return LignePanier(produit="p", quantite=1, prix_estime=prix, economie_estimee=eco,
                       offres_utilisees=[], besoin=besoin, raison="r")


def test_totaliser_recalcule_les_totaux():
    p = claude.totaliser(PropositionPanier(lignes=[ligne(3.5, 1), ligne(None, 0.5)], a_faire=[], offres_ecartees=[]), 3)
    assert (p.total_estime, p.economie_totale, p.hors_budget) == (3.5, 1.5, True)


def test_totaliser_sans_budget():
    p = claude.totaliser(PropositionPanier(lignes=[ligne(10, 0)], a_faire=[], offres_ecartees=[]), None)
    assert not p.hors_budget


def test_extraction(monkeypatch):
    recu = {}

    def faux(images):
        recu["images"] = images
        return Extraction(solde_cagnotte=4.2, offres=[OFFRE])

    monkeypatch.setattr(claude, "extraire_offres", faux)
    r = client.post("/api/extraction", files=[("captures", ("a.png", b"img", "image/png"))])
    assert r.status_code == 200
    assert r.json()["solde_cagnotte"] == 4.2
    assert recu["images"] == [(b"img", "image/png")]


def test_extraction_refuse_format_non_image():
    r = client.post("/api/extraction", files=[("captures", ("a.pdf", b"x", "application/pdf"))])
    assert r.status_code == 400


def test_panier_sans_offre():
    assert client.post("/api/panier", json={"besoins": ["lait"], "offres": []}).status_code == 400


def test_panier(monkeypatch):
    monkeypatch.setattr(claude, "_parse", lambda content, fmt: PropositionPanier(
        lignes=[ligne(5, 2)], a_faire=["Activer le bon lessive"], offres_ecartees=[]))
    r = client.post("/api/panier", json={"besoins": ["lessive"], "budget": 20, "offres": [OFFRE.model_dump()]})
    assert r.status_code == 200
    assert r.json()["economie_totale"] == 2


def test_page_accueil():
    assert "Panier Carrefour" in client.get("/").text
