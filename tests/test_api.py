from datetime import date

from fastapi.testclient import TestClient

from app import catalogues, ia, main
from app.models import DemandePanier, Extraction, LignePanier, Offre, PropositionPanier

client = TestClient(main.app)

OFFRE = Offre(
    type="bon", produit="Lessive", marque="X", remise_texte="-2€", remise_euros=2,
    seuil_achat=None, conditions=None, date_fin="2026-11-02",
)


def ligne(prix, eco, besoin=True):
    return LignePanier(produit="p", quantite=1, prix_estime=prix, economie_estimee=eco,
                       offres_utilisees=[], besoin=besoin, raison="r")


def test_totaliser_recalcule_les_totaux():
    p = ia.totaliser(PropositionPanier(lignes=[ligne(3.5, 1), ligne(None, 0.5)], a_faire=[], offres_ecartees=[]), 3)
    assert (p.total_estime, p.economie_totale, p.hors_budget) == (3.5, 1.5, True)


def test_totaliser_sans_budget():
    p = ia.totaliser(PropositionPanier(lignes=[ligne(10, 0)], a_faire=[], offres_ecartees=[]), None)
    assert not p.hors_budget


def test_extraction(monkeypatch):
    recu = {}

    def faux(images):
        recu["images"] = images
        return Extraction(solde_cagnotte=4.2, offres=[OFFRE])

    monkeypatch.setattr(ia, "extraire_offres", faux)
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
    monkeypatch.setattr(ia, "_parse", lambda content, fmt: PropositionPanier(
        lignes=[ligne(5, 2)], a_faire=["Activer le bon lessive"], offres_ecartees=[]))
    r = client.post("/api/panier", json={"besoins": ["lessive"], "budget": 20, "offres": [OFFRE.model_dump()]})
    assert r.status_code == 200
    assert r.json()["economie_totale"] == 2


def test_page_accueil():
    assert "Panier Carrefour" in client.get("/").text


def test_extraire_offres_appelle_gemini(monkeypatch):
    appel = {}

    class FauxModels:
        def generate_content(self, model, contents, config):
            appel.update(model=model, contents=contents, config=config)
            return type("R", (), {"text": Extraction(solde_cagnotte=None, offres=[OFFRE]).model_dump_json()})()

    monkeypatch.setattr(ia.genai, "Client", lambda: type("C", (), {"models": FauxModels()})())
    extraction = ia.extraire_offres([(b"img", "image/png")])
    assert extraction.offres == [OFFRE]
    assert appel["config"].response_schema is Extraction
    assert appel["contents"][0].inline_data.mime_type == "image/png"


LISTE_HTML = """<script type="application/ld+json">{"@graph": [
 {"@type": "ItemList", "itemListElement": [
  {"name": "Catalogue Carrefour", "url": "https://x/regardez/offres/catalogue-carrefour-42",
   "image": {"@id": "https://cdn/flyers/42/thumbnailFixedWidth/catalogue-carrefour-vos-promos-h400WebP-a.webp"}},
  {"name": "Catalogue Carrefour", "url": "https://x/regardez/offres/catalogue-carrefour-7",
   "image": {"@id": "https://cdn/flyers/7/thumbnailFixedWidth/catalogue-carrefour-h400WebP-b.webp"}}]},
 {"@type": "ImageObject", "@id": "https://cdn/flyers/42/thumbnailFixedWidth/catalogue-carrefour-vos-promos-h400WebP-a.webp",
  "name": "Catalogue Carrefour - Valable: 27/10/2026 au 09/11/2026"},
 {"@type": "ImageObject", "@id": "https://cdn/flyers/7/thumbnailFixedWidth/catalogue-carrefour-h400WebP-b.webp",
  "name": "Catalogue Carrefour - Valable: 01/10/2026 au 20/10/2026"}]}</script>"""


def test_parser_liste_catalogues():
    c42, c7 = catalogues.parser_liste(LISTE_HTML)
    assert (c42.id, c42.titre, str(c42.debut), str(c42.fin)) == (42, "Catalogue Carrefour : vos promos", "2026-10-27", "2026-11-09")
    assert c7.titre == "Catalogue Carrefour"


def test_catalogues_en_cours_ecarte_les_expires(monkeypatch):
    monkeypatch.setattr(catalogues, "_get", lambda url: type("R", (), {"text": LISTE_HTML})())
    assert [c.id for c in catalogues.catalogues_en_cours(date(2026, 10, 29))] == [42]


def test_parser_pages_catalogue():
    html = 'let flyerPages = [{"page":"\\/assets\\/uploads\\/flyers\\/42\\/%s\\/carrefour-1-a.jpeg"}];'
    assert catalogues.parser_pages(html) == ["https://img.offers-cdn.net/assets/uploads/flyers/42/large/carrefour-1-a.jpeg"]


def test_lire_catalogue_par_lots(monkeypatch):
    lots = []

    def faux_parse(contents, schema):
        lots.append(len(contents) - 1)
        return Extraction(solde_cagnotte=None, offres=[OFFRE])

    monkeypatch.setattr(ia, "_parse", faux_parse)
    cat = catalogues.Catalogue(id=42, titre="T", debut=None, fin=None, couverture="")
    extraction = ia.lire_catalogue(cat, [(b"p", "image/jpeg")] * 25, par_appel=10)
    assert sorted(lots) == [5, 10, 10]
    assert len(extraction.offres) == 3


def test_panier_ajoute_les_avantages_pass(monkeypatch):
    prompts = []
    monkeypatch.setattr(ia, "_parse", lambda content, fmt: prompts.append(content) or PropositionPanier(
        lignes=[], a_faire=[], offres_ecartees=[]))
    ia.composer_panier(DemandePanier(besoins=["pommes"], offres=[OFFRE]))
    ia.composer_panier(DemandePanier(besoins=["pommes"], offres=[OFFRE], carte_pass=False))
    assert "Fruits et légumes" in prompts[0] and "Fruits et légumes" not in prompts[1]
