from datetime import date

import httpx
import pytest

from fastapi.testclient import TestClient

from app import catalogues, historique, ia, main
from app.models import (DemandePanier, Extraction, LectureCatalogue, LignePanier, Offre, PromoCatalogue,
                        PropositionPanier, Releve)

@pytest.fixture(autouse=True)
def quotas_neufs(monkeypatch):
    monkeypatch.setattr(ia, "_epuises", {})


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


def test_panier_sans_offre(monkeypatch):
    # Aucun catalogue lu : le panier se fait quand même avec les avantages PASS
    monkeypatch.setattr(ia, "_parse", lambda content, fmt: PropositionPanier(lignes=[], a_faire=[], offres_ecartees=[]))
    assert client.post("/api/panier", json={"besoins": ["lait"], "offres": []}).status_code == 200
    r = client.post("/api/panier", json={"besoins": ["lait"], "offres": [], "carte_pass": False})
    assert r.status_code == 400


def test_panier(monkeypatch):
    monkeypatch.setattr(ia, "_parse", lambda content, fmt: PropositionPanier(
        lignes=[ligne(5, 2)], a_faire=["Activer le bon lessive"], offres_ecartees=[]))
    r = client.post("/api/panier", json={"besoins": ["lessive"], "budget": 20, "offres": [OFFRE.model_dump()]})
    assert r.status_code == 200
    assert r.json()["economie_totale"] == 2


def test_page_accueil():
    assert client.get("/").headers["cache-control"] == "no-store"
    assert "Panier Carrefour" in client.get("/").text


def test_extraire_offres_appelle_gemini(monkeypatch):
    appel = {}

    class FauxModels:
        def generate_content(self, model, contents, config):
            appel.update(model=model, contents=contents, config=config)
            return type("R", (), {"candidates": [], "text": Extraction(solde_cagnotte=None, offres=[OFFRE]).model_dump_json()})()

    monkeypatch.setattr(ia.genai, "Client", lambda **kw: type("C", (), {"models": FauxModels()})())
    monkeypatch.setattr(ia, "_instance", None)
    extraction = ia.extraire_offres([(b"img", "image/png")])
    assert extraction.offres == [OFFRE]
    assert appel["config"].response_schema is Extraction
    assert appel["contents"][0].inline_data.mime_type == "image/png"
    assert appel["config"].http_options.timeout == 90_000


def test_gemini_reessaie_sur_limite_par_minute(monkeypatch):
    appels = []

    class FauxModels:
        def generate_content(self, **kw):
            appels.append(1)
            if len(appels) == 1:
                raise ia.errors.APIError(429, {"error": {"message": "PerMinute", "status": "RESOURCE_EXHAUSTED"}})
            return type("R", (), {"candidates": [], "text": Extraction(solde_cagnotte=None, offres=[]).model_dump_json()})()

    monkeypatch.setattr(ia, "_instance", type("C", (), {"models": FauxModels()})())
    monkeypatch.setattr(ia.time, "sleep", lambda s: None)
    assert ia.extraire_offres([(b"img", "image/png")]).offres == [] and len(appels) == 2


def test_gemini_bascule_sur_secours_puis_quota(monkeypatch):
    modeles = []

    class FauxModels:
        def generate_content(self, model, **kw):
            modeles.append(model)
            raise ia.errors.APIError(429, {"error": {"message": "PerDay", "status": "RESOURCE_EXHAUSTED"}})

    monkeypatch.setattr(ia, "_instance", type("C", (), {"models": FauxModels()})())
    monkeypatch.setattr(ia.time, "sleep", lambda s: None)
    with pytest.raises(ia.QuotaEpuise):
        ia.extraire_offres([(b"img", "image/png")])
    assert modeles == [ia.MODEL, ia.SECOURS]
    # Les deux modèles sont épuisés pour la journée : plus aucun appel
    with pytest.raises(ia.QuotaEpuise):
        ia.extraire_offres([(b"img", "image/png")])
    assert len(modeles) == 2


def test_gemini_trop_long(monkeypatch):
    class FauxModels:
        def generate_content(self, **kw):
            raise httpx.ReadTimeout("trop long")

    monkeypatch.setattr(ia, "_instance", type("C", (), {"models": FauxModels()})())
    monkeypatch.setattr(ia.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="n'a pas répondu en 90 s"):
        ia.extraire_offres([(b"img", "image/png")])


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


def test_catalogues_en_cours_ecarte_les_hors_sujet(monkeypatch):
    html = LISTE_HTML.replace("vos-promos", "bretagne")
    monkeypatch.setattr(catalogues, "_get", lambda url: type("R", (), {"text": html})())
    assert catalogues.catalogues_en_cours(date(2026, 10, 25)) == []


def test_parser_pages_catalogue():
    html = 'let flyerPages = [{"page":"\\/assets\\/uploads\\/flyers\\/42\\/%s\\/carrefour-1-a.jpeg"}];'
    assert catalogues.parser_pages(html) == ["https://img.offers-cdn.net/assets/uploads/flyers/42/large/carrefour-1-a.jpeg"]


LECTURE = LectureCatalogue(promos=[PromoCatalogue(produit="Saumon", marque="Delpeyrat", promo="-34%", prix=4.99)])
CAT = catalogues.Catalogue(id=42, titre="T", debut=date(2026, 10, 27), fin=date(2026, 11, 9), couverture="")


def test_lire_catalogue_en_peu_de_requetes(monkeypatch):
    lots = []

    def faux_parse(contents, schema, **_):
        lots.append(len(contents) - 1)
        return LECTURE

    monkeypatch.setattr(ia, "_parse", faux_parse)
    extraction, complet = ia.lire_catalogue(CAT, [(b"p", "image/jpeg")] * 75)
    assert lots == [50, 25] and complet
    o = extraction.offres[0]
    assert (o.type, o.produit, o.remise_texte, o.prix_euros, o.date_fin) == ("promo", "Saumon", "-34%", 4.99, "2026-11-09")


def test_lire_catalogue_saute_un_lot_en_echec(monkeypatch):
    def faux_parse(contents, schema, **_):
        if len(contents) == 26:
            raise RuntimeError("tronqué")
        return LECTURE

    monkeypatch.setattr(ia, "_parse", faux_parse)
    extraction, complet = ia.lire_catalogue(CAT, [(b"p", "image/jpeg")] * 75)
    assert len(extraction.offres) == 1 and not complet


def test_lire_catalogue_s_arrete_si_quota_du_jour(monkeypatch):
    def faux_parse(contents, schema, **_):
        raise ia.QuotaEpuise("quota")

    monkeypatch.setattr(ia, "_parse", faux_parse)
    with pytest.raises(ia.QuotaEpuise):
        ia.lire_catalogue(CAT, [(b"p", "image/jpeg")] * 75)


def test_quota_journalier_detecte():
    assert ia._quota_journalier(Exception("429 RESOURCE_EXHAUSTED ... GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
    assert not ia._quota_journalier(Exception("429 RESOURCE_EXHAUSTED ... PerMinute"))


def test_panier_ajoute_les_avantages_pass(monkeypatch):
    prompts = []
    monkeypatch.setattr(ia, "_parse", lambda content, fmt: prompts.append(content) or PropositionPanier(
        lignes=[], a_faire=[], offres_ecartees=[]))
    ia.composer_panier(DemandePanier(besoins=["pommes"], offres=[OFFRE]))
    ia.composer_panier(DemandePanier(besoins=["pommes"], offres=[OFFRE], carte_pass=False))
    assert "Fruits et légumes" in prompts[0] and "Fruits et légumes" not in prompts[1]


def test_cle_produit_ignore_accents_et_casse():
    assert historique.cle("Café moulu", "Carte Noire") == historique.cle("CAFE  MOULU", "carte noire")


def test_annoter_prix_deja_vus_hors_meme_catalogue():
    offre = OFFRE.model_copy(update={"prix_euros": 5.0})
    releves = [
        Releve(produit="lessive", marque="x", prix=4.0, date_fin="2026-10-01"),
        Releve(produit="Lessive", marque="X", prix=6.0, date_fin="2026-10-15"),
        Releve(produit="Lessive", marque="X", prix=5.0, date_fin=OFFRE.date_fin),
        Releve(produit="Savon", marque="X", prix=1.0, date_fin="2026-10-01"),
    ]
    assert historique.annoter(offre, releves)["prix_deja_vus"] == {"min": 4.0, "moyenne": 5.0, "releves": 2}
    assert "prix_deja_vus" not in historique.annoter(OFFRE, releves)


def test_panier_transmet_stock_habituels_et_historique(monkeypatch):
    prompts = []
    monkeypatch.setattr(ia, "_parse", lambda content, fmt: prompts.append(content) or PropositionPanier(
        lignes=[], a_faire=[], offres_ecartees=[]))
    offre = OFFRE.model_copy(update={"prix_euros": 5.0})
    ia.composer_panier(DemandePanier(besoins=[], offres=[offre], habituels=["café"], stock=["riz"],
                                     historique=[Releve(produit="Lessive", marque="X", prix=3.5, date_fin="2026-09-01")]))
    assert "café" in prompts[0] and "riz" in prompts[0] and '"min": 3.5' in prompts[0]


def test_progression_challenge():
    from app.models import Palier
    challenge = Offre(type="challenge", produit="Carrefour Expert", marque=None, remise_texte="Challenge Fid'",
                      remise_euros=None, seuil_achat=None, conditions=None, date_fin=None, deja_achete=0.79,
                      paliers=[Palier(achat_euros=3, gain_euros=0.5), Palier(achat_euros=5, gain_euros=1),
                               Palier(achat_euros=7, gain_euros=1.8)])
    assert historique.progression(challenge) == {
        "gain_acquis": 0, "reste_a_acheter": 2.21, "gain_au_prochain_palier": 0.5, "rendement_pct": 23}
    fini = challenge.model_copy(update={"deja_achete": 7.5})
    assert historique.progression(fini) == {"gain_acquis": 1.8, "termine": True}
    assert historique.progression(OFFRE) is None


def test_totaliser_separe_la_cagnotte():
    lignes = [ligne(5, 2).model_copy(update={"dont_cagnotte": 0.75}), ligne(3, 1)]
    p = ia.totaliser(PropositionPanier(lignes=lignes, a_faire=[], offres_ecartees=[]), None)
    assert (p.economie_totale, p.economie_cagnotte) == (3, 0.75)


def test_lire_avec_cache_ne_lit_qu_une_fois(monkeypatch, tmp_path):
    monkeypatch.setattr(catalogues, "CACHE", tmp_path)
    appels = []
    cat = catalogues.Catalogue(id=42, titre="T", debut=None, fin=None, couverture="")

    def lire(c, complet=True):
        appels.append(c.id)
        return Extraction(solde_cagnotte=None, offres=[OFFRE]), complet

    assert catalogues.lire_avec_cache(cat, lire) == [OFFRE]
    assert catalogues.lire_avec_cache(cat, lire) == [OFFRE]
    assert appels == [42]
    autre = cat.model_copy(update={"id": 43})
    catalogues.lire_avec_cache(autre, lambda c: lire(c, complet=False))
    assert not catalogues.est_en_cache(autre)


def test_promos_semaine_renvoie_les_catalogues_deja_lus(monkeypatch, tmp_path):
    monkeypatch.setattr(catalogues, "CACHE", tmp_path)
    cats = [catalogues.Catalogue(id=i, titre="T", debut=None, fin=None, couverture="") for i in (1, 2)]
    monkeypatch.setattr(catalogues, "catalogues_en_cours", lambda: cats)
    monkeypatch.setattr(catalogues, "pages", lambda i: [])
    monkeypatch.setattr(main, "relancer_lecture", lambda: None)
    monkeypatch.setattr(ia, "lire_catalogue", lambda c, pages: (Extraction(solde_cagnotte=None, offres=[OFFRE]), True))
    catalogues.lire_avec_cache(cats[0], lambda c: ia.lire_catalogue(c, []))
    r = client.post("/api/promos-semaine").json()
    assert len(r["catalogues"]) == 1 and len(r["offres"]) == 1
    assert client.get("/api/progression").json()["lus"] == 1
    main.lire_en_fond()
    assert client.get("/api/progression").json() == {"lus": 2, "total": 2, "en_cours": False, "erreur": None, "catalogue": None}


def test_lecture_de_fond_s_arrete_sur_quota(monkeypatch, tmp_path):
    monkeypatch.setattr(catalogues, "CACHE", tmp_path)
    cats = [catalogues.Catalogue(id=i, titre="T", debut=None, fin=None, couverture="") for i in (1, 2)]
    monkeypatch.setattr(catalogues, "catalogues_en_cours", lambda: cats)
    monkeypatch.setattr(catalogues, "pages", lambda i: [])
    appels = []

    def lire(c, pages):
        appels.append(c.id)
        raise ia.QuotaEpuise("Quota du jour")

    monkeypatch.setattr(ia, "lire_catalogue", lire)
    main.lire_en_fond()
    assert appels == [1] and main.lecture["erreur"] == "Quota du jour"
    main.lecture["erreur"] = None


def test_erreur_serveur_renvoie_du_json(monkeypatch):
    def plante():
        raise RuntimeError("clé invalide")

    monkeypatch.setattr(catalogues, "catalogues_en_cours", plante)
    r = TestClient(main.app, raise_server_exceptions=False).post("/api/promos-semaine")
    assert r.status_code == 500 and r.json() == {"detail": "RuntimeError : clé invalide"}


def test_client_gemini_partage(monkeypatch):
    monkeypatch.setattr(ia.genai, "Client", lambda **kw: object())
    monkeypatch.setattr(ia, "_instance", None)
    assert ia._client() is ia._client()


def test_alleger_page():
    import io
    from PIL import Image
    tampon = io.BytesIO()
    Image.new("RGB", (1193, 2000), "white").save(tampon, "JPEG")
    assert Image.open(io.BytesIO(catalogues.alleger(tampon.getvalue()))).size == (895, 1500)


def test_cache_caracteres_speciaux_et_fichier_vide(monkeypatch, tmp_path):
    monkeypatch.setattr(catalogues, "CACHE", tmp_path)
    cat = catalogues.Catalogue(id=9, titre="T", debut=None, fin=None, couverture="")
    (tmp_path / "9.json").write_bytes(b"")
    assert not catalogues.est_en_cache(cat)
    offre = OFFRE.model_copy(update={"produit": "Yıldız çay – œufs"})
    catalogues.lire_avec_cache(cat, lambda c: (Extraction(solde_cagnotte=None, offres=[offre]), True))
    assert catalogues.est_en_cache(cat) and catalogues.offres_en_cache(cat)[0].produit == "Yıldız çay – œufs"


def test_cache_ancien_format_windows_et_illisible(monkeypatch, tmp_path):
    monkeypatch.setattr(catalogues, "CACHE", tmp_path)
    cat = catalogues.Catalogue(id=8, titre="T", debut=None, fin=None, couverture="")
    offre = OFFRE.model_copy(update={"produit": "Purée écrasée"})
    (tmp_path / "8.json").write_bytes(Extraction(solde_cagnotte=None, offres=[offre]).model_dump_json().encode("cp1252"))
    assert catalogues.offres_en_cache(cat)[0].produit == "Purée écrasée"
    (tmp_path / "8.json").write_bytes(b"{pas du json")
    assert catalogues.offres_en_cache(cat) == [] and not catalogues.est_en_cache(cat)
