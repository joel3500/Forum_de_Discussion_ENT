
# models.py
import os
from datetime import datetime, timezone
from peewee import (
    Model, CharField, TextField, DateTimeField, ForeignKeyField,
    SqliteDatabase
)
from playhouse.db_url import connect

# ---------- Connexion DB : Postgres si DATABASE_URL, sinon SQLite ----------
DATABASE_URL = os.environ.get("DATABASE_URL")

def _sqlite():
    # foreign_keys=1 pour activer CASCADE en SQLite
    return SqliteDatabase(
        'forum.sqlite',
        pragmas={
            'journal_mode': 'wal',
            'foreign_keys': 1
        }
    )

if DATABASE_URL:
    try:
        db = connect(DATABASE_URL)
        db.connect(reuse_if_open=True)
    except Exception as e:
        print("Postgres indisponible, fallback SQLite:", e)
        db = _sqlite()
else:
    db = _sqlite()

# ---------- Helpers temps (UTC aware → naïf pour Peewee) ----------
def now_utc_naive():
    # Datetime aware UTC → stocké en naïf UTC (compatible Peewee/SQLite)
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ---------- Base ----------
class BaseModel(Model):
    class Meta:
        database = db

# ---------- Utilisateur ----------
class User(BaseModel):
    nom = CharField()
    email = CharField(unique=True)          # unicité en DB
    password_hash = CharField()
    is_admin = CharField(default="no")      # "yes" / "no" simple

# ---------- Sujet ----------
class Topic(BaseModel):
    user = ForeignKeyField(User, backref='topics', null=True, on_delete='SET NULL')
    nom = CharField()                        # affichage rétro-compat
    titre = CharField()
    contenu = TextField()
    created_at = DateTimeField(default=now_utc_naive)

# ---------- Commentaire récursif (commentaire & réponse = même table) ----------
class Comment(BaseModel):
    topic   = ForeignKeyField(Topic, backref='comments', on_delete='CASCADE')
    user    = ForeignKeyField(User, backref='comments', null=True, on_delete='SET NULL')
    nom     = CharField()
    contenu = TextField()

    # parent == NULL  → commentaire de 1er niveau
    # parent == id    → réponse à un commentaire (profondeur illimitée)
    parent  = ForeignKeyField('self', null=True, backref='children', on_delete='CASCADE')

    country = CharField(null=True)
    city    = CharField(null=True)
    created_at = DateTimeField(default=now_utc_naive)

# ---------- Cache Actualités (payload JSON sérialisé en texte) ----------
class NewsCache(BaseModel):
    key = CharField(unique=True)             # ex: "saguenay_entrepreneuriat"
    payload = TextField(null=True)           # JSON string (json.dumps / json.loads dans app.py)
    fetched_at = DateTimeField(default=now_utc_naive)

# ---------- Init ----------
def initialize():
    with db:
        db.create_tables([User, Topic, Comment, NewsCache])
