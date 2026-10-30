import json
from datetime import date

from fastapi.testclient import TestClient
from pywebpush import WebPushException

from app import auto, catalogues, ia, main, notifications, stockage
from app.avantages import AVANTAGES_PASS
from app.models import AchatChallenge, Extraction, LectureTicket, LigneTicket, Offre, PropositionPanier
from tests.test_api import OFFRE, ligne

client = TestClient(main.app)
MARDI = date(2026, 11, 3)


def sauver_etat(etat, champs):
    stockage.ecrire("etat", json.dumps({"etat": etat, "champs": champs}))


def test_mardi_de_la_semaine_carrefour():
    assert auto.mardi(MARDI) == MARDI
    assert auto.mardi(date(2026, 11, 9)) == MARDI  # lundi suivant : encore la semaine du mardi 3
    assert auto.mardi(date(2026, 11, 2)) == date(2026, 10, 27)


def test_mardi_pass():
    assert any(o.jour == "mardi" and o.marque == "Carrefour" for o in AVANTAGES_PASS)


def test_comme_d_habitude_retire_le_stock():
    assert auto.comme_d_habitude(["Café", "Pâtes", "Lessive"], ["pates"]) == ["Café", "Lessive"]


def preparer_panier(monkeypatch, debut=MARDI):
    cat = catalogues.Catalogue(id=1, titre="T", debut=debut, fin=None, couverture="")
    catalogues.lire_avec_cache(cat, lambda c: (Extraction(solde_cagnotte=None, offres=[OFFRE]), True))
    demandes, envois = [], []
    monkeypatch.setattr(ia, "composer_panier", lambda d: demandes.append(d) or ia.totaliser(
        PropositionPanier(lignes=[ligne(5, 2)], a_faire=[], offres_ecartees=[]), None))
    monkeypatch.setattr(notifications, "envoyer", lambda titre, texte: envois.append(texte) or 1)
    return cat, demandes, envois


def test_panier_auto_le_mardi_une_fois(monkeypatch):
    cat, demandes, envois = preparer_panier(monkeypatch)
    valable = OFFRE.model_copy(update={"date_fin": "2026-11-10"})
    expire = OFFRE.model_copy(update={"date_fin": "2026-11-01", "produit": "Vieux"})
    sauver_etat({"offres": [valable.model_dump(), expire.model_dump()]},
                {"besoins": "", "habituels": "Café\nPâtes", "stock": "pâtes", "canal": "magasin"})
    assert auto.panier_de_la_semaine([cat], MARDI)
    assert demandes[0].besoins == ["Café"] and demandes[0].canal == "magasin"
    assert [o.produit for o in demandes[0].offres] == ["Lessive", "Lessive"]  # bon perso + catalogue, sans l'expiré
    etat = json.loads(stockage.lire("etat"))
    assert etat["etat"]["panier"]["auto"] == "2026-11-03" and etat["champs"]["habituels"] == "Café\nPâtes"
    assert "5.00 €" in envois[0]
    assert not auto.panier_de_la_semaine([cat], date(2026, 11, 4))  # déjà fait cette semaine


def test_panier_auto_attend_les_nouveaux_catalogues(monkeypatch):
    cat, demandes, _ = preparer_panier(monkeypatch, debut=date(2026, 10, 27))
    sauver_etat({}, {"besoins": "lait"})
    assert not auto.panier_de_la_semaine([cat], MARDI) and not demandes


def test_panier_auto_sans_besoins(monkeypatch):
    cat, demandes, _ = preparer_panier(monkeypatch)
    sauver_etat({}, {"besoins": ""})
    assert not auto.panier_de_la_semaine([cat], MARDI) and not demandes


def test_lecture_de_fond_lance_le_panier_auto(monkeypatch):
    monkeypatch.setattr(catalogues, "catalogues_en_cours", lambda: [])
    appels = []
    monkeypatch.setattr(auto, "panier_de_la_semaine", lambda en_cours: appels.append(en_cours))
    main.lire_en_fond()
    assert appels == [[]]


def test_rappel_des_bons_une_seule_fois(monkeypatch):
    envois = []
    monkeypatch.setattr(notifications, "envoyer", lambda titre, texte: envois.append((titre, texte)) or 1)
    bientot = OFFRE.model_copy(update={"date_fin": "2026-11-05"})  # jeudi
    loin = OFFRE.model_copy(update={"date_fin": "2026-11-20", "produit": "Café"})
    promo = OFFRE.model_copy(update={"type": "promo", "produit": "Riz"})
    sauver_etat({"offres": [o.model_dump() for o in (bientot, loin, promo)]}, {})
    assert auto.rappeler_bons(MARDI) == ["Lessive (jeudi)"]
    assert envois == [("⏰ 1 bon expire bientôt", "Lessive (jeudi)")]
    assert auto.rappeler_bons(date(2026, 11, 4)) == []


def test_rappel_reessaye_si_aucun_appareil(monkeypatch):
    monkeypatch.setattr(notifications, "envoyer", lambda titre, texte: 0)
    sauver_etat({"offres": [OFFRE.model_dump()]}, {})
    auto.rappeler_bons(date(2026, 10, 31))
    assert stockage.lire("rappels") is None


def test_ticket(monkeypatch):
    recu = {}
    lu = LectureTicket(date="2026-10-30", total=12.5, solde_cagnotte=3,
                       lignes=[LigneTicket(produit="Pâtes", marque=None, prix_unitaire=1.2, prix_total=2.4, quantite=2,
                                           se_conserve=True)],
                       challenges=[AchatChallenge(numero=0, montant=2.4)])
    monkeypatch.setattr(ia, "lire_ticket", lambda photos, challenges: recu.update(p=photos, c=challenges) or lu)
    challenge = OFFRE.model_copy(update={"type": "challenge", "produit": "Barilla"})
    r = client.post("/api/ticket", files=[("photos", ("t.jpg", b"img", "image/jpeg"))],
                    data={"challenges": json.dumps([challenge.model_dump()])})
    assert r.status_code == 200 and r.json()["challenges"][0]["montant"] == 2.4
    assert recu["p"] == [(b"img", "image/jpeg")] and recu["c"][0].produit == "Barilla"
    assert client.post("/api/ticket", files=[("photos", ("t.mp4", b"v", "video/mp4"))]).status_code == 400


def test_lire_ticket_donne_les_challenges_a_gemini(monkeypatch):
    prompts = []
    monkeypatch.setattr(ia, "_parse", lambda contents, schema, **_: prompts.append(contents[-1]) or schema)
    challenge = OFFRE.model_copy(update={"type": "challenge", "produit": "Rayon bio", "marque": None})
    ia.lire_ticket([(b"img", "image/jpeg")], [challenge])
    assert "0 : Rayon bio (toutes marques)" in prompts[0]


def test_reveil_sans_mot_de_passe(monkeypatch):
    monkeypatch.setenv("APP_MOT_DE_PASSE", "secret")
    appels = []
    monkeypatch.setattr(main, "reveiller", lambda: appels.append(1))
    assert client.get("/api/reveil").status_code == 200
    assert client.get("/api/etat").status_code == 401


def test_cle_de_notification_creee_une_fois():
    cle = client.get("/api/notifications").json()["cle"]
    stockage._memoire.clear()
    assert notifications.cle_publique() == cle and len(cle) == 87


def test_envoi_retire_les_appareils_desabonnes(monkeypatch):
    for endpoint in ("a", "b", "a"):
        client.post("/api/notifications", json={"endpoint": endpoint, "keys": {}})
    assert [a["endpoint"] for a in notifications._abonnements()] == ["b", "a"]

    def faux(abonnement, donnees, **kw):
        if abonnement["endpoint"] == "a":
            raise WebPushException("parti", response=type("R", (), {"status_code": 410})())

    monkeypatch.setattr(notifications, "webpush", faux)
    assert notifications.envoyer("t", "x") == 1
    assert [a["endpoint"] for a in notifications._abonnements()] == ["b"]
