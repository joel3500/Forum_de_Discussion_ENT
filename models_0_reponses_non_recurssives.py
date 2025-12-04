# models.py
# models.py
import os
from peewee import (
    Model, CharField, TextField, DateTimeField, ForeignKeyField,
    SqliteDatabase
)
from datetime import datetime, timezone
from playhouse.db_url import connect

def now_utc_naive():
    # Datetime aware en UTC → converti en naïf (UTC) pour stockage Peewee
    return datetime.now(timezone.utc).replace(tzinfo=None)


DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    try:
        db = connect(DATABASE_URL)
        db.connect(reuse_if_open=True)
    except Exception as e:
        print("Postgres unavailable, fallback to SQLite:", e)
        db = SqliteDatabase('forum.sqlite', pragmas={'journal_mode': 'wal'})
else:
    db = SqliteDatabase('forum.sqlite', pragmas={'journal_mode': 'wal'})

class BaseModel(Model):
    class Meta:
        database = db

class User(BaseModel):
    nom = CharField()
    email = CharField(unique=True)
    password_hash = CharField()
    is_admin = CharField(default="no")  # "yes" ou "no" (simple)

class Topic(BaseModel):
    user = ForeignKeyField(User, backref='topics', null=True, on_delete='SET NULL')
    nom = CharField()         # affichage pour rétro-compat
    titre = CharField()
    contenu = TextField()
    created_at = DateTimeField(default=now_utc_naive)

class Comment(BaseModel):
    topic = ForeignKeyField(Topic, backref='comments', on_delete='CASCADE')
    user = ForeignKeyField(User, backref='comments', null=True, on_delete='SET NULL')
    nom = CharField()
    contenu = TextField()
    created_at = DateTimeField(default=now_utc_naive)
    country = CharField(null=True)
    city = CharField(null=True)

class Reply(BaseModel):
    comment = ForeignKeyField(Comment, backref='replies', on_delete='CASCADE')
    user = ForeignKeyField(User, backref='replies', null=True, on_delete='SET NULL')
    nom = CharField()
    contenu = TextField()
    created_at = DateTimeField(default=now_utc_naive)
    country = CharField(null=True)
    city = CharField(null=True)

def initialize():
    with db:
        db.create_tables([User, Topic, Comment, Reply, NewsCache])

class NewsCache(BaseModel):
    key = CharField(unique=True)          # ex: "saguenay_entrepreneuriat"
    payload = TextField(null=True)                  # dict: {"items":[...], "model":"...", "fetched_at":"..."}
    fetched_at = DateTimeField(default=now_utc_naive)

