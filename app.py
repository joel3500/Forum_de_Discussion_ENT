# app.py

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, flash, session
)
from models import initialize, User, Topic, Comment, now_utc_naive
from datetime import datetime
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import os, re, json
from datetime import datetime, date
from openai import OpenAI
from models_0_reponses_non_recurssives import NewsCache

from datetime import timezone, timedelta
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os
from peewee import prefetch
from models_0_reponses_non_recurssives import Reply

# recherche par mot-clé + pagination (pour admin) ---------
from math import ceil
from peewee import fn


IMG_DIR = os.environ.get("IMG_DIR", "static/img")

load_dotenv()
initialize()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
#IMAGE_DIR = os.environ.get("IMAGE_DIR", "static/images")
#IMAGE_PRINCIPALE = os.environ.get("IMAGE_PRINCIPALE", "image_principale_ent.jpg")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
oai_client = None
if OPENAI_API_KEY:
    oai_client = OpenAI(api_key=OPENAI_API_KEY)

LOCAL_TZ = ZoneInfo("America/Toronto")

# ----- Token reset password -----
def ts():
    return URLSafeTimedSerializer(app.secret_key, salt="reset-password-salt")

# Pour toi à Saguenay (QC) ~ America/Toronto ; on simplifie à -04:00/-05:00.
# Pour strict, installe pytz/zoneinfo; ici on reste simple:
LOCAL_OFFSET = -4  # en heures (ajuste si heure d'hiver)
def today_local_iso():
    return now_utc_naive + timedelta(hours=LOCAL_OFFSET)

def to_local_str(dt_naive_utc):
    dt_local = dt_naive_utc.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return dt_local.strftime("%Y-%m-%d %H:%M")

# ----- Helpers -----
def current_user():
    uid = session.get("uid")
    if not uid: return None
    try:
        return User.get_by_id(uid)
    except:
        return None

def admin_required():
    u = current_user()
    if not u or u.is_admin != "yes":
        flash("Accès admin requis.")
        return redirect(url_for('index'))

def is_owner_or_admin(owner_user_id):
    u = current_user()
    return u and (u.is_admin == "yes" or (owner_user_id is not None and u.id == owner_user_id))


# ----- Seed admin -----
def seed_admin():
    admin_nom   = "Joel Sandé"
    admin_email = "docjoel007@gmail.com"
    admin_pwd   = "Episte_Plous2025"
    u = User.get_or_none(User.email == admin_email.lower())
    if not u:
        User.create(
            nom=admin_nom,
            email=admin_email.lower(),
            password_hash=generate_password_hash(admin_pwd),
            is_admin="yes"
        )

seed_admin()

# ----- Validators -----
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
def validate_email(email:str)->bool:
    return bool(EMAIL_RE.match(email or ""))

def validate_password(p:str)->tuple[bool,str]:
    if not p or len(p) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères."
    return True, ""

def fetch_saguenay_news_with_openai():
    """
    Appelle OpenAI pour produire une liste d'événements/actus entreprenariat au Saguenay.
    Retourne un dict {"items":[{title,date,place,description,source}], "model": "..."}.
    NB: Cette version ne "navigue" pas le web (pas de scraping). Pour la prod,
    tu peux brancher un crawler et demander à l'IA de *synthétiser* le crawl.
    """
    if not oai_client:
        # Fallback déterministe si pas de clé
        return {
            "items":[
                {"title":"(DEMO) Forum Startup Saguenay", "date":"2025-10-15", "place":"Centre-ville Saguenay",
                 "description":"Rencontres entrepreneurs, kiosques, mini-pitchs.","source":"https://exemple.local"},
                {"title":"(DEMO) Conférence PME & Investisseurs", "date":"2025-11-02", "place":"UQAC",
                 "description":"Financement, mentors, réseautage 5 à 7.","source":"https://exemple.local"}
            ],
            "model":"demo-no-key"
        }

    prompt = (
        "Tu es un assistant qui dresse un bulletin quotidien des actualités et événements "
        "liés à l'entrepreneuriat au Saguenay (Québec). "
        "Produis une liste concise (3–8 éléments max) des informations pertinentes à court terme "
        "(rencontres, conférences, ateliers, foires, 5 à 7, appels à projets, incubateurs), "
        "avec ce format JSON strict:\n\n"
        "{\n"
        '  "items": [\n'
        '    {"title": "...","date": "YYYY-MM-DD or date range","place":"...",'
        '     "description":"1-2 phrases utiles","source":"URL si connue ou vide"}\n'
        "  ]\n"
        "}\n\n"
        "Ne mets pas de texte hors JSON. Si tu n'as pas de sources sûres, laisse source=\"\"."
    )

    resp = oai_client.responses.create(
        model="gpt-4o-mini",  # économique/rapide; change si tu veux
        input=prompt,
        temperature=0.2
    )
    text = resp.output_text  # SDK v1: texte brut
    try:
        data = json.loads(text)
        if not isinstance(data.get("items", []), list):
            raise ValueError("items not list")
    except Exception:
        # garde un message lisible si la sortie n'est pas JSON strict
        data = {"items": [{"title":"Actualités indisponibles",
                           "date": "", "place":"", "description":"Erreur de format JSON.",
                           "source":""}], "model":"gpt-4o-mini"}
    data["model"] = "gpt-4o-mini"
    return data

# Helper: lire/écrire le cache “une fois par jour”
def get_saguenay_news_daily():
    key = "saguenay_entrepreneuriat"
    today_local = now_utc_naive()

    row = NewsCache.get_or_none(NewsCache.key == key)
    if row:
        # row.fetched_at est naïf UTC → on le “re-UTCise” puis on convertit en local
        fetched_local_date = row.fetched_at.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).date()
        try:
            payload = json.loads(row.payload) if row.payload else {}
        except Exception:
            payload = {}
        if fetched_local_date == today_local and payload.get("items"):
            return payload

    # Sinon: régénérer via OpenAI
    payload = fetch_saguenay_news_with_openai()
    if row:
        row.payload = json.dumps(payload, ensure_ascii=False)
        row.fetched_at = now_utc_naive()
        row.save()
    else:
        NewsCache.create(
            key=key,
            payload=json.dumps(payload, ensure_ascii=False),
            fetched_at=now_utc_naive()
        )
    return payload

def list_forum_images():
    try:
        names = [n for n in os.listdir(IMG_DIR) if n.lower().endswith((".jpg",".jpeg",".png",".gif"))]
    except Exception:
        names = []
    # ordre souhaité
    order = ["image_principale_ent.jpeg", "1.jpeg", "2.jpeg", "3.jpeg", "4.jpeg", "5.jpeg", "6.jpeg"]
    names_sorted = [n for n in order if n in names]
    # ajoute les éventuels fichiers en plus, à la fin
    for n in names:
        if n not in names_sorted:
            names_sorted.append(n)

    main_name = "image_principale_ent.jpeg" if "image_principale_ent.jpeg" in names_sorted else (names_sorted[0] if names_sorted else None)
    main_url = f"img/{main_name}" if main_name else None

    # galerie = toutes sauf la principale
    gallery_urls = [f"img/{n}" for n in names_sorted if n != main_name]
    return main_url, gallery_urls

@app.context_processor
def inject_gallery():
    main_image_url, gallery_urls = list_forum_images()
    return dict(main_image_url=main_image_url, gallery_urls=gallery_urls)


# ----- Routes publiques -----
@app.route('/')
def index():
    # 1) Sujets (les plus récents en premier)
    sujets = Topic.select().order_by(Topic.created_at.desc())

    # 2) Images : main + galerie (depuis static/img)
    img_dir_fs = os.path.join(app.static_folder, 'img')
    try:
        names = [n for n in os.listdir(img_dir_fs)
                 if n.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))]
    except Exception:
        names = []

    # Ordre souhaité : image_principale_ent.jpeg d'abord, puis 1..5.jpeg
    desired = ['image_principale_ent.jpeg', '1.jpeg', '2.jpeg', '3.jpeg', '4.jpeg', '5.jpeg']
    ordered = [n for n in desired if n in names] + [n for n in names if n not in desired]

    main_name = 'image_principale_ent.jpeg' if 'image_principale_ent.jpeg' in ordered else (ordered[0] if ordered else None)
    main_image_url = f'img/{main_name}' if main_name else None

    # Galerie = toutes sauf l'image principale
    gallery_urls = [f'img/{n}' for n in ordered if n != main_name]

    # 3) Rendu : on passe main_image_url & gallery_urls (utilisés dans base.html),
    #    et 'user' si tu affiches les boutons selon la session.
    return render_template(
        'forum_de_discussion.html',
        sujets=sujets,
        main_image_url=main_image_url,
        gallery_urls=gallery_urls,
        user=current_user()
    )

# app.py (dans view_topic)
# Affichage d'un sujet + arborescence des commentaires ---------------
@app.route('/sujet/<int:topic_id>')
def view_topic(topic_id):
    sujet = Topic.get_or_none(Topic.id == topic_id)
    if not sujet:
        flash("Sujet introuvable.")
        return redirect(url_for('index'))

    # Récupère tous les commentaires de ce sujet (du plus ancien au plus récent pour la lecture)
    rows = (Comment
            .select()
            .where(Comment.topic == sujet)
            .order_by(Comment.created_at.asc()))

    # Construit l'arbre en mémoire: chaque node reçoit une liste ._kids
    by_id = {c.id: c for c in rows}
    roots = []
    for c in rows:
        if not hasattr(c, '_kids'):
            c._kids = []
    for c in rows:
        if c.parent_id:
            parent = by_id.get(c.parent_id)
            if parent:
                parent._kids.append(c)
        else:
            roots.append(c)

    return render_template('sujet.html', sujet=sujet, roots=roots, user=current_user())


@app.route('/actualites')
def actualites():
    data = get_saguenay_news_daily()
    items = data.get("items", [])
    model = data.get("model", "")
    return render_template('actualites.html', items=items, model=model, user=current_user())

# “Une fois par jour” : à la première requête quotidienne, on rafraîchit via OpenAI
#  et on stocke. Les requêtes suivantes lisent le cache du jour.
#  “Même info pour tous” : tout le monde lit NewsCache → contenu identique.
#  Admin peut forcer un refresh via le bouton (utile si je veux régénérer manuellement).
@app.route('/admin/refresh_actualites', methods=['POST'])
def admin_refresh_actualites():
    r = admin_required()
    if r: return r
    # Supprime le cache pour forcer régénération au prochain accès
    NewsCache.delete().where(NewsCache.key == "saguenay_entrepreneuriat").execute()
    flash("Cache actualités supprimé. La prochaine visite va regénérer la page via OpenAI.")
    return redirect(url_for('admin_home'))

# ----- Auth -----
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        nom = (request.form.get('nom') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        pwd = request.form.get('mot_de_passe') or ''

        if not (nom and email and pwd):
            flash("Tous les champs sont requis.")
            return redirect(url_for('register'))
        if not validate_email(email):
            flash("Email invalide.")
            return redirect(url_for('register'))
        ok, msg = validate_password(pwd)
        if not ok:
            flash(msg)
            return redirect(url_for('register'))
        if User.get_or_none(User.email == email):
            flash("Cet email est déjà utilisé.")
            return redirect(url_for('register'))

        u = User.create(
            nom=nom,
            email=email,
            password_hash=generate_password_hash(pwd),
            is_admin="no"
        )
        session['uid'] = u.id
        flash("Bienvenue !")
        return redirect(url_for('index'))
    return render_template('register.html', user=current_user())

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        pwd = request.form.get('mot_de_passe') or ''
        u = User.get_or_none(User.email == email)
        if not u or not check_password_hash(u.password_hash, pwd):
            flash("Identifiants invalides.")
            return redirect(url_for('login'))
        session['uid'] = u.id
        flash("Connecté.")
        return redirect(url_for('index'))
    return render_template('login.html', user=current_user())

@app.route('/logout')
def logout():
    session.clear()
    flash("Déconnecté.")
    return redirect(url_for('index'))

# ----- Sujets: créer / éditer / supprimer -----
@app.route('/nouveau_sujet', methods=['POST'])
def nouveau_sujet():
    u = current_user()
    if not u:
        flash("Connecte-toi pour créer un sujet.")
        return redirect(url_for('login'))
    nom = request.form.get('nom') or u.nom
    titre = request.form.get('titre')
    contenu = request.form.get('contenu')
    if not (nom and titre and contenu):
        flash("Remplis les 3 champs : nom, titre, énoncé.")
        return redirect(url_for('index'))
    Topic.create(user=u, nom=nom, titre=titre, contenu=contenu)
    flash("Sujet créé !")
    return redirect(url_for('index'))

@app.route('/edit_topic/<int:topic_id>', methods=['GET','POST'])
def edit_topic(topic_id):
    t = Topic.get_or_none(Topic.id == topic_id)
    if not t:
        flash("Sujet introuvable.")
        return redirect(url_for('index'))
    if not is_owner_or_admin(t.user.id if t.user else -1):
        flash("Tu n'as pas les droits pour modifier ce sujet.")
        return redirect(url_for('view_topic', topic_id=topic_id))
    if request.method == 'POST':
        titre = request.form.get('titre','').strip()
        contenu = request.form.get('contenu','').strip()
        if not (titre and contenu):
            flash("Titre et énoncé sont requis.")
            return redirect(url_for('edit_topic', topic_id=topic_id))
        t.titre = titre
        t.contenu = contenu
        t.save()
        flash("Sujet modifié.")
        return redirect(url_for('view_topic', topic_id=topic_id))
    return render_template('edit_topic.html', sujet=t, user=current_user())

@app.route('/delete_topic/<int:topic_id>', methods=['POST'])
def delete_topic(topic_id):
    t = Topic.get_or_none(Topic.id == topic_id)
    if not t:
        flash("Sujet introuvable.")
        return redirect(url_for('index'))
    if not is_owner_or_admin(t.user.id if t.user else -1):
        flash("Tu n'as pas les droits pour supprimer ce sujet.")
        return redirect(url_for('view_topic', topic_id=topic_id))
    t.delete_instance(recursive=True)
    flash("Sujet supprimé.")
    return redirect(url_for('index'))

# ----- Commentaires / Réponses -----
# ========== Créer un commentaire (niveau 1) ==========
@app.route('/commenter/<int:topic_id>', methods=['POST'])
def commenter(topic_id):
    u = current_user()
    if not u:
        flash("Connecte-toi pour commenter.")
        return redirect(url_for('login'))

    nom = (request.form.get('nom') or u.nom).strip()
    contenu = (request.form.get('contenu') or '').strip()
    country = (request.form.get('country') or None)
    city = (request.form.get('city') or None)

    if not contenu:
        flash("Le commentaire est vide.")
        return redirect(url_for('view_topic', topic_id=topic_id))

    Comment.create(topic=topic_id, user=u, nom=nom, contenu=contenu,
                   parent=None, country=country, city=city)
    return redirect(url_for('view_topic', topic_id=topic_id))

# ========== Répondre à n'importe quel commentaire (récursif) ==========
@app.route('/repondre/<int:parent_id>', methods=['POST'])
def repondre(parent_id):
    u = current_user()
    if not u:
        flash("Connecte-toi pour répondre.")
        return redirect(url_for('login'))

    parent = Comment.get_or_none(Comment.id == parent_id)
    if not parent:
        flash("Commentaire parent introuvable.")
        return redirect(url_for('index'))

    nom = (request.form.get('nom') or u.nom).strip()
    contenu = (request.form.get('contenu') or '').strip()
    country = (request.form.get('country') or None)
    city = (request.form.get('city') or None)

    if not contenu:
        flash("La réponse est vide.")
        return redirect(url_for('view_topic', topic_id=parent.topic.id))

    Comment.create(topic=parent.topic, user=u, nom=nom, contenu=contenu,
                   parent=parent, country=country, city=city)
    return redirect(url_for('view_topic', topic_id=parent.topic.id))


# ========== Modifier / supprimer un commentaire (branche entière en cascade) ==========
@app.route('/edit_comment/<int:comment_id>', methods=['POST'])
def edit_comment(comment_id):
    c = Comment.get_or_none(Comment.id == comment_id)
    if not c:
        flash("Commentaire introuvable.")
        return redirect(url_for('index'))
    if not is_owner_or_admin(c.user.id if c.user else -1):
        flash("Tu n'as pas les droits.")
        return redirect(url_for('view_topic', topic_id=c.topic.id))

    new_text = (request.form.get('contenu') or '').strip()
    if new_text:
        c.contenu = new_text
        c.save()
        flash("Commentaire modifié.")
    return redirect(url_for('view_topic', topic_id=c.topic.id))

@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    c = Comment.get_or_none(Comment.id == comment_id)
    if not c:
        flash("Commentaire introuvable.")
        return redirect(url_for('index'))
    if not is_owner_or_admin(c.user.id if c.user else -1):
        flash("Tu n'as pas les droits.")
        return redirect(url_for('view_topic', topic_id=c.topic.id))

    topic_id = c.topic.id
    # Grâce à on_delete='CASCADE' sur parent, toute la sous-branche est supprimée
    c.delete_instance(recursive=True)
    flash("Commentaire supprimé.")
    return redirect(url_for('view_topic', topic_id=topic_id))

# ----- Admin déjà présent -----
@app.route('/admin')
def admin_home():
    r = admin_required()
    if r: return r
    sujets = Topic.select().order_by(Topic.created_at.desc())
    # Tous les commentaires, tous niveaux, récents d’abord
    comments = Comment.select().order_by(Comment.created_at.desc())
    users = User.select().order_by(User.id.desc())
    return render_template('admin.html',
                           sujets=sujets, comments=comments, users=users, user=current_user())


@app.route('/admin/delete_topic/<int:topic_id>', methods=['POST'])
def admin_delete_topic(topic_id):
    r = admin_required()
    if r: return r
    t = Topic.get_or_none(Topic.id == topic_id)
    if t:
        t.delete_instance(recursive=True)
        flash("Sujet supprimé (admin).")
    return redirect(url_for('admin_home'))


@app.route('/admin/delete_comment/<int:comment_id>', methods=['POST'])
def admin_delete_comment(comment_id):
    r = admin_required()
    if r: return r
    c = Comment.get_or_none(Comment.id == comment_id)
    if c:
        # Cascade sur toute la sous-branche grâce à parent on_delete='CASCADE'
        c.delete_instance(recursive=True)
        flash("Commentaire supprimé (admin).")
    return redirect(url_for('admin_home'))

# ----- Reset mot de passe -----
@app.route('/reset_password', methods=['GET','POST'])
def reset_password_request():
    # Formulaire: saisir son email -> on génère un lien avec token (dev: on l'affiche)
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if not validate_email(email):
            flash("Email invalide.")
            return redirect(url_for('reset_password_request'))
        u = User.get_or_none(User.email == email)
        if not u:
            flash("Si cet email existe, un lien de réinitialisation sera envoyé.")
            return redirect(url_for('login'))
        token = ts().dumps({"uid": u.id, "email": u.email})
        reset_url = url_for('reset_password_token', token=token, _external=True)
        # DEV: on affiche le lien pour test local; en prod, on envoie par email.
        flash("Lien de réinitialisation généré (dev). Copie-colle:")
        flash(reset_url)
        return redirect(url_for('login'))
    return render_template('reset_password_request.html', user=current_user())

@app.route('/reset_password/<token>', methods=['GET','POST'])
def reset_password_token(token):
    try:
        data = ts().loads(token, max_age=3600)  # 1h
    except SignatureExpired:
        flash("Lien expiré. Recommence la procédure.")
        return redirect(url_for('reset_password_request'))
    except BadSignature:
        flash("Lien invalide.")
        return redirect(url_for('reset_password_request'))

    u = User.get_or_none(User.id == data.get("uid"))
    if not u or u.email != data.get("email"):
        flash("Jeton non valide.")
        return redirect(url_for('reset_password_request'))

    if request.method == 'POST':
        p1 = request.form.get('password') or ''
        p2 = request.form.get('password2') or ''
        if p1 != p2:
            flash("Les mots de passe ne correspondent pas.")
            return redirect(url_for('reset_password_token', token=token))
        ok, msg = validate_password(p1)
        if not ok:
            flash(msg)
            return redirect(url_for('reset_password_token', token=token))
        u.password_hash = generate_password_hash(p1)
        u.save()
        flash("Mot de passe mis à jour. Tu peux te connecter.")
        return redirect(url_for('login'))

    return render_template('reset_password_form.html', token=token, user=current_user())

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
