import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import creer_app

TICKET = {"titre": "Imprimante en panne", "description": "Voyant rouge fixe",
          "demandeur": "Sarah Benali", "poste": "PC-ACCUEIL-02",
          "categorie": "Imprimante", "priorite": "Haute"}


class TestTickets(unittest.TestCase):
    def setUp(self):
        fd, self.chemin = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.client = creer_app(self.chemin).test_client()

    def tearDown(self):
        os.unlink(self.chemin)

    def jeton(self):
        page = self.client.get("/nouveau").get_data(as_text=True)
        return re.search(r'name="jeton" value="(\w+)"', page).group(1)

    def poster(self, url, donnees):
        return self.client.post(url, data={**donnees, "jeton": self.jeton()})

    def test_creation_et_affichage(self):
        r = self.poster("/nouveau", TICKET)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/ticket/1"))
        page = self.client.get("/ticket/1").get_data(as_text=True)
        self.assertIn("Imprimante en panne", page)
        self.assertIn("#0001", page)
        self.assertIn("Imprimante en panne", self.client.get("/").get_data(as_text=True))

    def test_champs_obligatoires(self):
        r = self.poster("/nouveau", {**TICKET, "titre": "  "})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Le titre est obligatoire", r.get_data(as_text=True))
        r = self.poster("/nouveau", {**TICKET, "priorite": "Critique"})
        self.assertEqual(r.status_code, 400)

    def test_formulaire_sans_jeton_refuse(self):
        self.assertEqual(self.client.post("/nouveau", data=TICKET).status_code, 400)
        self.assertEqual(self.client.post("/nouveau", data={**TICKET, "jeton": "faux"}).status_code, 400)

    def test_html_echappe(self):
        self.poster("/nouveau", {**TICKET, "titre": "<script>alert(1)</script>"})
        page = self.client.get("/ticket/1").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_cloture_exige_une_note(self):
        self.poster("/nouveau", TICKET)
        self.poster("/ticket/1/suivi", {"statut": "Résolu", "priorite": "Haute"})
        page = self.client.get("/ticket/1").get_data(as_text=True)
        self.assertIn("Ajoutez une note", page)
        self.assertNotIn("Résolu le", page)

        self.poster("/ticket/1/suivi", {"statut": "Résolu", "priorite": "Haute",
                                        "auteur": "Karim", "texte": "Cartouche remplacée"})
        page = self.client.get("/ticket/1").get_data(as_text=True)
        self.assertIn("Résolu le", page)
        self.assertIn("Statut : Ouvert → Résolu", page)
        self.assertIn("Cartouche remplacée", page)

    def test_reouverture_efface_la_date_de_resolution(self):
        self.poster("/nouveau", TICKET)
        self.poster("/ticket/1/suivi", {"statut": "Résolu", "priorite": "Haute",
                                        "auteur": "Karim", "texte": "Corrigé"})
        self.poster("/ticket/1/suivi", {"statut": "En cours", "priorite": "Haute"})
        self.assertNotIn("Résolu le", self.client.get("/ticket/1").get_data(as_text=True))

    def test_filtres_et_tri(self):
        self.poster("/nouveau", {**TICKET, "titre": "Souris cassée", "priorite": "Basse"})
        self.poster("/nouveau", {**TICKET, "titre": "Serveur injoignable", "priorite": "Urgente"})
        self.poster("/ticket/1/suivi", {"statut": "Résolu", "priorite": "Basse",
                                        "auteur": "Karim", "texte": "Remplacée"})

        actifs = self.client.get("/").get_data(as_text=True)
        self.assertIn("Serveur injoignable", actifs)
        self.assertNotIn("Souris cassée", actifs)

        tous = self.client.get("/?statut=tous").get_data(as_text=True)
        self.assertLess(tous.index("Serveur injoignable"), tous.index("Souris cassée"))

        self.assertIn("Souris cassée", self.client.get("/?statut=Résolu").get_data(as_text=True))
        recherche = self.client.get("/?statut=tous&q=serveur").get_data(as_text=True)
        self.assertNotIn("Souris cassée", recherche)

    def test_recherche_sans_injection(self):
        self.poster("/nouveau", TICKET)
        r = self.client.get("/?statut=tous&q=' OR 1=1 --")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Imprimante en panne", r.get_data(as_text=True))

    def test_ticket_inconnu(self):
        self.assertEqual(self.client.get("/ticket/999").status_code, 404)
        self.assertEqual(self.poster("/ticket/999/suivi", {"statut": "Résolu"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
