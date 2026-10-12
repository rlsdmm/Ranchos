"""
Ranchos — agregador de ranchos para temporada.

Público:  lista com filtros, página de cada rancho, botão de WhatsApp com contagem
          de cliques, página "Anuncie seu rancho", sitemap/robots para o Google.
Admin:    /admin — cadastro de ranchos, fotos, destaque/verificado, pedidos de
          anúncio e relatório mensal por rancho (pronto para mandar ao dono).
Donos:    contas criadas pelo admin em /admin/donos. O dono entra no mesmo /admin/login
          (login + senha) e só vê e edita os próprios ranchos; rancho novo dele fica
          pendente até o admin aprovar. Verificado/destaque continuam só com o admin.

Banco:    DATABASE_URL (Postgres em produção). Sem ela, usa SQLite local.
Fotos:    com BUNNY_STORAGE_URL/BUNNY_STORAGE_KEY/BUNNY_CDN_URL vão para o Bunny
          Storage e são servidas pela CDN do Bunny. Sem elas, ficam no próprio banco.
"""
import hashlib
import hmac
import io
import os
import re
import random
import secrets
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import calendar as calmod
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from urllib.parse import quote, unquote, urlparse
from zoneinfo import ZoneInfo

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from PIL import Image, ImageOps
from sqlalchemy import exc, func
from sqlalchemy.orm import deferred
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SITE_NAME = os.environ.get("SITE_NAME", "Ranchos da Cidade")
CITY_NAME = os.environ.get("CITY_NAME", "Sua Cidade")
SITE_WHATSAPP = re.sub(r"\D", "", os.environ.get("SITE_WHATSAPP", ""))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
# Bunny Storage: ex. https://br.storage.bunnycdn.com/zona  +  https://zona.b-cdn.net
BUNNY_STORAGE_URL = os.environ.get("BUNNY_STORAGE_URL", "").rstrip("/")
BUNNY_STORAGE_KEY = os.environ.get("BUNNY_STORAGE_KEY", "")
BUNNY_CDN_URL = os.environ.get("BUNNY_CDN_URL", "").rstrip("/")
BUNNY_ON = bool(BUNNY_STORAGE_URL and BUNNY_STORAGE_KEY and BUNNY_CDN_URL)
BUNNY_PREFIX = "ranchos"  # pasta dentro da zona, que é compartilhada com outros arquivos

db_url = os.environ.get("DATABASE_URL", "sqlite:///ranchos.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

app = Flask(__name__)
app.config.update(
    # SECRET_KEY fixa é importante: com vários workers, uma chave aleatória derrubaria o login.
    SECRET_KEY=os.environ.get("SECRET_KEY")
    or hashlib.sha256(f"ranchos|{os.environ.get('ADMIN_PASSWORD', '')}|{db_url}".encode()).hexdigest(),
    SQLALCHEMY_DATABASE_URI=db_url,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    MAX_CONTENT_LENGTH=60 * 1024 * 1024,  # uploads de até 60 MB por envio
    # O Firebase Hosting (na frente do Cloud Run) descarta todo cookie que não se chame __session.
    SESSION_COOKIE_NAME="__session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") != "development" and bool(BASE_URL.startswith("https")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # o servidor fica atrás de proxy
db = SQLAlchemy(app)

# Comodidades: chave -> (rótulo, ícone)
AMENITIES = {
    "piscina": ("Piscina", "🏊"),
    "beira_rio": ("Beira-rio", "🌊"),
    "rampa": ("Rampa para barco", "🚤"),
    "pesca": ("Bom para pesca", "🎣"),
    "churrasqueira": ("Churrasqueira", "🔥"),
    "area_gourmet": ("Área gourmet", "🍽️"),
    "ar": ("Ar-condicionado", "❄️"),
    "wifi": ("Wi-Fi", "📶"),
    "pet": ("Aceita pet", "🐶"),
    "estacionamento": ("Estacionamento", "🚗"),
    "som": ("Pode som", "🔊"),
    "roupa_cama": ("Roupa de cama inclusa", "🛏️"),
    "beach_tennis": ("Quadra de beach tennis", "🎾"),
    "parquinho": ("Parquinho infantil", "🎠"),
    "futebol": ("Campo de futebol", "⚽"),
    "sinuca": ("Mesa de sinuca", "🎱"),
    "bebedouro": ("Bebedouro", "🚰"),
}
# Serviços que os profissionais anunciam (página /servicos e bloco na página do rancho)
SERVICES = {
    "cozinheira": ("Cozinheira", "👩‍🍳"),
    "churrasqueiro": ("Churrasqueiro", "🍖"),
    "confeitaria": ("Confeitaria", "🎂"),
    "faxina": ("Faxina", "🧹"),
    "roupa_cama": ("Aluguel de roupa de cama", "🛏️"),
}

# Comodidades que viram filtro na página inicial e linha na comparação da lista
FILTER_AMENITIES = ["beira_rio", "piscina", "rampa", "pesca", "area_gourmet", "ar", "pet", "wifi",
                    "beach_tennis", "parquinho", "futebol"]

# Páginas por tipo de rancho (/ranchos/<slug>), feitas para as buscas do Google.
# "amenity" filtra pela comodidade; "min_cap" pela quantidade de pessoas.
CATEGORIES = {
    "com-piscina": dict(
        label="Com piscina", amenity="piscina", title="Ranchos com piscina",
        intro="Ranchos com piscina para alugar em {city}, para a turma aproveitar o sol sem sair do rancho. "
              "Veja as fotos, quantas pessoas cabem e o valor do fim de semana, e combine direto com o dono pelo WhatsApp."),
    "beira-rio": dict(
        label="Na beira do rio", amenity="beira_rio", title="Ranchos na beira do rio",
        intro="Ranchos na beira d'água em {city}, para acordar com vista para o rio, nadar e ver o pôr do sol. "
              "Compare os ranchos e fale direto com o dono pelo WhatsApp."),
    "para-pesca": dict(
        label="Para pesca", amenity="pesca", title="Ranchos para pescaria",
        h1="Ranchos para pescaria em {city}", seo_title="Ranchos para pescaria em {city}: píer, rampa e beira-rio",
        intro="Ranchos bons para pescaria em {city}. Antes de ir, confira as regras de pesca e os períodos de "
              "defeso da região. Veja fotos, estrutura e o valor do fim de semana de cada rancho."),
    "com-rampa-para-barco": dict(
        label="Com rampa para barco", amenity="rampa", title="Ranchos com rampa para barco",
        intro="Ranchos em {city} com rampa para colocar o barco ou o jet ski na água. "
              "Veja fotos e detalhes e combine datas direto com o dono."),
    "que-aceitam-pet": dict(
        label="Aceitam pet", amenity="pet", title="Ranchos que aceitam pet",
        intro="Ranchos em {city} que aceitam animais de estimação, para o cachorro também curtir o fim de semana. "
              "Avise o dono antes sobre o seu pet."),
    "com-area-gourmet": dict(
        label="Com área gourmet", amenity="area_gourmet", title="Ranchos com área gourmet",
        intro="Ranchos em {city} com área gourmet para o churrasco e os almoços em grupo. "
              "Veja fotos, estrutura e o valor do fim de semana."),
    "com-quadra-de-beach-tennis": dict(
        label="Com beach tennis", amenity="beach_tennis", title="Ranchos com quadra de beach tennis",
        intro="Ranchos em {city} com quadra de beach tennis, para jogar com a turma entre um mergulho e outro. "
              "Veja fotos e o valor do fim de semana e fale direto com o dono."),
    "com-parquinho": dict(
        label="Com parquinho", amenity="parquinho", title="Ranchos com parquinho infantil",
        intro="Ranchos em {city} com parquinho, para as crianças se divertirem enquanto os adultos descansam. "
              "Confira a estrutura de cada um e combine direto com o dono pelo WhatsApp."),
    "com-campo-de-futebol": dict(
        label="Com campo de futebol", amenity="futebol", title="Ranchos com campo de futebol",
        intro="Ranchos em {city} com campo de futebol para aquela pelada com os amigos. "
              "Veja fotos, quantas pessoas cabem e o valor do fim de semana."),
    "com-mesa-de-sinuca": dict(
        label="Com sinuca", amenity="sinuca", title="Ranchos com mesa de sinuca",
        intro="Ranchos em {city} com mesa de sinuca, para a turma jogar à noite ou nos dias de chuva. "
              "Veja fotos, estrutura e o valor do fim de semana e combine direto com o dono pelo WhatsApp."),
    "para-grupos-grandes": dict(
        label="Para 20 pessoas ou mais", min_cap=20, title="Ranchos para grupos grandes",
        intro="Ranchos em {city} que recebem 20 pessoas ou mais, para família grande, aniversário ou a turma toda. "
              "Confira quartos, camas e o valor do fim de semana de cada um."),
}
LIST_MAX = 12  # ranchos numa lista para o grupo
NEW_DAYS = 30           # selo "Novo" nos ranchos que entraram há menos tempo que isso...
NEW_MAX = 3             # ...mas só nos mais recentes: com o site começando, todos seriam novos
FRESH_AGENDA_DAYS = 30  # agenda mais velha que isso não aparece como "atualizada" no card

# Cobrança dos donos: meses grátis no começo, depois mensal ou anual.
TRIAL_MONTHS = 3
PRICE_MONTH = "R$ 19,90"
PRICE_YEAR = "R$ 200"
BILLING_NOTICE_DAYS = 7  # o rancho entra na lista de cobrança do painel essa quantidade de dias antes de vencer
PIX_KEY = os.environ.get("PIX_KEY", "")  # vai na mensagem de cobrança; vazio = mensagem sem Pix
ICAL_SYNC_HOURS = 2  # agenda externa (Google Agenda, Airbnb...) é copiada de novo depois desse tempo

BOT_RE = re.compile(r"bot|crawl|spider|slurp|facebookexternalhit|whatsapp|preview|curl|wget|python", re.I)


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Rancho(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    region = db.Column(db.String(120), default="")          # bairro / condomínio / estrada
    summary = db.Column(db.String(200), default="")         # frase curta para o card
    description = db.Column(db.Text, default="")
    capacity = db.Column(db.Integer, default=0)
    bedrooms = db.Column(db.Integer, default=0)
    bathrooms = db.Column(db.Integer, default=0)
    beds = db.Column(db.String(160), default="")            # ex.: "3 casal, 6 solteiro"
    internet = db.Column(db.String(120), default="")        # ex.: "Fibra 150 Mbps, Wi-Fi 6"
    fridges = db.Column(db.Integer, default=0)              # geladeiras
    freezers = db.Column(db.Integer, default=0)
    beer_fridges = db.Column(db.Integer, default=0)         # cervejeiras
    price_night = db.Column(db.Integer, default=0)          # R$ por diária
    price_weekend = db.Column(db.Integer, default=0)        # R$ pacote fim de semana
    price_holiday = db.Column(db.String(160), default="")   # texto livre
    min_nights = db.Column(db.Integer, default=1)
    checkin = db.Column(db.String(20), default="")
    checkout = db.Column(db.String(20), default="")
    rules = db.Column(db.Text, default="")
    amenities = db.Column(db.String(400), default="")       # chaves separadas por vírgula
    maps_url = db.Column(db.String(500), default="")
    owner_name = db.Column(db.String(120), default="")
    owner_whatsapp = db.Column(db.String(30), default="")
    verified = db.Column(db.Boolean, default=False)
    verified_at = db.Column(db.DateTime)  # quando o selo foi dado (visita da equipe)
    featured = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    # Conta de dono que pode editar o rancho. Rancho cadastrado pelo dono fica pendente
    # (fora do site) até o administrador aprovar.
    owner_id = db.Column(db.Integer, db.ForeignKey("owner.id", ondelete="SET NULL"), index=True)
    pending = db.Column(db.Boolean, default=False)
    # Última vez que a agenda foi mexida. Vazio = rancho sem agenda (não mostra no site).
    calendar_updated_at = db.Column(db.DateTime)
    # Até quando o anúncio está pago (ou no período grátis). Vazio = sem cobrança registrada.
    paid_until = db.Column(db.Date)
    # Agenda externa do dono (.ics do Google Agenda, Airbnb, Booking). Preenchida = a agenda daqui
    # é cópia dela e não se edita no painel.
    ical_url = db.Column(db.String(500), default="")
    ical_synced_at = db.Column(db.DateTime)
    ical_error = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=now_utc)
    updated_at = db.Column(db.DateTime, default=now_utc, onupdate=now_utc)

    photos = db.relationship("Photo", backref="rancho", cascade="all, delete-orphan",
                             order_by="Photo.position")
    busy_days = db.relationship("BusyDay", cascade="all, delete-orphan", lazy="dynamic")

    @property
    def public(self):
        return bool(self.active and not self.pending)

    @property
    def amenity_list(self):
        return [a for a in (self.amenities or "").split(",") if a in AMENITIES]

    @property
    def cover(self):
        return self.photos[0] if self.photos else None

    @property
    def whatsapp_digits(self):
        d = re.sub(r"\D", "", self.owner_whatsapp or "")
        if d and not d.startswith("55"):
            d = "55" + d
        return d

    @property
    def coords(self):
        """"lat,lng" tirado do link do Google Maps, para o botão do Waze. None quando o link
        não traz coordenadas (link curto maps.app.goo.gl ou só o código do lugar)."""
        u = unquote(self.maps_url or "")
        num = r"(-?\d{1,2}\.\d{3,})"
        for pat in (r"!3d" + num + r"!4d" + num,                          # alfinete do lugar
                    r"[?&](?:q|ll|query|destination)=" + num + r",\s*" + num,
                    r"@" + num + r"," + num):                             # centro do mapa
            m = re.search(pat, u)
            if m and abs(float(m.group(1))) <= 90 and abs(float(m.group(2))) <= 180:
                return f"{m.group(1)},{m.group(2)}"
        return None

    @property
    def is_new(self):
        return self.id in new_rancho_ids()

    @property
    def agenda_fresh(self):
        """Agenda mexida há pouco. Data velha no card passaria a impressão contrária."""
        return bool(self.calendar_updated_at
                    and now_utc() - self.calendar_updated_at < timedelta(days=FRESH_AGENDA_DAYS))


class Owner(db.Model):
    """Conta de dono de rancho. O administrador cria com uma senha provisória, que o dono
    é obrigado a trocar no primeiro acesso."""
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(120), unique=True, nullable=False, index=True)  # e-mail ou usuário, minúsculo
    name = db.Column(db.String(120), default="")
    password_hash = db.Column(db.String(255), nullable=False)
    must_change = db.Column(db.Boolean, default=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=now_utc)
    last_login = db.Column(db.DateTime)

    ranchos = db.relationship("Rancho", backref="owner", order_by="Rancho.name")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class BusyDay(db.Model):
    """Dia em que o rancho está alugado (agenda). Uma linha por dia ocupado."""
    __tablename__ = "busy_day"
    __table_args__ = (db.UniqueConstraint("rancho_id", "day"),)
    id = db.Column(db.Integer, primary_key=True)
    rancho_id = db.Column(db.Integer, db.ForeignKey("rancho.id", ondelete="CASCADE"), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False)


class LoginThrottle(db.Model):
    """Senhas erradas por conta. Fica no banco (e não na memória) porque o site roda em
    várias instâncias e workers ao mesmo tempo."""
    key = db.Column(db.String(160), primary_key=True)  # "admin" ou "owner:<login>"
    failures = db.Column(db.Integer, default=0)
    window_start = db.Column(db.DateTime, default=now_utc)
    locked_until = db.Column(db.DateTime)


class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rancho_id = db.Column(db.Integer, db.ForeignKey("rancho.id"), nullable=False, index=True)
    position = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)
    etag = db.Column(db.String(40), default="")
    # Caminho no Bunny sem o sufixo (-f.webp / -t.webp). Vazio = a foto está nas colunas abaixo,
    # que então ficam com b"" (não dá para tirar o NOT NULL no SQLite sem recriar a tabela).
    cdn_key = db.Column(db.String(120), default="")
    full = deferred(db.Column(db.LargeBinary, nullable=False))
    thumb = deferred(db.Column(db.LargeBinary, nullable=False))

    def url(self, s="f", absolute=False):
        if self.cdn_key:
            return f"{BUNNY_CDN_URL}/{self.cdn_key}-{s}.webp"
        path = url_for("image", pid=self.id, s="t" if s == "t" else None)
        return site_url() + path if absolute else path


class Provider(db.Model):
    """Profissional que atende nos ranchos (cozinheira, faxina...). O turista fala direto com ela."""
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    services = db.Column(db.String(200), default="")      # chaves de SERVICES separadas por vírgula
    summary = db.Column(db.String(200), default="")       # frase curta do card
    description = db.Column(db.Text, default="")
    price_text = db.Column(db.String(160), default="")    # vazio = a combinar
    whatsapp = db.Column(db.String(30), default="")
    active = db.Column(db.Boolean, default=True)
    paid_until = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=now_utc)
    updated_at = db.Column(db.DateTime, default=now_utc, onupdate=now_utc)
    photos = db.relationship("ProviderPhoto", order_by="ProviderPhoto.position",
                             cascade="all, delete-orphan", lazy="selectin")

    @property
    def service_list(self):
        return [k for k in (self.services or "").split(",") if k in SERVICES]

    @property
    def whatsapp_digits(self):
        d = re.sub(r"\D", "", self.whatsapp or "")
        return "55" + d if d and not d.startswith("55") else d

    @property
    def cover(self):
        return self.photos[0] if self.photos else None


class ProviderPhoto(db.Model):
    """Mesmo esquema de Photo (WebP no Bunny ou no banco); a primeira é a foto do card."""
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("provider.id"), nullable=False, index=True)
    position = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)
    etag = db.Column(db.String(40), default="")
    cdn_key = db.Column(db.String(120), default="")
    full = deferred(db.Column(db.LargeBinary, nullable=False))
    thumb = deferred(db.Column(db.LargeBinary, nullable=False))

    def url(self, s="f", absolute=False):
        if self.cdn_key:
            return f"{BUNNY_CDN_URL}/{self.cdn_key}-{s}.webp"
        path = url_for("provider_image", pid=self.id, s="t" if s == "t" else None)
        return site_url() + path if absolute else path


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rancho_id = db.Column(db.Integer, db.ForeignKey("rancho.id", ondelete="CASCADE"), index=True)
    # Clique no WhatsApp de um profissional (kind "prestador")
    provider_id = db.Column(db.Integer, db.ForeignKey("provider.id", ondelete="CASCADE"), index=True)
    # visit (chegada ao site, sem rancho) | view | whatsapp | servico | fav (♥ na lista)
    kind = db.Column(db.String(20), nullable=False)
    source = db.Column(db.String(40), default="")  # de onde veio: instagram, google, google-ads, direto...
    created_at = db.Column(db.DateTime, default=now_utc, index=True)


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    rancho_name = db.Column(db.String(160))
    region = db.Column(db.String(160))
    message = db.Column(db.Text)
    handled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=now_utc)


with app.app_context():
    try:
        db.create_all()
    except exc.DatabaseError:
        # Os workers do gunicorn sobem juntos; se outro criou as tabelas no mesmo instante, tenta de novo.
        db.session.rollback()
        time.sleep(1)
        db.create_all()
    # create_all não acrescenta coluna em tabela que já existe.
    for table, column, ddl in [
        ("photo", "cdn_key", "VARCHAR(120) DEFAULT ''"),
        ("rancho", "owner_id", "INTEGER REFERENCES owner(id) ON DELETE SET NULL"),
        ("rancho", "pending", "BOOLEAN DEFAULT FALSE"),
        ("rancho", "internet", "VARCHAR(120) DEFAULT ''"),
        ("rancho", "fridges", "INTEGER DEFAULT 0"),
        ("rancho", "freezers", "INTEGER DEFAULT 0"),
        ("rancho", "beer_fridges", "INTEGER DEFAULT 0"),
        ("event", "source", "VARCHAR(40) DEFAULT ''"),
        ("rancho", "calendar_updated_at", "TIMESTAMP"),
        ("rancho", "paid_until", "DATE"),
        ("rancho", "ical_url", "VARCHAR(500) DEFAULT ''"),
        ("rancho", "ical_synced_at", "TIMESTAMP"),
        ("rancho", "ical_error", "VARCHAR(200) DEFAULT ''"),
        ("event", "provider_id", "INTEGER REFERENCES provider(id) ON DELETE CASCADE"),
        ("rancho", "verified_at", "TIMESTAMP"),
    ]:
        if column not in {c["name"] for c in db.inspect(db.engine).get_columns(table)}:
            try:
                with db.engine.begin() as conn:
                    conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            except exc.DatabaseError:  # outro worker acrescentou ao mesmo tempo
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "rancho"


def unique_slug(name, exclude_id=None, model=None):
    model = model or Rancho
    base = slugify(name)[:100]
    slug, n = base, 2
    while True:
        q = model.query.filter_by(slug=slug)
        if exclude_id:
            q = q.filter(model.id != exclude_id)
        if not q.first():
            return slug
        slug = f"{base}-{n}"
        n += 1


def to_int(v, default=0):
    try:
        return max(0, int(re.sub(r"[^\d]", "", str(v)) or default))
    except ValueError:
        return default


def brl(v):
    return "R$ " + f"{int(v):,}".replace(",", ".")


def process_image(file_storage):
    """Returns (full_webp, thumb_webp, w, h) or None if not an image."""
    try:
        img = Image.open(file_storage.stream)
        # JPEG: decodifica já reduzido (1/2, 1/4...) em vez dos 12 MP inteiros. Bem mais rápido
        # e leve, o que importa no plano grátis do Render (0,1 CPU e 512 MB).
        w, h = img.size
        scale = 1800 / max(w, h)
        if scale < 1:
            img.draft("RGB", (int(w * scale), int(h * scale)))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return None
    full = img
    full.thumbnail((1800, 1800), Image.LANCZOS, reducing_gap=3.0)
    thumb = full.copy()
    thumb.thumbnail((720, 720), Image.LANCZOS, reducing_gap=3.0)
    b1, b2 = io.BytesIO(), io.BytesIO()
    # method=2: ~3x mais rápido que o 4 e só ~4% maior
    full.save(b1, "WEBP", quality=80, method=2)
    thumb.save(b2, "WEBP", quality=76, method=2)
    return b1.getvalue(), b2.getvalue(), full.width, full.height


def bunny_request(method, path, data=None):
    req = urllib.request.Request(f"{BUNNY_STORAGE_URL}/{path}", data=data, method=method,
                                 headers={"AccessKey": BUNNY_STORAGE_KEY,
                                          "Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status


def bunny_upload(key, full, thumb):
    """Envia as duas versões juntas (metade do tempo de espera)."""
    with ThreadPoolExecutor(2) as ex:
        for f in [ex.submit(bunny_request, "PUT", f"{key}-f.webp", full),
                  ex.submit(bunny_request, "PUT", f"{key}-t.webp", thumb)]:
            f.result()


def bunny_delete(keys):
    """Apaga do Bunny depois do commit. Se falhar, sobra só um arquivo órfão; não trava o painel."""
    paths = [f"{k}-{s}.webp" for k in keys if k for s in "ft"]
    if not paths:
        return
    def rm(p):
        try:
            bunny_request("DELETE", p)
        except Exception as e:
            app.logger.warning("Bunny: não apagou %s (%s)", p, e)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(rm, paths))


def site_url():
    return BASE_URL or request.url_root.rstrip("/")


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(24)
    return session["_csrf"]


def check_csrf():
    sent = request.form.get("_csrf", "")
    if not sent or not hmac.compare_digest(sent, session.get("_csrf", "")):
        abort(400, "Formulário expirado. Volte, recarregue a página e tente de novo.")


def is_admin():
    return bool(session.get("admin"))


def current_owner():
    """Dono logado (ou None). Conta desativada ou apagada derruba a sessão na hora."""
    if "owner" not in g:
        oid = session.get("owner_id")
        o = db.session.get(Owner, oid) if oid else None
        g.owner = o if o and o.active else None
    return g.owner


def admin_required(f):
    """Só o administrador."""
    @wraps(f)
    def wrapper(*a, **kw):
        if not is_admin():
            if current_owner():
                abort(403)
            return redirect(url_for("admin_login", next=request.path))
        if request.method == "POST":
            check_csrf()
        return f(*a, **kw)
    return wrapper


def panel_required(f):
    """Administrador ou dono. O dono com senha provisória só entra depois de trocá-la."""
    @wraps(f)
    def wrapper(*a, **kw):
        owner = current_owner()
        if not is_admin() and not owner:
            return redirect(url_for("admin_login", next=request.path))
        if owner and owner.must_change and request.endpoint not in ("owner_password", "admin_logout"):
            return redirect(url_for("owner_password"))
        if request.method == "POST":
            check_csrf()
        return f(*a, **kw)
    return wrapper


def editable_rancho(rid):
    """Rancho que quem está logado pode mexer. Para o dono, rancho de outra conta é 404
    (nem confirma que existe)."""
    r = db.session.get(Rancho, rid)
    if not r or not (is_admin() or (current_owner() and r.owner_id == current_owner().id)):
        abort(404)
    return r


def public_ranchos():
    return Rancho.query.filter(Rancho.active.is_(True), Rancho.pending.isnot(True))


def set_verified(r, on):
    """Liga ou desliga o selo. A data da visita aparece no anúncio."""
    if on and not r.verified:
        r.verified_at = now_utc()
    elif not on:
        r.verified_at = None
    r.verified = on


def new_rancho_ids():
    """Ids com selo "Novo". Calculado uma vez por requisição."""
    if "new_ids" not in g:
        since = now_utc() - timedelta(days=NEW_DAYS)
        q = (public_ranchos().filter(Rancho.created_at >= since)
             .order_by(Rancho.created_at.desc()).with_entities(Rancho.id).limit(NEW_MAX))
        g.new_ids = {rid for (rid,) in q}
    return g.new_ids


def default_order(ranchos):
    return sorted(ranchos, key=lambda r: (not r.featured, not r.verified, -(r.updated_at or now_utc()).timestamp()))


def in_category(r, cat):
    if cat.get("amenity") and cat["amenity"] not in r.amenity_list:
        return False
    return (r.capacity or 0) >= cat.get("min_cap", 0)


def categories_with_ranchos(ranchos=None):
    """[(slug, categoria, quantidade)] só dos tipos que têm rancho: página vazia não ajuda no Google."""
    ranchos = public_ranchos().all() if ranchos is None else ranchos
    out = []
    for slug, cat in CATEGORIES.items():
        n = sum(1 for r in ranchos if in_category(r, cat))
        if n:
            out.append((slug, cat, n))
    return out


def log_event(rancho_id, kind, provider_id=None):
    if is_admin() or current_owner() or BOT_RE.search(request.headers.get("User-Agent", "")):
        return
    db.session.add(Event(rancho_id=rancho_id, provider_id=provider_id, kind=kind,
                         source=session.get("src", "direto")))
    db.session.commit()


# ---------------------------------------------------------------------------
# Origem das visitas
# ---------------------------------------------------------------------------
# Páginas onde o turista pode "chegar" ao site (as outras rotas não definem a origem).
LANDING_ENDPOINTS = {"index", "rancho", "category", "group_list", "anuncie", "services", "about", "safety_guide"}
# Site de onde veio (pelo Referer) -> nome da origem
REFERRER_SOURCES = [
    (re.compile(r"(^|\.)instagram\.com$"), "instagram"),
    (re.compile(r"(^|\.)(facebook\.com|fb\.com|fb\.me)$"), "facebook"),
    (re.compile(r"(^|\.)google\.[a-z.]+$"), "google"),
    (re.compile(r"(^|\.)(bing\.com|yahoo\.com|duckduckgo\.com)$"), "outros-buscadores"),
    (re.compile(r"(^|\.)(whatsapp\.com|wa\.me)$"), "whatsapp"),
    (re.compile(r"(^|\.)(youtube\.com|youtu\.be)$"), "youtube"),
    (re.compile(r"(^|\.)(tiktok\.com)$"), "tiktok"),
]
SOURCE_LABELS = {
    "direto": "Direto (link no WhatsApp, digitado ou app)",
    "google": "Google (busca)",
    "google-ads": "Google Ads (anúncio)",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "meta": "Instagram/Facebook (link com fbclid)",
    "whatsapp": "WhatsApp Web",
    "outros-buscadores": "Outros buscadores",
}


def clean_source(v):
    return re.sub(r"[^a-z0-9_-]+", "-", (v or "").strip().lower()).strip("-")[:40]


def detect_source():
    """Etiqueta do link > marca de anúncio > site de onde veio > direto."""
    args = request.args
    if args.get("utm_source"):
        return clean_source(args["utm_source"]) or "direto"
    if args.get("gclid") or args.get("gbraid") or args.get("wbraid"):
        return "google-ads"
    ref_host = urlparse(request.headers.get("Referer", "")).netloc.lower().split(":")[0]
    if ref_host and ref_host != request.host.split(":")[0]:
        for pattern, name in REFERRER_SOURCES:
            if pattern.search(ref_host):
                return name
        if args.get("fbclid"):
            return "meta"
        return clean_source(ref_host.removeprefix("www."))  # outro site qualquer: guarda o domínio
    if args.get("fbclid"):
        return "meta"
    return "direto"


@app.before_request
def track_source():
    """Guarda a origem na sessão na chegada ao site e conta um "visitante" por sessão.
    Um link com etiqueta ou de anúncio clicado depois troca a origem (vale o último anúncio)."""
    if request.method != "GET" or request.endpoint not in LANDING_ENDPOINTS:
        return
    if CANONICAL_HOST and request.host != CANONICAL_HOST:  # *.web.app / *.run.app não entram na conta
        return
    tagged = any(request.args.get(k) for k in ("utm_source", "gclid", "gbraid", "wbraid", "fbclid"))
    if "src" in session and not tagged:
        return
    new = detect_source()
    if session.get("src") != new:
        session["src"] = new
        log_event(None, "visit")


def month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(dt, n):
    y, m = dt.year + (dt.month - 1 + n) // 12, (dt.month - 1 + n) % 12 + 1
    return dt.replace(year=y, month=m)


def months_later(d, n):
    """Mesmo dia n meses depois; 31/01 + 1 mês = 28 ou 29/02."""
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return date(y, m, min(d.day, calmod.monthrange(y, m)[1]))


MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]


# ---------------------------------------------------------------------------
# Agenda
# ---------------------------------------------------------------------------
CALENDAR_MONTHS = 12  # meses que a agenda mostra, a partir do mês atual


def easter(year):
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def br_holidays(year):
    """Feriados nacionais (e o Carnaval, que todo mundo emenda). Municipais ficam de fora."""
    e = easter(year)
    days = {
        date(year, 1, 1): "Confraternização Universal", date(year, 4, 21): "Tiradentes",
        date(year, 5, 1): "Dia do Trabalho", date(year, 9, 7): "Independência",
        date(year, 10, 12): "Nossa Senhora Aparecida", date(year, 11, 2): "Finados",
        date(year, 11, 15): "Proclamação da República", date(year, 11, 20): "Consciência Negra",
        date(year, 12, 25): "Natal",
        e - timedelta(days=48): "Carnaval", e - timedelta(days=47): "Carnaval",
        e - timedelta(days=2): "Sexta-feira Santa", e + timedelta(days=60): "Corpus Christi",
    }
    return days


def today_br():
    return datetime.now(BR_TZ).date()


WEEKDAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def next_holiday(today=None):
    """Próximo feriado e o período que o turista emenda: {name, day, start, end}.
    Quinta ou sexta emendam até domingo; segunda ou terça começam no sábado."""
    today = today or today_br()
    hol = {}
    for y in (today.year, today.year + 1):
        hol.update(br_holidays(y))
    day = min(d for d in hol if d >= today)
    wd = day.weekday()  # segunda = 0
    start = day - timedelta(days={0: 2, 1: 3, 6: 1}.get(wd, 0))
    end = day + timedelta(days={3: 3, 4: 2, 5: 1}.get(wd, 0))
    while end + timedelta(days=1) in hol:  # Carnaval: segunda e terça
        end += timedelta(days=1)
    return {"name": hol[day], "day": day, "start": max(start, today), "end": end}


def day_label(d):
    return f"{WEEKDAYS_PT[d.weekday()]}, {d.day} de {MONTHS_PT[d.month - 1]}"


def calendar_months(busy, n=CALENDAR_MONTHS):
    """Meses da agenda a partir do mês atual: [{label, weeks: [[dia|None x7]]}].
    Semana começando no domingo, como nos calendários brasileiros."""
    today = today_br()
    holidays = {}
    for y in (today.year, today.year + 1, today.year + 2):
        holidays.update(br_holidays(y))
    cal = calmod.Calendar(firstweekday=6)
    months, y, m = [], today.year, today.month
    for _ in range(n):
        weeks = []
        for week in cal.monthdatescalendar(y, m):
            weeks.append([None if d.month != m else {
                "date": d, "iso": d.isoformat(), "past": d < today, "today": d == today,
                "busy": d in busy, "holiday": holidays.get(d, ""), "weekend": d.weekday() >= 5,
            } for d in week])
        months.append({"label": f"{MONTHS_PT[m - 1].capitalize()} de {y}", "weeks": weeks})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def busy_set(r, start=None):
    start = start or today_br().replace(day=1)
    return {b.day for b in r.busy_days.filter(BusyDay.day >= start)}


def ical_feed_url(url):
    """Link da agenda em .ics. Aceita também o link de incorporar do Google Agenda, que é o que o
    dono encontra no próprio site (calendar.google.com/calendar/embed?src=...)."""
    url = (url or "").strip().replace("&#x26;", "&").replace("&amp;", "&")
    m = re.search(r"calendar\.google\.com/calendar/(?:u/\d+/)?embed\?(?:[^#]*&)?src=([^&#]+)", url)
    if m:
        return f"https://calendar.google.com/calendar/ical/{quote(unquote(m.group(1)), safe='')}/public/basic.ics"
    return url if url.startswith("https://") else ""


def _ical_date(params, value):
    """(dia em Brasília, tem_hora). Evento de dia inteiro vem como 20261019."""
    if len(value) == 8:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])), False
    dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    tzid = re.search(r"TZID=([^;:]+)", params)
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tzid.group(1)) if tzid else BR_TZ)
        except Exception:
            dt = dt.replace(tzinfo=BR_TZ)
    return dt.astimezone(BR_TZ).date(), True


def ical_busy_days(text, start, end):
    """Dias ocupados entre start e end num arquivo .ics. Todo evento conta como ocupado
    (Google Agenda, Airbnb e Booking só exportam as reservas), inclusive os marcados como "livre":
    no Google Agenda, evento de dia inteiro já nasce "livre". Só cancelado não conta.
    Evento repetido (RRULE) conta só a primeira vez."""
    text = re.sub(r"\r?\n[ \t]", "", text)  # linhas dobradas do formato .ics
    days = set()
    for ev in text.split("BEGIN:VEVENT")[1:]:
        ev = ev.split("END:VEVENT")[0]
        if re.search(r"^STATUS:CANCELLED", ev, re.M | re.I):
            continue
        s = re.search(r"^DTSTART([^:\r\n]*):(\S+)", ev, re.M)
        if not s:
            continue
        try:
            a, timed = _ical_date(s.group(1), s.group(2))
            e = re.search(r"^DTEND([^:\r\n]*):(\S+)", ev, re.M)
            b = _ical_date(e.group(1), e.group(2))[0] if e else a
        except ValueError:
            continue
        # Dia inteiro: o fim é o dia seguinte ao último. Com hora: o dia em que termina também conta.
        b = b + timedelta(days=1) if timed else max(b, a + timedelta(days=1))
        d = max(a, start)
        while d < b and d <= end:
            days.add(d)
            d += timedelta(days=1)
    return days


def sync_ical(r):
    """Copia os dias ocupados da agenda externa para a agenda do rancho, de hoje em diante.
    A agenda externa manda: dia liberado lá é liberado aqui. Se o link falhar, a agenda
    daqui fica como estava e o erro aparece no painel."""
    r.ical_synced_at = now_utc()
    try:
        url = ical_feed_url(r.ical_url)
        if not url:
            raise ValueError("o link precisa começar com https://")
        req = urllib.request.Request(url, headers={"User-Agent": f"{SITE_NAME} (agenda)"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read(3_000_000).decode("utf-8", "replace")
        if "BEGIN:VCALENDAR" not in text:
            raise ValueError("o link não é de uma agenda (.ics)")
    except Exception as e:  # rede, 404, agenda que deixou de ser pública...
        r.ical_error = str(e)[:200] or e.__class__.__name__
        db.session.commit()
        return False
    today = today_br()
    want = ical_busy_days(text, today, today + timedelta(days=400))
    have = {b.day: b for b in r.busy_days.filter(BusyDay.day >= today)}
    for d, b in have.items():
        if d not in want:
            db.session.delete(b)
    for d in want - have.keys():
        db.session.add(BusyDay(rancho_id=r.id, day=d))
    r.ical_error = ""
    r.calendar_updated_at = now_utc()
    try:
        db.session.commit()
    except exc.IntegrityError:  # outro worker sincronizou o mesmo rancho ao mesmo tempo
        db.session.rollback()
    return True


_ical_next_check = 0.0


@app.before_request
def sync_external_calendars():
    """Sem tarefa agendada no Cloud Run: as visitas às páginas com agenda disparam a cópia.
    Cada processo olha no máximo a cada 10 minutos, e só copia agendas mais velhas que
    ICAL_SYNC_HOURS, então quase nenhuma visita espera por isso."""
    global _ical_next_check
    if request.method != "GET" or request.endpoint not in ("index", "rancho", "category", "group_list",
                                                            "rancho_agenda_json"):
        return
    if time.time() < _ical_next_check:
        return
    _ical_next_check = time.time() + 600
    stale = now_utc() - timedelta(hours=ICAL_SYNC_HOURS)
    try:
        for r in (Rancho.query.filter(Rancho.ical_url != "")
                  .filter((Rancho.ical_synced_at.is_(None)) | (Rancho.ical_synced_at < stale)).limit(3)):
            sync_ical(r)
    except Exception:
        db.session.rollback()  # agenda externa nunca derruba a página
        app.logger.exception("falha ao sincronizar agenda externa")


def parse_day(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def source_stats(since):
    """Linhas da tabela "De onde vêm os turistas", da origem que mais trouxe contato para a menor."""
    q = (db.session.query(Event.source, Event.kind, func.count(Event.id))
         .filter(Event.created_at >= since).group_by(Event.source, Event.kind))
    rows = {}
    for src, kind, n in q.all():
        src = src or "sem-registro"  # eventos de antes de existir a origem
        row = rows.setdefault(src, {"source": src, "label": SOURCE_LABELS.get(src, src),
                                    "visit": 0, "view": 0, "whatsapp": 0, "fav": 0})
        if kind in row:
            row[kind] = n
    if "sem-registro" in rows:
        rows["sem-registro"]["label"] = "Antes do registro de origem"
    return sorted(rows.values(), key=lambda r: (-r["whatsapp"], -r["visit"], -r["view"]))


def counts_since(since, rancho_id=None):
    """{(rancho_id, kind): n} since a date."""
    q = db.session.query(Event.rancho_id, Event.kind, func.count(Event.id)).filter(Event.created_at >= since)
    if rancho_id:
        q = q.filter(Event.rancho_id == rancho_id)
    return {(r, k): n for r, k, n in q.group_by(Event.rancho_id, Event.kind).all()}


@app.context_processor
def inject_globals():
    return dict(SITE_NAME=SITE_NAME, CITY_NAME=CITY_NAME, SITE_WHATSAPP=SITE_WHATSAPP,
                AMENITIES=AMENITIES, FILTER_AMENITIES=FILTER_AMENITIES, SERVICES=SERVICES, brl=brl, csrf_token=csrf_token, is_admin=is_admin,
                current_owner=current_owner, site_url=site_url, year=datetime.now().year)


CANONICAL_HOST = urlparse(BASE_URL).netloc


# Não redirecionar outros hosts para o domínio oficial: atrás do Firebase, parte das requisições
# ao próprio domínio (inclusive do robô do Google buscando robots.txt e sitemap) chega sem
# X-Forwarded-Host, com o host interno *.a.run.app. O redirecionamento mandava essas requisições
# para o mesmo endereço, em loop, e o Search Console não conseguia ler o sitemap (out/2026).
# Para o Google ficar só com o domínio, basta o <link rel="canonical"> que as páginas já têm.


BR_TZ = ZoneInfo("America/Sao_Paulo")


@app.template_filter("local")
def local_time(dt):
    """Datas são salvas em UTC; mostra no horário de Brasília."""
    return dt.replace(tzinfo=timezone.utc).astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M") if dt else ""


@app.template_filter("ago")
def ago(dt):
    """"hoje", "ontem", "há 3 dias"... contando pelo dia de Brasília."""
    if not dt:
        return ""
    n = (today_br() - dt.replace(tzinfo=timezone.utc).astimezone(BR_TZ).date()).days
    if n <= 0:
        return "hoje"
    if n == 1:
        return "ontem"
    if n < 14:
        return f"há {n} dias"
    if n < 60:
        return f"há {n // 7} semanas"
    return f"há {n // 30} meses"


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # Só as fotos podem ficar no cache da CDN; páginas têm contagem de visitas e token de formulário.
    resp.headers.setdefault("Cache-Control", "private, no-cache")
    return resp


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    cap = to_int(request.args.get("hospedes"), 0)
    max_price = to_int(request.args.get("ate"), 0)
    wanted = [a for a in request.args.getlist("c") if a in AMENITIES]
    order = request.args.get("ordem", "destaque")

    ranchos = public_ranchos().all()
    total = len(ranchos)
    # Foto do topo: capa de um rancho sorteado a cada visita. Foto em pé também entra: com o
    # verde por cima o corte fica bom, e no celular o topo é alto e ela encaixa melhor.
    covers = [r for r in ranchos if r.cover]
    hero = random.choice(covers) if covers else None
    if cap:
        ranchos = [r for r in ranchos if (r.capacity or 0) >= cap]
    if max_price:
        # A cidade trabalha com valor de fim de semana. Rancho sem valor cadastrado ("consulte")
        # continua aparecendo, para não sumir da busca só por não ter preço.
        ranchos = [r for r in ranchos if not r.price_weekend or r.price_weekend <= max_price]
    if wanted:
        ranchos = [r for r in ranchos if set(wanted) <= set(r.amenity_list)]

    if order == "preco":
        ranchos.sort(key=lambda r: (r.price_weekend or 10**9))
    elif order == "capacidade":
        ranchos.sort(key=lambda r: -(r.capacity or 0))
    else:
        ranchos = default_order(ranchos)

    filtering = bool(cap or max_price or wanted)
    return render_template("index.html", ranchos=ranchos, total=total, cap=cap, max_price=max_price,
                           wanted=wanted, order=order, filtering=filtering, hero=hero,
                           categories=categories_with_ranchos(), holiday=holiday_block(),
                           updated=last_update(public_ranchos().all()), lds=[site_ld()])


def holiday_block():
    """Bloco "Próximo feriado" da página inicial. Só conta ranchos com agenda no site:
    dos outros não dá para saber se estão livres. None se nenhum tem agenda."""
    h = next_holiday()
    with_agenda = public_ranchos().filter(Rancho.calendar_updated_at.isnot(None)).all()
    if not with_agenda:
        return None
    busy = {rid for (rid,) in db.session.query(BusyDay.rancho_id)
            .filter(BusyDay.day.between(h["start"], h["end"])).distinct()}
    h["free"] = default_order([r for r in with_agenda if r.id not in busy])
    h["label"] = day_label(h["day"])
    h["period"] = (f"De {day_label(h['start'])} a {day_label(h['end'])}"
                   if h["start"] != h["end"] else day_label(h["day"]).capitalize())
    return h


# ---------------------------------------------------------------------------
# Respostas e números tirados do cadastro. Google e IAs (ChatGPT, Gemini...) preferem
# resposta direta e dado que só existe aqui a texto genérico sobre a cidade.
# ---------------------------------------------------------------------------
def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def join_pt(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]


def last_update(ranchos):
    """Última vez que algum desses ranchos mudou (anúncio ou agenda)."""
    ds = [d for r in ranchos for d in (r.updated_at, r.calendar_updated_at) if d]
    return max(ds) if ds else None


def price_range(ranchos):
    ps = sorted(r.price_weekend for r in ranchos if r.price_weekend)
    if not ps:
        return ""
    return brl(ps[0]) if ps[0] == ps[-1] else f"de {brl(ps[0])} a {brl(ps[-1])}"


def category_facts(cat, ranchos):
    """Frase-resumo e perguntas da página por tipo: ([fatos], [(pergunta, resposta)])."""
    city, n = CITY_NAME, len(ranchos)
    group = cat["title"][0].lower() + cat["title"][1:]  # "ranchos com piscina"
    facts, faq = [], []
    caps = sorted(r.capacity for r in ranchos if r.capacity)
    if caps:
        facts.append(f"recebem de {caps[0]} a {caps[-1]} pessoas" if caps[0] != caps[-1] else f"recebem até {caps[0]} pessoas")
    pr = price_range(ranchos)
    if pr:
        priced = sum(1 for r in ranchos if r.price_weekend)
        facts.append(f"o fim de semana sai {pr}" + (f" (nos {priced} que informam o valor)" if priced < n else ""))
        faq.append((f"Quanto custa o fim de semana nos {group} de {city}?",
                    f"No site, o fim de semana sai {pr}"
                    + (f", segundo os {priced} ranchos que informam o valor" if priced < n else "")
                    + ". Feriado costuma ter pacote próprio, que aparece em cada anúncio."))
    for key in ("beira_rio", "rampa", "piscina", "pet"):
        if key != cat.get("amenity"):
            k = sum(1 for r in ranchos if key in r.amenity_list)
            if k:
                facts.append(f"{k} {'tem' if k == 1 else 'têm'} {AMENITIES[key][0].lower()}" if key in ("piscina", "rampa")
                             else f"{k} {'fica' if k == 1 else 'ficam'} na beira do rio" if key == "beira_rio"
                             else f"{k} {'aceita' if k == 1 else 'aceitam'} pet")
    if caps and n > 1:
        big = [r for r in ranchos if r.capacity == caps[-1]]
        faq.append((f"Qual dos {group} cabe mais gente?",
                    f"{join_pt(r.name for r in big)}, para até {caps[-1]} pessoas."))
    ver = [r for r in ranchos if r.verified]
    faq.append((f"Quais {group} foram visitados pela equipe do site?",
                f"{join_pt(r.name for r in ver)}. {'Ele tem' if len(ver) == 1 else 'Eles têm'} o selo ✓ Verificado: visitamos o local e confirmamos o contato do dono."
                if ver else "Nenhum ainda. Antes de pagar qualquer sinal, siga o nosso guia para alugar com segurança."))
    head = f"{plural(n, 'rancho', 'ranchos')} no site"
    return ([head] + facts), faq


def rancho_faq(r):
    """Perguntas de quem vai alugar, respondidas com o que o dono cadastrou.
    Só entra pergunta com resposta conhecida: comodidade não marcada não quer dizer "não"."""
    a, q = set(r.amenity_list), []
    dono = r.owner_name.split()[0] if r.owner_name else "o dono"
    if r.capacity:
        rooms = f", em {plural(r.bedrooms, 'quarto', 'quartos')}" if r.bedrooms else ""
        beds = f" Camas: {r.beds}." if r.beds else ""
        q.append((f"Quantas pessoas cabem no {r.name}?", f"Até {r.capacity} pessoas{rooms}.{beds}"))
    prices = []
    if r.price_weekend:
        prices.append(f"o fim de semana sai por {brl(r.price_weekend)}")
    if r.price_night:
        prices.append(f"a diária avulsa por {brl(r.price_night)}")
    if prices or r.price_holiday:
        txt = ("Pelo anúncio, " + " e ".join(prices) + ". ") if prices else ""
        txt += f"Feriados: {r.price_holiday}." if r.price_holiday else "O valor de feriado é combinado com o dono."
        q.append((f"Quanto custa alugar o {r.name}?", txt))
    water = [t for k, t in (("beira_rio", "fica na beira do rio"), ("rampa", "tem rampa para barco e jet ski"),
                            ("pesca", "é bom para pesca")) if k in a]
    if water:
        q.append(("Fica na beira do rio? Dá para colocar o barco?", f"Sim: o rancho {join_pt(water)}."))
    if "pet" in a:
        q.append(("Aceita cachorro?", "Sim, o rancho aceita pet. Avise o dono antes sobre o seu."))
    if r.internet or "wifi" in a:
        q.append(("Tem internet?", f"Sim: {r.internet}." if r.internet else "Sim, tem Wi-Fi."))
    if "roupa_cama" in a:
        q.append(("Precisa levar roupa de cama?", "Não, a roupa de cama está inclusa."))
    if r.checkin or r.checkout:
        parts = ([f"entrada a partir das {r.checkin}"] if r.checkin else []) + ([f"saída até as {r.checkout}"] if r.checkout else [])
        q.append(("Qual o horário de entrada e saída?", join_pt(parts).capitalize() + "."))
    if (r.min_nights or 1) > 1:
        q.append(("Tem mínimo de diárias?", f"Sim, {r.min_nights} diárias."))
    q.append(("Como reservar?", f"Fale direto com {dono} pelo WhatsApp, no botão desta página. Datas, valor e sinal "
                                "são combinados com o dono, sem intermediário e sem taxa do site. Antes de pagar o sinal, "
                                "peça um contrato simples e confira se o nome no Pix é o do dono."))
    if r.verified:
        when = f" em {r.verified_at.replace(tzinfo=timezone.utc).astimezone(BR_TZ):%d/%m/%Y}" if r.verified_at else ""
        q.append(("O rancho é confiável?", f"A equipe do site visitou o rancho{when} e confirmou o contato do dono."))
    return q


def faq_ld(faq):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": qq, "acceptedAnswer": {"@type": "Answer", "text": aa}}
                           for qq, aa in faq]}


def breadcrumb_ld(*items):
    """items: (nome, caminho). O último é a página atual."""
    base = site_url()
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i, "name": n, "item": base + path}
                                for i, (n, path) in enumerate(items, 1)]}


def site_ld():
    base = site_url()
    org = {"@type": "Organization", "@id": f"{base}/#org", "name": SITE_NAME, "url": f"{base}/",
           "description": f"Catálogo de ranchos para alugar em {CITY_NAME}, com ranchos visitados pela equipe "
                          "e contato direto com o dono.",
           "areaServed": {"@type": "City", "name": CITY_NAME}}
    if SITE_WHATSAPP:
        org["contactPoint"] = {"@type": "ContactPoint", "telephone": f"+{SITE_WHATSAPP}",
                               "contactType": "customer support", "availableLanguage": "Portuguese"}
    return {"@context": "https://schema.org", "@graph": [
        org, {"@type": "WebSite", "@id": f"{base}/#site", "name": SITE_NAME, "url": f"{base}/",
              "inLanguage": "pt-BR", "publisher": {"@id": f"{base}/#org"}}]}


@app.route("/ranchos/<slug>")
def category(slug):
    cat = CATEGORIES.get(slug) or abort(404)
    everyone = public_ranchos().all()
    ranchos = default_order([r for r in everyone if in_category(r, cat)])
    if not ranchos:
        abort(404)
    others = [c for c in categories_with_ranchos(everyone) if c[0] != slug]
    facts, faq = category_facts(cat, ranchos)
    h1 = cat.get("h1", "{title} para alugar em {city}").format(title=cat["title"], city=CITY_NAME)
    seo_title = cat.get("seo_title", "{title} para alugar em {city}").format(title=cat["title"], city=CITY_NAME)
    lds = [breadcrumb_ld(("Ranchos", "/"), (cat["title"], f"/ranchos/{slug}")), faq_ld(faq)]
    return render_template("category.html", slug=slug, cat=cat, ranchos=ranchos, others=others,
                           intro=cat["intro"].format(city=CITY_NAME), h1=h1, seo_title=seo_title,
                           facts=facts, faq=faq, rows=compare_rows(ranchos) if len(ranchos) > 1 else [],
                           updated=last_update(ranchos), lds=lds)


@app.route("/sobre")
def about():
    ranchos = public_ranchos().all()
    return render_template("sobre.html", n=len(ranchos), n_verified=sum(1 for r in ranchos if r.verified),
                           updated=last_update(ranchos), lds=[site_ld()])


@app.route("/como-alugar-com-seguranca")
def safety_guide():
    lds = [breadcrumb_ld(("Ranchos", "/"), ("Como alugar com segurança", "/como-alugar-com-seguranca"))]
    return render_template("seguranca.html", lds=lds)


def compare_rows(ranchos):
    """Linhas da tabela de comparação: [(rótulo, [(texto, é_o_melhor), ...])].
    Some com as linhas que nenhum rancho preencheu e marca o melhor valor quando os
    números são diferentes (menor preço; maior capacidade, quartos, geladeiras...)."""
    many = len(ranchos) > 1
    rows = []

    def numeric(label, values, fmt, best=max):
        known = [v for v in values if v]
        if not known:
            return
        top = best(known)
        mark = many and len(set(known)) > 1
        rows.append((label, [(fmt(v) if v else "—", mark and v == top) for v in values]))

    def text(label, values):
        if any(values):
            rows.append((label, [(v or "—", False) for v in values]))

    def yes_no(label, flags):
        if any(flags):
            rows.append((label, [("✓" if f else "—", False) for f in flags]))

    numeric("💰 Fim de semana", [r.price_weekend for r in ranchos], brl, best=min)
    numeric("👥 Pessoas", [r.capacity for r in ranchos], lambda v: f"até {v}")
    numeric("🛏️ Quartos", [r.bedrooms for r in ranchos], str)
    numeric("🚿 Banheiros", [r.bathrooms for r in ranchos], str)
    text("🛌 Camas", [r.beds for r in ranchos])
    text("📅 Mínimo", [f"{r.min_nights} diárias" if (r.min_nights or 1) > 1 else "" for r in ranchos])
    text("📶 Internet", [r.internet or ("Tem Wi-Fi" if "wifi" in r.amenity_list else "") for r in ranchos])
    numeric("🧊 Geladeiras", [r.fridges for r in ranchos], str)
    numeric("🍺 Cervejeiras", [r.beer_fridges for r in ranchos], str)
    numeric("❄️ Freezers", [r.freezers for r in ranchos], str)
    for key in FILTER_AMENITIES:
        if key != "wifi":
            yes_no(f"{AMENITIES[key][1]} {AMENITIES[key][0]}", [key in r.amenity_list for r in ranchos])
    yes_no("✓ Verificado", [r.verified for r in ranchos])
    return rows


@app.route("/lista")
def group_list():
    """Lista de ranchos para mandar ao grupo. Os ranchos vão no próprio endereço
    (?r=slug1,slug2), então quem recebe o link vê a mesma lista, sem login."""
    slugs = [s for s in dict.fromkeys(request.args.get("r", "").split(",")) if s][:LIST_MAX]
    found = {r.slug: r for r in public_ranchos().filter(Rancho.slug.in_(slugs)).all()} if slugs else {}
    ranchos = [found[s] for s in slugs if s in found]
    share_url = f"{site_url()}/lista?r={','.join(r.slug for r in ranchos)}" if ranchos else ""
    share_text = (f"Separei {'esses ranchos' if len(ranchos) > 1 else 'esse rancho'} em {CITY_NAME} "
                  f"pra gente escolher: {share_url}")
    return render_template("lista.html", ranchos=ranchos, share_url=share_url, rows=compare_rows(ranchos),
                           wa_link=f"https://wa.me/?text={quote(share_text)}" if ranchos else "")


@app.route("/rancho/<slug>")
def rancho(slug):
    r = Rancho.query.filter_by(slug=slug).first_or_404()
    own = current_owner() and r.owner_id == current_owner().id
    if not r.public and not (is_admin() or own):  # admin e o dono podem pré-visualizar
        abort(404)
    seen = session.get("seen", {})
    today = datetime.now().strftime("%Y-%m-%d")
    # "view" = pessoa (1 por rancho por dia); "reopen" = a mesma pessoa abrindo de novo no dia.
    # Visualizações = view + reopen; pessoas = view (o histórico de antes do reopen continua igual).
    if seen.get(str(r.id)) != today:
        log_event(r.id, "view")
        seen[str(r.id)] = today
        session["seen"] = dict(list(seen.items())[-50:])
    else:
        log_event(r.id, "reopen")
    others = (public_ranchos().filter(Rancho.id != r.id)
              .order_by(Rancho.featured.desc(), Rancho.updated_at.desc()).limit(3).all())
    base = site_url()
    ld = {
        "@context": "https://schema.org",
        "@type": "LodgingBusiness",
        "name": r.name,
        "description": r.summary or (r.description or "")[:200],
        "url": f"{base}/rancho/{r.slug}",
        "address": {"@type": "PostalAddress", "addressLocality": CITY_NAME, "streetAddress": r.region or ""},
        "image": [p.url(absolute=True) for p in r.photos[:5]],
        "priceRange": f"{brl(r.price_weekend)} o fim de semana" if r.price_weekend else "Consulte",
        "amenityFeature": [{"@type": "LocationFeatureSpecification", "name": AMENITIES[a][0], "value": True}
                           for a in r.amenity_list],
    }
    if "pet" in r.amenity_list:
        ld["petsAllowed"] = True
    if r.checkin:
        ld["checkinTime"] = r.checkin
    if r.checkout:
        ld["checkoutTime"] = r.checkout
    faq = rancho_faq(r)
    lds = [breadcrumb_ld(("Ranchos", "/"), (r.name, f"/rancho/{r.slug}")), faq_ld(faq)]
    months = calendar_months(busy_set(r)) if r.calendar_updated_at else None
    return render_template("rancho.html", r=r, others=others, ld=ld, months=months, faq=faq, lds=lds,
                           providers=public_providers()[:3])


@app.route("/rancho/<slug>/whatsapp")
def rancho_whatsapp(slug):
    r = public_ranchos().filter_by(slug=slug).first_or_404()
    if not r.whatsapp_digits:
        abort(404)
    log_event(r.id, "whatsapp")
    msg = (f"Olá{(' ' + r.owner_name.split()[0]) if r.owner_name else ''}! "
           f"Vi o {r.name} no site {SITE_NAME} e gostaria de saber a disponibilidade para as datas: ")
    # Datas escolhidas na agenda da página do rancho (?de=2026-10-10&ate=2026-10-12)
    start, end = parse_day(request.args.get("de")), parse_day(request.args.get("ate"))
    if start and start >= today_br():
        end = end if end and start <= end <= start + timedelta(days=60) else start
        msg += (f"{start:%d/%m/%Y}" if end == start else f"{start:%d/%m/%Y} a {end:%d/%m/%Y}") + "."
    return redirect(f"https://wa.me/{r.whatsapp_digits}?text={quote(msg)}")


@app.route("/rancho/<slug>/agenda.json")
def rancho_agenda_json(slug):
    """Dias ocupados do rancho, para o site próprio do dono mostrar a mesma agenda."""
    r = public_ranchos().filter_by(slug=slug).first_or_404()
    updated = r.calendar_updated_at
    data = {
        "atualizadaEm": updated and updated.isoformat() + "Z",  # vazio = rancho ainda sem agenda
        "ocupados": sorted(d.isoformat() for d in busy_set(r)) if updated else [],
    }
    return data, 200, {"Access-Control-Allow-Origin": "*"}  # só leitura, sem dados pessoais


@app.route("/rancho/<slug>/salvou", methods=["POST"])
def rancho_saved(slug):
    """Conta quem tocou no ♥ (uma vez por navegador por rancho). O número aparece só
    no painel e no relatório do dono, não no site."""
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if origin and urlparse(origin).netloc != request.host:  # só aceita vindo do próprio site
        abort(403)
    r = public_ranchos().filter_by(slug=slug).first_or_404()
    counted = session.get("faved", [])
    if r.id not in counted:
        log_event(r.id, "fav")
        session["faved"] = (counted + [r.id])[-100:]
    return "", 204


def public_providers():
    """Profissionais no ar; quem tem foto primeiro, depois os mais recentes."""
    ps = Provider.query.filter_by(active=True).order_by(Provider.created_at.desc()).all()
    return sorted(ps, key=lambda p: p.cover is None)


@app.route("/servicos")
def services():
    wanted = request.args.get("tipo", "")
    providers = public_providers()
    if wanted in SERVICES:
        providers = [p for p in providers if wanted in p.service_list]
    rancho = Rancho.query.filter_by(slug=request.args.get("rancho", "")).first()
    return render_template("services.html", providers=providers, wanted=wanted,
                           rancho=rancho if rancho and rancho.public else None)


@app.route("/servicos/<slug>/whatsapp")
def provider_whatsapp(slug):
    p = Provider.query.filter_by(slug=slug, active=True).first_or_404()
    if not p.whatsapp_digits:
        abort(404)
    r = Rancho.query.filter_by(slug=request.args.get("rancho", "")).first()
    log_event(r.id if r else None, "prestador", provider_id=p.id)
    stay = f" Vou ficar no {r.name}." if r else ""
    msg = (f"Olá, {p.name.split()[0]}! Vi seu anúncio no site {SITE_NAME}.{stay} "
           f"Gostaria de saber sobre seus serviços para as datas: ")
    return redirect(f"https://wa.me/{p.whatsapp_digits}?text={quote(msg)}")


@app.route("/img/s/<int:pid>")
def provider_image(pid):
    p = db.session.get(ProviderPhoto, pid) or abort(404)
    if p.cdn_key:
        return redirect(p.url(request.args.get("s", "f")), 301)
    etag = f'"{p.etag}-{request.args.get("s", "f")}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)
    resp = Response(p.thumb if request.args.get("s") == "t" else p.full, mimetype="image/webp")
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["ETag"] = etag
    return resp


@app.route("/servicos/whatsapp")
def servicos_whatsapp():
    if not SITE_WHATSAPP:
        abort(404)
    r = Rancho.query.filter_by(slug=request.args.get("rancho", "")).first()
    if r:
        log_event(r.id, "servico")
    extra = f" no {r.name}" if r else ""
    msg = f"Olá! Vou ficar{extra} e gostaria de contratar cozinheira ou faxina. As datas são: "
    return redirect(f"https://wa.me/{SITE_WHATSAPP}?text={quote(msg)}")


@app.route("/anuncie", methods=["GET", "POST"])
def anuncie():
    sent = False
    if request.method == "POST":
        check_csrf()
        if request.form.get("website"):  # honeypot anti-spam
            return redirect(url_for("anuncie"))
        name = request.form.get("name", "").strip()[:120]
        phone = request.form.get("phone", "").strip()[:40]
        if not name or len(re.sub(r"\D", "", phone)) < 10:
            flash("Preencha seu nome e um WhatsApp com DDD.", "error")
            return render_template("anuncie.html", form=request.form), 400
        db.session.add(Lead(name=name, phone=phone,
                            rancho_name=request.form.get("rancho_name", "").strip()[:160],
                            region=request.form.get("region", "").strip()[:160],
                            message=request.form.get("message", "").strip()[:2000]))
        db.session.commit()
        sent = True
    return render_template("anuncie.html", sent=sent, form={})


@app.route("/img/<int:pid>")
def image(pid):
    p = db.session.get(Photo, pid)
    if not p:
        abort(404)
    if p.cdn_key:  # links antigos (Google Imagens, WhatsApp) continuam funcionando
        return redirect(p.url(request.args.get("s", "f")), 301)
    etag = f'"{p.etag}-{request.args.get("s", "f")}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)
    data = p.thumb if request.args.get("s") == "t" else p.full
    resp = Response(data, mimetype="image/webp")
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["ETag"] = etag
    return resp


@app.route("/robots.txt")
def robots():
    # Em produção quem responde é a cópia estática firebase-public/robots.txt (o Firebase serve
    # arquivo estático antes de repassar ao Cloud Run), para o Google sempre conseguir ler
    # mesmo se a ligação com o Cloud Run engasgar. Mudou aqui? Atualize lá também.
    body = f"User-agent: *\nDisallow: /admin\nDisallow: /rancho/*/whatsapp\nSitemap: {site_url()}/sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    base = site_url()
    urls = [(f"{base}/", None), (f"{base}/anuncie", None), (f"{base}/sobre", None),
            (f"{base}/como-alugar-com-seguranca", None)]
    ranchos = public_ranchos().all()
    for slug, _, _ in categories_with_ranchos(ranchos):
        urls.append((f"{base}/ranchos/{slug}", None))
    for r in ranchos:
        urls.append((f"{base}/rancho/{r.slug}", r.updated_at))
    if Provider.query.filter_by(active=True).first():
        urls.append((f"{base}/servicos", None))
    items = "".join(
        f"<url><loc>{u}</loc>{f'<lastmod>{d:%Y-%m-%d}</lastmod>' if d else ''}</url>" for u, d in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    return Response(xml, mimetype="application/xml")


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
LOGIN_RE = re.compile(r"^[a-z0-9@._+-]{3,120}$")
MIN_PASSWORD = 8
# Hash de uma senha qualquer: login inexistente gasta o mesmo tempo que senha errada,
# para não dar para descobrir quais logins existem.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(8))


MAX_FAILURES = 5                  # senhas erradas seguidas...
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_TIME = timedelta(minutes=15)  # ...bloqueiam a conta por este tempo


def normalize_login(v):
    return (v or "").strip().lower()


def throttle_key(login):
    return f"owner:{login}" if login else "admin"


def locked_minutes(key):
    """Minutos que ainda faltam de bloqueio (0 = liberado)."""
    t = db.session.get(LoginThrottle, key)
    if t and t.locked_until and t.locked_until > now_utc():
        return max(1, int((t.locked_until - now_utc()).total_seconds() // 60) + 1)
    return 0


def register_failure(key):
    """Conta uma senha errada; devolve quantas tentativas ainda restam (0 = acabou de bloquear)."""
    now = now_utc()
    t = db.session.get(LoginThrottle, key)
    if not t:
        t = LoginThrottle(key=key, failures=0, window_start=now)
        db.session.add(t)
    if not t.window_start or t.window_start < now - FAILURE_WINDOW:
        t.failures, t.window_start = 0, now
    t.failures = (t.failures or 0) + 1
    left = MAX_FAILURES - t.failures
    if left <= 0:
        t.locked_until, t.failures, t.window_start = now + LOCK_TIME, 0, now
        left = 0
    db.session.commit()
    return left


def clear_failures(key):
    t = db.session.get(LoginThrottle, key)
    if t:
        db.session.delete(t)
        db.session.commit()


def temp_password():
    """Senha provisória fácil de ditar por telefone (sem 0/O, 1/l)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        check_csrf()
        time.sleep(0.6)  # freia tentativas de adivinhar a senha
        login = normalize_login(request.form.get("login"))
        password = request.form.get("password", "")
        nxt = request.args.get("next", "")
        nxt = nxt if nxt.startswith("/admin") else url_for("admin_home")
        key = throttle_key(login)
        wait = locked_minutes(key)
        if wait:  # bloqueada: nem confere a senha, senão dava para continuar chutando
            flash(f"Muitas senhas erradas. Por segurança, o acesso ficou bloqueado; "
                  f"tente de novo em {wait} minuto(s).", "error")
            return render_template("admin/login.html", login=login), 429
        if not login:  # administrador: só a senha, como sempre foi
            if ADMIN_PASSWORD and hmac.compare_digest(password, ADMIN_PASSWORD):
                clear_failures(key)
                session.clear()
                session.permanent = True
                session["admin"] = True
                return redirect(nxt)
        else:
            o = Owner.query.filter_by(login=login).first()
            if o and o.active and o.check_password(password):
                clear_failures(key)
                session.clear()
                session.permanent = True
                session["owner_id"] = o.id
                o.last_login = now_utc()
                db.session.commit()
                return redirect(url_for("owner_password") if o.must_change else nxt)
            if not o:
                check_password_hash(_DUMMY_HASH, password)
        left = register_failure(key)
        msg = "Login ou senha incorretos." if login else "Senha incorreta."
        if left == 0:
            msg += f" Por segurança, o acesso ficou bloqueado por {int(LOCK_TIME.total_seconds() // 60)} minutos."
        elif left <= 2:
            msg += f" Mais {left} tentativa(s) errada(s) e o acesso fica bloqueado por {int(LOCK_TIME.total_seconds() // 60)} minutos."
        flash(msg, "error")
        return render_template("admin/login.html", login=login), 401
    return render_template("admin/login.html")


@app.route("/admin/logout", methods=["POST"])
@panel_required
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin/senha", methods=["GET", "POST"])
@panel_required
def owner_password():
    """Dono troca a senha (obrigatório no primeiro acesso)."""
    o = current_owner()
    if not o:  # a senha do administrador fica na variável ADMIN_PASSWORD
        abort(404)
    if request.method == "POST":
        new, confirm = request.form.get("new", ""), request.form.get("confirm", "")
        if not o.check_password(request.form.get("current", "")):
            flash("A senha atual não confere.", "error")
        elif len(new) < MIN_PASSWORD:
            flash(f"A senha nova precisa ter pelo menos {MIN_PASSWORD} caracteres.", "error")
        elif new != confirm:
            flash("As duas senhas novas não são iguais.", "error")
        elif o.check_password(new):
            flash("A senha nova precisa ser diferente da atual.", "error")
        else:
            o.set_password(new)
            o.must_change = False
            db.session.commit()
            flash("Senha trocada. Pronto, pode usar o painel.", "ok")
            return redirect(url_for("admin_home"))
    return render_template("admin/password.html", owner=o)


@app.route("/admin")
@panel_required
def admin_home():
    since = now_utc() - timedelta(days=30)
    o = current_owner()
    if o:
        ranchos = Rancho.query.filter_by(owner_id=o.id).order_by(Rancho.name).all()
        c30 = counts_since(since)
        return render_template("admin/owner_home.html", ranchos=ranchos, c30=c30, owner=o)
    ranchos = Rancho.query.order_by(Rancho.pending.desc(), Rancho.featured.desc(), Rancho.name).all()
    c30 = counts_since(since)
    leads = Lead.query.order_by(Lead.handled, Lead.created_at.desc()).limit(50).all()
    totals = {
        "views": sum(n for (_, k), n in c30.items() if k == "view"),
        "pageviews": sum(n for (_, k), n in c30.items() if k in ("view", "reopen")),
        "whatsapp": sum(n for (_, k), n in c30.items() if k == "whatsapp"),
        "servico": sum(n for (_, k), n in c30.items() if k == "servico"),
        "fav": sum(n for (_, k), n in c30.items() if k == "fav"),
    }
    return render_template("admin/dashboard.html", ranchos=ranchos, c30=c30, leads=leads, totals=totals,
                           sources=source_stats(since), billing=billing_rows(ranchos), today=today_br())


def billing_rows(ranchos):
    """Ranchos vencidos ou vencendo nos próximos dias, do que venceu há mais tempo para o mais novo,
    cada um com a mensagem de cobrança pronta para mandar no WhatsApp do dono."""
    today = today_br()
    due = sorted((r for r in ranchos if not r.pending and r.paid_until
                  and r.paid_until <= today + timedelta(days=BILLING_NOTICE_DAYS)),
                 key=lambda r: r.paid_until)
    if not due:
        return []
    c90 = counts_since(now_utc() - timedelta(days=90))
    rows = []
    for r in due:
        days = (r.paid_until - today).days
        contacts = c90.get((r.id, "whatsapp"), 0)
        text = billing_text(r, days, contacts)
        rows.append({
            "r": r, "days": days, "contacts": contacts, "text": text,
            "wa_link": f"https://wa.me/{r.whatsapp_digits}?text={quote(text)}" if r.whatsapp_digits else "",
        })
    return rows


def billing_text(r, days, contacts):
    first = (r.owner_name or "").split()[0] if r.owner_name else ""
    when = r.paid_until.strftime("%d/%m")
    lines = [f"Olá{(' ' + first) if first else ''}! Aqui é do {SITE_NAME}."]
    if days >= 0:
        lines.append(f"O anúncio do {r.name} está ativo até {when}.")
    else:
        lines.append(f"O anúncio do {r.name} venceu em {when}.")
    if contacts:
        lines.append(f"Nos últimos 3 meses, {contacts} {'pessoa clicou' if contacts == 1 else 'pessoas clicaram'} "
                     f"para falar com você no WhatsApp pelo site.")
    lines.append(f"Para continuar é {PRICE_MONTH} por mês ou {PRICE_YEAR} o ano todo.")
    if PIX_KEY:
        lines.append(f"Pix: {PIX_KEY}")
    lines.append("Se não quiser continuar, é só avisar que eu tiro o anúncio, sem problema.")
    return "\n".join(lines)


def fill_rancho(r, form):
    r.name = form.get("name", "").strip()[:120] or "Sem nome"
    r.region = form.get("region", "").strip()[:120]
    r.summary = form.get("summary", "").strip()[:200]
    r.description = form.get("description", "").replace("\r\n", "\n").strip()  # o navegador manda \r\n
    r.capacity = to_int(form.get("capacity"))
    r.bedrooms = to_int(form.get("bedrooms"))
    r.bathrooms = to_int(form.get("bathrooms"))
    r.beds = form.get("beds", "").strip()[:160]
    r.internet = form.get("internet", "").strip()[:120]
    r.fridges = to_int(form.get("fridges"))
    r.freezers = to_int(form.get("freezers"))
    r.beer_fridges = to_int(form.get("beer_fridges"))
    r.price_night = to_int(form.get("price_night"))
    r.price_weekend = to_int(form.get("price_weekend"))
    r.price_holiday = form.get("price_holiday", "").strip()[:160]
    r.min_nights = to_int(form.get("min_nights"), 1) or 1
    r.checkin = form.get("checkin", "").strip()[:20]
    r.checkout = form.get("checkout", "").strip()[:20]
    r.rules = form.get("rules", "").strip()
    r.amenities = ",".join(a for a in form.getlist("amenities") if a in AMENITIES)
    maps = form.get("maps_url", "").strip()[:500]
    r.maps_url = maps if maps.startswith("https://") else ""
    r.owner_name = form.get("owner_name", "").strip()[:120]
    old_digits = r.whatsapp_digits
    r.owner_whatsapp = form.get("owner_whatsapp", "").strip()[:30]
    r.active = bool(form.get("active"))
    if is_admin():
        set_verified(r, bool(form.get("verified")))
        r.featured = bool(form.get("featured"))
        r.paid_until = parse_day(form.get("paid_until"))
        ical = form.get("ical_url", "").strip()[:500]
        if ical != (r.ical_url or ""):
            r.ical_url, r.ical_synced_at, r.ical_error = ical, None, ""
        oid = to_int(form.get("owner_id"))
        r.owner_id = oid if oid and db.session.get(Owner, oid) else None
    elif r.verified and old_digits and r.whatsapp_digits != old_digits:
        # Conta invadida poderia trocar o número por um de golpista: o selo sai até o admin conferir.
        set_verified(r, False)
        return True
    return False


def save_uploads(r, files, photo_cls=None):
    """Fotos novas no fim da lista de r (rancho ou profissional)."""
    photo_cls = photo_cls or Photo
    added, skipped = 0, 0
    pos = max([p.position for p in r.photos] + [-1]) + 1
    for f in files:
        if not f or not f.filename:
            continue
        res = process_image(f)
        if not res:
            skipped += 1
            continue
        full, thumb, w, h = res
        etag = hashlib.sha1(full).hexdigest()[:16]
        key = ""
        if BUNNY_ON:
            db.session.flush()  # rancho novo ainda não tem id
            folder = r.id if photo_cls is Photo else f"servicos/{r.id}"
            key = f"{BUNNY_PREFIX}/{folder}/{etag}-{secrets.token_hex(3)}"
            bunny_upload(key, full, thumb)
            full = thumb = b""
        r.photos.append(photo_cls(position=pos, width=w, height=h, full=full, thumb=thumb,
                                  etag=etag, cdn_key=key))
        pos += 1
        added += 1
    return added, skipped


@app.route("/admin/rancho/novo", methods=["GET", "POST"])
@app.route("/admin/rancho/<int:rid>", methods=["GET", "POST"])
@panel_required
def admin_edit(rid=None):
    r = editable_rancho(rid) if rid else None
    owner = current_owner()
    if request.method == "POST":
        is_new = r is None
        if is_new:
            r = Rancho(slug="tmp-" + secrets.token_hex(4))
            if owner:  # rancho cadastrado pelo dono só vai ao ar depois da aprovação
                r.owner_id, r.pending = owner.id, True
            db.session.add(r)
        old_ical = r.ical_url or ""
        lost_seal = fill_rancho(r, request.form)
        if is_new or request.form.get("regen_slug"):
            db.session.flush()
            r.slug = unique_slug(r.name, exclude_id=r.id)
        added, skipped = save_uploads(r, request.files.getlist("photos"))
        db.session.commit()
        msg = "Rancho salvo."
        if added:
            msg += f" {added} foto(s) adicionada(s)."
        if skipped:
            msg += f" {skipped} arquivo(s) ignorado(s) por não serem imagens."
        if is_new and r.pending:
            msg += " Ele vai aparecer no site assim que for aprovado."
        flash(msg, "ok")
        if r.ical_url and r.ical_url != old_ical:
            if sync_ical(r):
                n = r.busy_days.filter(BusyDay.day >= today_br()).count()
                flash(f"Agenda copiada da agenda de origem: {n} dias ocupados.", "ok")
            else:
                flash(f"Não consegui ler a agenda de origem ({r.ical_error}). Confira o link.", "error")
        if lost_seal:
            flash("Como o WhatsApp mudou, o selo \"Verificado\" saiu até a gente conferir o número novo.", "error")
        return redirect(url_for("admin_edit", rid=r.id))
    owners = Owner.query.order_by(Owner.name, Owner.login).all() if is_admin() else []
    return render_template("admin/edit.html", r=r, owners=owners,
                           trial_end=months_later(today_br(), TRIAL_MONTHS))


@app.route("/admin/rancho/<int:rid>/agenda")
@panel_required
def admin_calendar(rid):
    r = editable_rancho(rid)
    return render_template("admin/agenda.html", r=r, months=calendar_months(busy_set(r)))


@app.route("/admin/rancho/<int:rid>/agenda", methods=["POST"])
@panel_required
def admin_calendar_save(rid):
    """Marca ou libera dias (um ou um período). Responde JSON para a página não recarregar."""
    r = editable_rancho(rid)
    if r.ical_url:  # a próxima cópia da agenda de origem desfaria a mudança
        return {"ok": False, "erro": "agenda copiada automaticamente; mude na agenda de origem"}, 400
    busy = request.form.get("busy") == "1"
    today = today_br()
    days = sorted({d for d in (parse_day(x) for x in request.form.get("days", "").split(",")) if d})
    days = [d for d in days if today <= d <= today + timedelta(days=400)][:400]  # passado não muda
    if not days:
        return {"ok": False, "erro": "Nenhum dia válido."}, 400
    existing = {b.day: b for b in r.busy_days.filter(BusyDay.day.in_(days))}
    for d in days:
        if busy and d not in existing:
            db.session.add(BusyDay(rancho_id=r.id, day=d))
        elif not busy and d in existing:
            db.session.delete(existing[d])
    r.calendar_updated_at = now_utc()
    try:
        db.session.commit()
    except exc.IntegrityError:  # duas abas marcando o mesmo dia ao mesmo tempo
        db.session.rollback()
    return {"ok": True, "updated": r.calendar_updated_at and local_time(r.calendar_updated_at)}


@app.route("/admin/rancho/<int:rid>/agenda/sincronizar", methods=["POST"])
@panel_required
def admin_calendar_sync(rid):
    r = editable_rancho(rid)
    if r.ical_url and sync_ical(r):
        flash("Agenda atualizada agora com a agenda de origem.", "ok")
    else:
        flash(f"Não consegui ler a agenda de origem ({r.ical_error or 'sem link'}).", "error")
    return redirect(url_for("admin_calendar", rid=r.id))


@app.route("/admin/rancho/<int:rid>/aprovar", methods=["POST"])
@admin_required
def admin_approve(rid):
    r = db.session.get(Rancho, rid) or abort(404)
    r.pending = False
    r.active = True
    if not r.paid_until:  # o período grátis conta a partir da publicação
        r.paid_until = months_later(today_br(), TRIAL_MONTHS)
    db.session.commit()
    flash(f"{r.name} aprovado e publicado no site.", "ok")
    if request.form.get("back") == "edit":
        return redirect(url_for("admin_edit", rid=r.id))
    return redirect(url_for("admin_home"))


@app.route("/admin/rancho/<int:rid>/foto/<int:pid>/<action>", methods=["POST"])
@panel_required
def admin_photo(rid, pid, action):
    r = editable_rancho(rid)
    photos = list(r.photos)
    p = next((x for x in photos if x.id == pid), None) or abort(404)
    gone = []
    if action == "excluir":
        r.photos.remove(p)
        gone.append(p.cdn_key)
    elif action == "capa":
        photos.remove(p)
        photos.insert(0, p)
    elif action in ("esquerda", "direita"):
        i = photos.index(p)
        j = i - 1 if action == "esquerda" else i + 1
        if 0 <= j < len(photos):
            photos[i], photos[j] = photos[j], photos[i]
    for i, x in enumerate(photos):
        x.position = i
    db.session.commit()
    bunny_delete(gone)
    return redirect(url_for("admin_edit", rid=rid) + "#fotos")


@app.route("/admin/rancho/<int:rid>/fotos", methods=["POST"])
@panel_required
def admin_photos_upload(rid):
    """Recebe um lote de fotos (o navegador divide envios grandes em vários lotes)."""
    r = editable_rancho(rid)
    added, skipped = save_uploads(r, request.files.getlist("photos"))
    db.session.commit()
    if request.form.get("final"):  # último lote: um resumo só, em vez de uma mensagem por lote
        total_added = to_int(request.form.get("prev_added")) + added
        total_skipped = to_int(request.form.get("prev_skipped")) + skipped
        msg = f"Rancho salvo. {total_added} foto(s) adicionada(s)."
        if total_skipped:
            msg += f" {total_skipped} arquivo(s) ignorado(s) por não serem imagens."
        flash(msg, "ok")
    return {"ok": True, "added": added, "skipped": skipped}


@app.route("/admin/rancho/<int:rid>/fotos/ordem", methods=["POST"])
@panel_required
def admin_photo_order(rid):
    """Recebe a ordem nova do arrastar-e-soltar: ids separados por vírgula."""
    r = editable_rancho(rid)
    by_id = {p.id: p for p in r.photos}
    try:
        ids = [int(x) for x in request.form.get("ordem", "").split(",") if x]
    except ValueError:
        abort(400)
    if sorted(ids) != sorted(by_id):  # a página estava desatualizada (foto nova ou excluída em outra aba)
        return {"ok": False, "erro": "As fotos mudaram em outra aba."}, 409
    for i, pid in enumerate(ids):
        by_id[pid].position = i
    db.session.commit()
    return {"ok": True}


@app.route("/admin/rancho/<int:rid>/fotos/excluir-todas", methods=["POST"])
@panel_required
def admin_photos_delete_all(rid):
    r = editable_rancho(rid)
    n = len(r.photos)
    gone = [p.cdn_key for p in r.photos]
    r.photos.clear()
    db.session.commit()
    bunny_delete(gone)
    flash(f"{n} foto(s) excluída(s).", "ok")
    return redirect(url_for("admin_edit", rid=rid) + "#fotos")


@app.route("/admin/rancho/<int:rid>/excluir", methods=["POST"])
@admin_required
def admin_delete(rid):
    r = db.session.get(Rancho, rid) or abort(404)
    gone = [p.cdn_key for p in r.photos]
    Event.query.filter_by(rancho_id=r.id).delete()
    db.session.delete(r)
    db.session.commit()
    bunny_delete(gone)
    flash(f"{r.name} excluído.", "ok")
    return redirect(url_for("admin_home"))


@app.route("/admin/rancho/<int:rid>/pagamento", methods=["POST"])
@admin_required
def admin_payment(rid):
    """Registra um pagamento: estende o vencimento em 1 mês ou 1 ano. Pagamento atrasado conta
    a partir de hoje, para o dono não pagar pelos dias em que o anúncio ficou vencido."""
    r = db.session.get(Rancho, rid) or abort(404)
    months = {"mes": 1, "ano": 12}.get(request.form.get("plano")) or abort(400)
    base = max(r.paid_until or today_br(), today_br())
    r.paid_until = months_later(base, months)
    db.session.commit()
    flash(f"Pagamento registrado: {r.name} pago até {r.paid_until.strftime('%d/%m/%Y')}.", "ok")
    return redirect(url_for("admin_home") + "#cobranca")


@app.route("/admin/servicos")
@admin_required
def admin_providers():
    providers = Provider.query.order_by(Provider.active.desc(), Provider.name).all()
    since = now_utc() - timedelta(days=30)
    clicks = dict(db.session.query(Event.provider_id, func.count(Event.id))
                  .filter(Event.kind == "prestador", Event.created_at >= since)
                  .group_by(Event.provider_id).all())
    return render_template("admin/providers.html", providers=providers, clicks=clicks)


@app.route("/admin/servicos/novo", methods=["GET", "POST"])
@app.route("/admin/servicos/<int:pid>", methods=["GET", "POST"])
@admin_required
def admin_provider(pid=None):
    p = (db.session.get(Provider, pid) or abort(404)) if pid else None
    if request.method == "POST":
        f = request.form
        if p is None:
            p = Provider(slug="tmp-" + secrets.token_hex(4))
            db.session.add(p)
        old_name = p.name
        p.name = f.get("name", "").strip()[:120] or "Sem nome"
        p.services = ",".join(k for k in f.getlist("services") if k in SERVICES)
        p.summary = f.get("summary", "").strip()[:200]
        p.description = f.get("description", "").replace("\r\n", "\n").strip()
        p.price_text = f.get("price_text", "").strip()[:160]
        p.whatsapp = f.get("whatsapp", "").strip()[:30]
        p.active = bool(f.get("active"))
        p.paid_until = parse_day(f.get("paid_until"))
        db.session.flush()
        if p.name != old_name:
            p.slug = unique_slug(p.name, exclude_id=p.id, model=Provider)
        added, skipped = save_uploads(p, request.files.getlist("photos"), ProviderPhoto)
        db.session.commit()
        msg = "Profissional salvo."
        if added:
            msg += f" {added} foto(s) adicionada(s)."
        if skipped:
            msg += f" {skipped} arquivo(s) ignorado(s) por não serem imagens."
        flash(msg, "ok")
        return redirect(url_for("admin_provider", pid=p.id))
    return render_template("admin/provider_edit.html", p=p,
                           trial_end=months_later(today_br(), TRIAL_MONTHS))


@app.route("/admin/servicos/<int:pid>/foto/<int:fid>/<action>", methods=["POST"])
@admin_required
def admin_provider_photo(pid, fid, action):
    p = db.session.get(Provider, pid) or abort(404)
    photo = next((x for x in p.photos if x.id == fid), None) or abort(404)
    if action == "excluir":
        key = photo.cdn_key
        p.photos.remove(photo)
        db.session.commit()
        bunny_delete([key])
    elif action == "capa":
        rest = [x for x in p.photos if x.id != fid]
        for i, x in enumerate([photo] + rest):
            x.position = i
        db.session.commit()
    else:
        abort(400)
    return redirect(url_for("admin_provider", pid=p.id) + "#fotos")


@app.route("/admin/servicos/<int:pid>/excluir", methods=["POST"])
@admin_required
def admin_provider_delete(pid):
    p = db.session.get(Provider, pid) or abort(404)
    keys = [x.cdn_key for x in p.photos]
    name = p.name
    db.session.delete(p)
    db.session.commit()
    bunny_delete(keys)
    flash(f"{name} excluído(a).", "ok")
    return redirect(url_for("admin_providers"))


@app.route("/admin/rancho/<int:rid>/alternar/<field>", methods=["POST"])
@admin_required
def admin_toggle(rid, field):
    if field not in ("active", "featured", "verified"):
        abort(400)
    r = db.session.get(Rancho, rid) or abort(404)
    if field == "verified":
        set_verified(r, not r.verified)
    else:
        setattr(r, field, not getattr(r, field))
    db.session.commit()
    return redirect(url_for("admin_home"))


@app.route("/admin/rancho/<int:rid>/relatorio")
@panel_required
def admin_report(rid):
    r = editable_rancho(rid)
    start = add_months(month_start(now_utc()), -5)
    rows = (db.session.query(Event.kind, Event.created_at)
            .filter(Event.rancho_id == r.id, Event.created_at >= start).all())
    months = []
    for i in range(6):
        m0 = add_months(start, i)
        m1 = add_months(start, i + 1)
        sel = [k for k, t in rows if m0 <= t < m1]
        months.append({
            "label": f"{MONTHS_PT[m0.month - 1]} de {m0.year}",
            "short": MONTHS_PT[m0.month - 1][:3],
            "views": sel.count("view"),                             # pessoas
            "pageviews": sel.count("view") + sel.count("reopen"),   # visualizações
            "whatsapp": sel.count("whatsapp"),
            "fav": sel.count("fav"),
        })
    months.reverse()
    cur = months[0]
    prev = months[1]
    first = (r.owner_name or "").split()[0] if r.owner_name else ""
    text = (f"Olá{(' ' + first) if first else ''}! Resumo de {cur['label']} do {r.name} no {SITE_NAME}:\n"
            f"👀 {cur['pageviews']} visualizações do anúncio, por {cur['views']} "
            f"{'pessoa' if cur['views'] == 1 else 'pessoas'}\n"
            f"💬 {cur['whatsapp']} {'pessoa clicou' if cur['whatsapp'] == 1 else 'pessoas clicaram'} "
            f"para falar com você no WhatsApp\n"
            + (f"❤️ {cur['fav']} {'pessoa salvou' if cur['fav'] == 1 else 'pessoas salvaram'} "
               f"o rancho na lista para mostrar ao grupo\n" if cur["fav"] else "")
            # no primeiro mês do anúncio não tem mês anterior para comparar
            + (f"No mês anterior foram {prev['whatsapp']} {'contato' if prev['whatsapp'] == 1 else 'contatos'}.\n"
               if prev["pageviews"] or prev["whatsapp"] else "")
            + f"Link do anúncio: {site_url()}/rancho/{r.slug}")
    wa_link = f"https://wa.me/{r.whatsapp_digits}?text={quote(text)}" if r.whatsapp_digits else ""
    peak = max([m["pageviews"] for m in months] + [1])
    return render_template("admin/report.html", r=r, months=months, text=text, wa_link=wa_link, peak=peak)


def _owner_form_errors(login, exclude_id=None):
    if not LOGIN_RE.match(login):
        return "Login inválido: use de 3 a 120 caracteres, só letras, números e @ . _ + -"
    q = Owner.query.filter_by(login=login)
    if exclude_id:
        q = q.filter(Owner.id != exclude_id)
    if q.first():
        return f"Já existe uma conta com o login {login}."
    return None


def _assign_ranchos(o, ids):
    """Liga os ranchos marcados a esta conta (tirando de quem estivesse antes) e solta os desmarcados."""
    wanted = {i for i in ids if i}
    for r in Rancho.query.filter((Rancho.owner_id == o.id) | (Rancho.id.in_(wanted or [0]))).all():
        r.owner_id = o.id if r.id in wanted else None


@app.route("/admin/donos", methods=["GET", "POST"])
@admin_required
def admin_owners():
    if request.method == "POST":
        login = normalize_login(request.form.get("login"))
        password = request.form.get("password", "").strip() or temp_password()
        err = _owner_form_errors(login)
        if not err and len(password) < MIN_PASSWORD:
            err = f"A senha provisória precisa ter pelo menos {MIN_PASSWORD} caracteres."
        if err:
            flash(err, "error")
        else:
            o = Owner(login=login, name=request.form.get("name", "").strip()[:120], must_change=True)
            o.set_password(password)
            db.session.add(o)
            db.session.flush()
            _assign_ranchos(o, [to_int(x) for x in request.form.getlist("ranchos")])
            db.session.commit()
            flash(f"Conta criada. Login: {login} · Senha provisória: {password} · Anote e passe para o dono: "
                  "ela não aparece de novo, e ele vai trocar no primeiro acesso.", "ok")
            return redirect(url_for("admin_owners"))
    owners = Owner.query.order_by(Owner.active.desc(), Owner.name, Owner.login).all()
    ranchos = Rancho.query.order_by(Rancho.name).all()
    return render_template("admin/owners.html", owners=owners, ranchos=ranchos,
                           suggestion=temp_password(), form=request.form)


@app.route("/admin/donos/<int:oid>", methods=["GET", "POST"])
@admin_required
def admin_owner(oid):
    o = db.session.get(Owner, oid) or abort(404)
    if request.method == "POST":
        login = normalize_login(request.form.get("login"))
        err = _owner_form_errors(login, exclude_id=o.id)
        if err:
            flash(err, "error")
        else:
            o.login = login
            o.name = request.form.get("name", "").strip()[:120]
            o.active = bool(request.form.get("active"))
            _assign_ranchos(o, [to_int(x) for x in request.form.getlist("ranchos")])
            db.session.commit()
            flash("Conta salva.", "ok")
            return redirect(url_for("admin_owner", oid=o.id))
    ranchos = Rancho.query.order_by(Rancho.name).all()
    return render_template("admin/owner.html", o=o, ranchos=ranchos,
                           locked=locked_minutes(throttle_key(o.login)))


@app.route("/admin/donos/<int:oid>/desbloquear", methods=["POST"])
@admin_required
def admin_owner_unlock(oid):
    o = db.session.get(Owner, oid) or abort(404)
    clear_failures(throttle_key(o.login))
    flash(f"Conta {o.login} desbloqueada.", "ok")
    return redirect(url_for("admin_owner", oid=o.id))


@app.route("/admin/donos/<int:oid>/nova-senha", methods=["POST"])
@admin_required
def admin_owner_reset(oid):
    o = db.session.get(Owner, oid) or abort(404)
    password = temp_password()
    o.set_password(password)
    o.must_change = True
    db.session.commit()
    clear_failures(throttle_key(o.login))  # senha nova também desbloqueia
    flash(f"Senha provisória nova de {o.login}: {password} · Passe para o dono: ela não aparece de novo, "
          "e ele vai trocar no próximo acesso.", "ok")
    return redirect(url_for("admin_owner", oid=o.id))


@app.route("/admin/donos/<int:oid>/excluir", methods=["POST"])
@admin_required
def admin_owner_delete(oid):
    o = db.session.get(Owner, oid) or abort(404)
    for r in o.ranchos:  # os ranchos continuam no site; só ficam sem conta de dono
        r.owner_id = None
    db.session.delete(o)
    db.session.commit()
    flash(f"Conta {o.login} excluída. Os ranchos dela continuam no site.", "ok")
    return redirect(url_for("admin_owners"))


@app.route("/admin/lead/<int:lid>/alternar", methods=["POST"])
@admin_required
def admin_lead(lid):
    lead = db.session.get(Lead, lid) or abort(404)
    lead.handled = not lead.handled
    db.session.commit()
    return redirect(url_for("admin_home") + "#pedidos")


# ---------------------------------------------------------------------------
# Demo data:  flask --app app seed-demo
# ---------------------------------------------------------------------------
@app.cli.command("seed-demo")
def seed_demo():
    """Cria 4 ranchos de exemplo com fotos geradas (só para testar)."""
    from PIL import ImageDraw
    import random

    def fake_photo(seed):
        rnd = random.Random(seed)
        w, h = 1600, 1066
        img = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(img)
        sky = (rnd.randint(120, 200), rnd.randint(170, 215), rnd.randint(215, 245))
        water = (rnd.randint(20, 60), rnd.randint(90, 130), rnd.randint(110, 150))
        horizon = int(h * rnd.uniform(0.45, 0.6))
        for y in range(horizon):
            t = y / horizon
            d.line([(0, y), (w, y)], fill=tuple(int(sky[i] * (1 - t * 0.25) + 255 * t * 0.15) for i in range(3)))
        d.rectangle([0, horizon, w, h], fill=water)
        d.polygon([(0, horizon), (w * 0.35, horizon - 70), (w * 0.7, horizon - 20), (w, horizon - 60), (w, horizon)],
                  fill=(46, 92, 52))
        sx = rnd.randint(200, w - 200)
        d.ellipse([sx - 60, horizon - 260, sx + 60, horizon - 140], fill=(255, 214, 120))
        hx = rnd.randint(150, w - 700)
        d.rectangle([hx, horizon - 40, hx + 520, horizon + 170], fill=(236, 228, 214))
        d.polygon([(hx - 40, horizon - 40), (hx + 260, horizon - 190), (hx + 560, horizon - 40)], fill=(150, 72, 48))
        d.rectangle([hx + 210, horizon + 60, hx + 300, horizon + 170], fill=(96, 64, 40))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        buf.seek(0)

        class FS:
            filename = "demo.jpg"
            stream = buf
        return FS()

    demos = [
        dict(name="Rancho Pôr do Sol", region="Beira da represa", summary="Deck na beira d'água e vista para o pôr do sol.",
             capacity=16, bedrooms=4, bathrooms=3, beds="4 casal, 8 solteiro", price_night=900, price_weekend=1700,
             price_holiday="Pacote de 3 diárias R$ 2.800", min_nights=2, checkin="14h", checkout="12h",
             amenities="piscina,beira_rio,rampa,pesca,churrasqueira,wifi,estacionamento", verified=True, featured=True),
        dict(name="Rancho Recanto do Tucunaré", region="Estrada do Porto", summary="Perfeito para pescaria com a turma.",
             capacity=12, bedrooms=3, bathrooms=2, beds="2 casal, 8 solteiro", price_night=650, price_weekend=1200,
             min_nights=2, checkin="13h", checkout="12h", amenities="beira_rio,rampa,pesca,churrasqueira,pet,som",
             verified=True),
        dict(name="Rancho Águas Claras", region="Condomínio Marina", summary="Área gourmet completa e piscina aquecida.",
             capacity=24, bedrooms=6, bathrooms=5, beds="6 casal, 12 solteiro", price_night=1500, price_weekend=2800,
             price_holiday="Réveillon: consultar", min_nights=2, checkin="15h", checkout="11h",
             amenities="piscina,beira_rio,area_gourmet,ar,wifi,churrasqueira,roupa_cama,estacionamento", featured=True),
        dict(name="Rancho da Figueira", region="Bairro Beira-Rio", summary="Simples, aconchegante e com sombra o dia todo.",
             capacity=8, bedrooms=2, bathrooms=1, beds="2 casal, 4 solteiro", price_night=380, price_weekend=700,
             min_nights=1, checkin="12h", checkout="12h", amenities="beira_rio,pesca,churrasqueira,pet"),
    ]
    desc = ("Rancho completo, com área de lazer ampla e acesso direto ao rio. Cozinha equipada com geladeira, "
            "freezer, fogão e utensílios. Varanda com redes e vista para a água.\n\n"
            "Ideal para famílias e grupos de amigos que querem descansar, pescar e fazer aquele churrasco.")
    rules = "Proibido som alto após as 22h.\nNão é permitido festa aberta ao público.\nRespeite a capacidade máxima."
    for i, dmo in enumerate(demos):
        if Rancho.query.filter_by(name=dmo["name"]).first():
            continue
        r = Rancho(slug=unique_slug(dmo["name"]), description=desc, rules=rules, owner_name="João da Silva",
                   owner_whatsapp="(16) 99999-0000", active=True, **dmo)
        db.session.add(r)
        db.session.flush()
        save_uploads(r, [fake_photo(i * 10 + k) for k in range(4)])
        # alguns cliques falsos para o relatório
        for d_ago in range(0, 150, 3):
            for _ in range(random.randint(0, 6)):
                db.session.add(Event(rancho_id=r.id, kind="view", created_at=now_utc() - timedelta(days=d_ago)))
            if random.random() < 0.5:
                db.session.add(Event(rancho_id=r.id, kind="whatsapp", created_at=now_utc() - timedelta(days=d_ago)))
    db.session.commit()
    print("Ranchos de exemplo criados.")



@app.cli.command("fotos-para-bunny")
def photos_to_bunny():
    """Move para o Bunny as fotos que ainda estão no banco (pode rodar de novo se parar no meio)."""
    if not BUNNY_ON:
        raise SystemExit("Defina BUNNY_STORAGE_URL, BUNNY_STORAGE_KEY e BUNNY_CDN_URL.")
    ids = [pid for (pid,) in db.session.query(Photo.id).filter(Photo.cdn_key == "").order_by(Photo.id)]
    print(f"{len(ids)} foto(s) no banco.")
    for n, pid in enumerate(ids, 1):
        p = db.session.get(Photo, pid)
        key = f"{BUNNY_PREFIX}/{p.rancho_id}/{p.etag or pid}-{secrets.token_hex(3)}"
        bunny_upload(key, p.full, p.thumb)
        p.cdn_key, p.full, p.thumb = key, b"", b""
        db.session.commit()  # uma por vez: se cair no meio, o que já foi fica salvo
        db.session.expunge_all()
        print(f"{n}/{len(ids)} foto {pid} -> {key}")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
