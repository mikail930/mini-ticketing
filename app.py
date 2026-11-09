"""Mini-ticketing : gestion des demandes de dépannage informatique.

Lancement :  python app.py   puis ouvrir http://127.0.0.1:5000
"""
import os
import secrets
import sqlite3
from datetime import datetime

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)

STATUTS = ["Ouvert", "En cours", "En attente", "Résolu"]
PRIORITES = ["Basse", "Normale", "Haute", "Urgente"]
CATEGORIES = ["Matériel", "Logiciel", "Réseau", "Compte et accès", "Imprimante", "Autre"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    titre       TEXT NOT NULL,
    description TEXT NOT NULL,
    demandeur   TEXT NOT NULL,
    poste       TEXT NOT NULL DEFAULT '',
    categorie   TEXT NOT NULL,
    priorite    TEXT NOT NULL,
    statut      TEXT NOT NULL DEFAULT 'Ouvert',
    cree_le     TEXT NOT NULL,
    modifie_le  TEXT NOT NULL,
    resolu_le   TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    auteur    TEXT NOT NULL,
    texte     TEXT NOT NULL,
    cree_le   TEXT NOT NULL
);
"""


def maintenant() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def creer_app(chemin_base=None) -> Flask:
    app = Flask(__name__)
    app.config["BASE"] = chemin_base or os.environ.get("TICKETS_BASE", "tickets.db")
    # Sans clé fixée, les sessions sont perdues à chaque redémarrage (sans gravité ici)
    app.secret_key = os.environ.get("TICKETS_CLE") or secrets.token_hex(32)

    def base() -> sqlite3.Connection:
        if "base" not in g:
            g.base = sqlite3.connect(app.config["BASE"])
            g.base.row_factory = sqlite3.Row
            g.base.execute("PRAGMA foreign_keys = ON")
        return g.base

    @app.teardown_appcontext
    def fermer(_exc):
        connexion = g.pop("base", None)
        if connexion is not None:
            connexion.close()

    with app.app_context():
        base().executescript(SCHEMA)

    # --- Protection CSRF : un jeton par session, vérifié sur chaque formulaire ---
    def jeton() -> str:
        if "jeton" not in session:
            session["jeton"] = secrets.token_hex(16)
        return session["jeton"]

    app.jinja_env.globals["jeton"] = jeton

    @app.before_request
    def verifier_jeton():
        if request.method == "POST":
            recu = request.form.get("jeton", "")
            if not secrets.compare_digest(recu, session.get("jeton", "")) or not recu:
                abort(400, "Formulaire expiré, rechargez la page.")

    def ticket_ou_404(ticket_id: int) -> sqlite3.Row:
        ticket = base().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if ticket is None:
            abort(404)
        return ticket

    @app.route("/")
    def liste():
        statut = request.args.get("statut", "actifs")
        priorite = request.args.get("priorite", "")
        recherche = request.args.get("q", "").strip()

        conditions, valeurs = [], []
        if statut == "actifs":
            conditions.append("statut != 'Résolu'")
        elif statut in STATUTS:
            conditions.append("statut = ?")
            valeurs.append(statut)
        if priorite in PRIORITES:
            conditions.append("priorite = ?")
            valeurs.append(priorite)
        if recherche:
            conditions.append("(titre LIKE ? OR demandeur LIKE ? OR poste LIKE ?)")
            valeurs += [f"%{recherche}%"] * 3

        requete = "SELECT * FROM tickets"
        if conditions:
            requete += " WHERE " + " AND ".join(conditions)
        # Les plus urgents d'abord, puis les plus anciens
        requete += """ ORDER BY CASE priorite WHEN 'Urgente' THEN 0 WHEN 'Haute' THEN 1
                       WHEN 'Normale' THEN 2 ELSE 3 END, cree_le, id"""
        tickets = base().execute(requete, valeurs).fetchall()

        compteurs = {s: 0 for s in STATUTS}
        for ligne in base().execute("SELECT statut, COUNT(*) AS n FROM tickets GROUP BY statut"):
            compteurs[ligne["statut"]] = ligne["n"]

        return render_template("liste.html", tickets=tickets, compteurs=compteurs,
                               statut=statut, priorite=priorite, recherche=recherche,
                               statuts=STATUTS, priorites=PRIORITES)

    @app.route("/nouveau", methods=["GET", "POST"])
    def nouveau():
        if request.method == "POST":
            f = {k: request.form.get(k, "").strip()
                 for k in ("titre", "description", "demandeur", "poste", "categorie", "priorite")}
            erreurs = []
            if not f["titre"]:
                erreurs.append("Le titre est obligatoire.")
            if not f["description"]:
                erreurs.append("La description est obligatoire.")
            if not f["demandeur"]:
                erreurs.append("Le nom du demandeur est obligatoire.")
            if f["categorie"] not in CATEGORIES:
                erreurs.append("Catégorie inconnue.")
            if f["priorite"] not in PRIORITES:
                erreurs.append("Priorité inconnue.")
            if erreurs:
                for e in erreurs:
                    flash(e, "erreur")
                return render_template("nouveau.html", f=f, categories=CATEGORIES,
                                       priorites=PRIORITES), 400

            date = maintenant()
            curseur = base().execute(
                """INSERT INTO tickets (titre, description, demandeur, poste, categorie,
                                        priorite, cree_le, modifie_le)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (f["titre"][:120], f["description"], f["demandeur"][:60], f["poste"][:40],
                 f["categorie"], f["priorite"], date, date))
            base().commit()
            flash(f"Ticket n° {curseur.lastrowid} créé.", "ok")
            return redirect(url_for("detail", ticket_id=curseur.lastrowid))

        vide = {"priorite": "Normale", "categorie": CATEGORIES[0]}
        return render_template("nouveau.html", f=vide, categories=CATEGORIES, priorites=PRIORITES)

    @app.route("/ticket/<int:ticket_id>")
    def detail(ticket_id):
        ticket = ticket_ou_404(ticket_id)
        notes = base().execute("SELECT * FROM notes WHERE ticket_id = ? ORDER BY id",
                               (ticket_id,)).fetchall()
        return render_template("detail.html", t=ticket, notes=notes,
                               statuts=STATUTS, priorites=PRIORITES)

    @app.route("/ticket/<int:ticket_id>/suivi", methods=["POST"])
    def suivi(ticket_id):
        ticket = ticket_ou_404(ticket_id)
        statut = request.form.get("statut", ticket["statut"])
        priorite = request.form.get("priorite", ticket["priorite"])
        auteur = request.form.get("auteur", "").strip()[:60]
        texte = request.form.get("texte", "").strip()

        if statut not in STATUTS or priorite not in PRIORITES:
            abort(400)
        if texte and not auteur:
            flash("Indiquez votre nom pour ajouter une note.", "erreur")
            return redirect(url_for("detail", ticket_id=ticket_id))
        # Clôturer sans explication rend l'historique inutilisable
        if statut == "Résolu" and ticket["statut"] != "Résolu" and not texte:
            flash("Ajoutez une note décrivant la solution avant de clôturer.", "erreur")
            return redirect(url_for("detail", ticket_id=ticket_id))

        date = maintenant()
        changements = []
        if statut != ticket["statut"]:
            changements.append(f"Statut : {ticket['statut']} → {statut}")
        if priorite != ticket["priorite"]:
            changements.append(f"Priorité : {ticket['priorite']} → {priorite}")
        if not changements and not texte:
            return redirect(url_for("detail", ticket_id=ticket_id))

        if statut == "Résolu":
            resolu_le = ticket["resolu_le"] or date
        else:
            resolu_le = None  # ticket rouvert
        base().execute("UPDATE tickets SET statut = ?, priorite = ?, modifie_le = ?, "
                       "resolu_le = ? WHERE id = ?",
                       (statut, priorite, date, resolu_le, ticket_id))
        contenu = "\n".join(filter(None, [" · ".join(changements), texte]))
        base().execute("INSERT INTO notes (ticket_id, auteur, texte, cree_le) VALUES (?, ?, ?, ?)",
                       (ticket_id, auteur or "Système", contenu, date))
        base().commit()
        flash("Ticket mis à jour.", "ok")
        return redirect(url_for("detail", ticket_id=ticket_id))

    return app


if __name__ == "__main__":
    # Accessible uniquement depuis ce poste. Voir le README pour un usage sur le réseau.
    creer_app().run(host="127.0.0.1", port=5000)
