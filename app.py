"""
Ranchos — agregador de ranchos para temporada.

Público:  lista com filtros, página de cada rancho, botão de WhatsApp com contagem
          de cliques, página "Anuncie seu rancho", sitemap/robots para o Google.
Admin:    /admin — cadastro de ranchos, fotos, destaque/verificado, pedidos de
          anúncio e relatório mensal por rancho (pronto para mandar ao dono).

Banco:    DATABASE_URL (Postgres em produção). Sem ela, usa SQLite local.
Fotos:    com BUNNY_STORAGE_URL/BUNNY_STORAGE_KEY/BUNNY_CDN_URL vão para o Bunny
          Storage e são servidas pela CDN do Bunny. Sem elas, ficam no próprio banco.
"""
import hashlib
import hmac
import io
import os
import re
import secrets
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from PIL import Image, ImageOps
from sqlalchemy import exc, func
from sqlalchemy.orm import deferred
from werkzeug.middleware.proxy_fix import ProxyFix

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
}

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
    featured = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=now_utc)
    updated_at = db.Column(db.DateTime, default=now_utc, onupdate=now_utc)

    photos = db.relationship("Photo", backref="rancho", cascade="all, delete-orphan",
                             order_by="Photo.position")

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


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rancho_id = db.Column(db.Integer, db.ForeignKey("rancho.id", ondelete="CASCADE"), index=True)
    kind = db.Column(db.String(20), nullable=False)  # view | whatsapp | servico
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
    if "cdn_key" not in {c["name"] for c in db.inspect(db.engine).get_columns("photo")}:
        try:
            with db.engine.begin() as conn:
                conn.execute(db.text("ALTER TABLE photo ADD COLUMN cdn_key VARCHAR(120) DEFAULT ''"))
        except exc.DatabaseError:  # outro worker acrescentou ao mesmo tempo
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "rancho"


def unique_slug(name, exclude_id=None):
    base = slugify(name)[:100]
    slug, n = base, 2
    while True:
        q = Rancho.query.filter_by(slug=slug)
        if exclude_id:
            q = q.filter(Rancho.id != exclude_id)
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


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not is_admin():
            return redirect(url_for("admin_login", next=request.path))
        if request.method == "POST":
            check_csrf()
        return f(*a, **kw)
    return wrapper


def log_event(rancho_id, kind):
    if is_admin() or BOT_RE.search(request.headers.get("User-Agent", "")):
        return
    db.session.add(Event(rancho_id=rancho_id, kind=kind))
    db.session.commit()


def month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(dt, n):
    y, m = dt.year + (dt.month - 1 + n) // 12, (dt.month - 1 + n) % 12 + 1
    return dt.replace(year=y, month=m)


MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]


def counts_since(since, rancho_id=None):
    """{(rancho_id, kind): n} since a date."""
    q = db.session.query(Event.rancho_id, Event.kind, func.count(Event.id)).filter(Event.created_at >= since)
    if rancho_id:
        q = q.filter(Event.rancho_id == rancho_id)
    return {(r, k): n for r, k, n in q.group_by(Event.rancho_id, Event.kind).all()}


@app.context_processor
def inject_globals():
    return dict(SITE_NAME=SITE_NAME, CITY_NAME=CITY_NAME, SITE_WHATSAPP=SITE_WHATSAPP,
                AMENITIES=AMENITIES, brl=brl, csrf_token=csrf_token, is_admin=is_admin,
                site_url=site_url, year=datetime.now().year)


CANONICAL_HOST = urlparse(BASE_URL).netloc


@app.before_request
def canonical_host():
    """O site também responde em *.web.app e *.run.app; manda tudo pro domínio oficial
    para o Google não indexar cópias."""
    if CANONICAL_HOST and request.host != CANONICAL_HOST:
        code = 301 if request.method in ("GET", "HEAD") else 308
        return redirect(BASE_URL + request.full_path.rstrip("?"), code=code)


BR_TZ = ZoneInfo("America/Sao_Paulo")


@app.template_filter("local")
def local_time(dt):
    """Datas são salvas em UTC; mostra no horário de Brasília."""
    return dt.replace(tzinfo=timezone.utc).astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M") if dt else ""


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

    ranchos = Rancho.query.filter_by(active=True).all()
    total = len(ranchos)
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
        ranchos.sort(key=lambda r: (not r.featured, not r.verified, -(r.updated_at or now_utc()).timestamp()))

    filtering = bool(cap or max_price or wanted)
    return render_template("index.html", ranchos=ranchos, total=total, cap=cap, max_price=max_price,
                           wanted=wanted, order=order, filtering=filtering)


@app.route("/rancho/<slug>")
def rancho(slug):
    r = Rancho.query.filter_by(slug=slug).first_or_404()
    if not r.active and not is_admin():
        abort(404)
    seen = session.get("seen", {})
    today = datetime.now().strftime("%Y-%m-%d")
    if seen.get(str(r.id)) != today:
        log_event(r.id, "view")
        seen[str(r.id)] = today
        session["seen"] = dict(list(seen.items())[-50:])
    others = (Rancho.query.filter(Rancho.active.is_(True), Rancho.id != r.id)
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
    return render_template("rancho.html", r=r, others=others, ld=ld)


@app.route("/rancho/<slug>/whatsapp")
def rancho_whatsapp(slug):
    r = Rancho.query.filter_by(slug=slug, active=True).first_or_404()
    if not r.whatsapp_digits:
        abort(404)
    log_event(r.id, "whatsapp")
    msg = (f"Olá{(' ' + r.owner_name.split()[0]) if r.owner_name else ''}! "
           f"Vi o {r.name} no site {SITE_NAME} e gostaria de saber a disponibilidade para as datas: ")
    return redirect(f"https://wa.me/{r.whatsapp_digits}?text={quote(msg)}")


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
    body = f"User-agent: *\nDisallow: /admin\nDisallow: /rancho/*/whatsapp\nSitemap: {site_url()}/sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    base = site_url()
    urls = [(f"{base}/", None), (f"{base}/anuncie", None)]
    for r in Rancho.query.filter_by(active=True).all():
        urls.append((f"{base}/rancho/{r.slug}", r.updated_at))
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
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_PASSWORD:
        return "Defina a variável de ambiente ADMIN_PASSWORD para usar o painel.", 503
    if request.method == "POST":
        check_csrf()
        time.sleep(0.6)  # freia tentativas de adivinhar a senha
        if hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session.clear()
            session.permanent = True
            session["admin"] = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/admin") else url_for("admin_home"))
        flash("Senha incorreta.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin_home():
    ranchos = Rancho.query.order_by(Rancho.featured.desc(), Rancho.name).all()
    since = now_utc() - timedelta(days=30)
    c30 = counts_since(since)
    leads = Lead.query.order_by(Lead.handled, Lead.created_at.desc()).limit(50).all()
    totals = {
        "views": sum(n for (_, k), n in c30.items() if k == "view"),
        "whatsapp": sum(n for (_, k), n in c30.items() if k == "whatsapp"),
        "servico": sum(n for (_, k), n in c30.items() if k == "servico"),
    }
    return render_template("admin/dashboard.html", ranchos=ranchos, c30=c30, leads=leads, totals=totals)


def fill_rancho(r, form):
    r.name = form.get("name", "").strip()[:120] or "Sem nome"
    r.region = form.get("region", "").strip()[:120]
    r.summary = form.get("summary", "").strip()[:200]
    r.description = form.get("description", "").strip()
    r.capacity = to_int(form.get("capacity"))
    r.bedrooms = to_int(form.get("bedrooms"))
    r.bathrooms = to_int(form.get("bathrooms"))
    r.beds = form.get("beds", "").strip()[:160]
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
    r.owner_whatsapp = form.get("owner_whatsapp", "").strip()[:30]
    r.verified = bool(form.get("verified"))
    r.featured = bool(form.get("featured"))
    r.active = bool(form.get("active"))


def save_uploads(r, files):
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
            key = f"{BUNNY_PREFIX}/{r.id}/{etag}-{secrets.token_hex(3)}"
            bunny_upload(key, full, thumb)
            full = thumb = b""
        r.photos.append(Photo(position=pos, width=w, height=h, full=full, thumb=thumb,
                              etag=etag, cdn_key=key))
        pos += 1
        added += 1
    return added, skipped


@app.route("/admin/rancho/novo", methods=["GET", "POST"])
@app.route("/admin/rancho/<int:rid>", methods=["GET", "POST"])
@admin_required
def admin_edit(rid=None):
    r = db.session.get(Rancho, rid) if rid else None
    if rid and not r:
        abort(404)
    if request.method == "POST":
        is_new = r is None
        if is_new:
            r = Rancho(slug="tmp-" + secrets.token_hex(4))
            db.session.add(r)
        fill_rancho(r, request.form)
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
        flash(msg, "ok")
        return redirect(url_for("admin_edit", rid=r.id))
    return render_template("admin/edit.html", r=r)


@app.route("/admin/rancho/<int:rid>/foto/<int:pid>/<action>", methods=["POST"])
@admin_required
def admin_photo(rid, pid, action):
    r = db.session.get(Rancho, rid) or abort(404)
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
@admin_required
def admin_photos_upload(rid):
    """Recebe um lote de fotos (o navegador divide envios grandes em vários lotes)."""
    r = db.session.get(Rancho, rid) or abort(404)
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
@admin_required
def admin_photo_order(rid):
    """Recebe a ordem nova do arrastar-e-soltar: ids separados por vírgula."""
    r = db.session.get(Rancho, rid) or abort(404)
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
@admin_required
def admin_photos_delete_all(rid):
    r = db.session.get(Rancho, rid) or abort(404)
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


@app.route("/admin/rancho/<int:rid>/alternar/<field>", methods=["POST"])
@admin_required
def admin_toggle(rid, field):
    if field not in ("active", "featured", "verified"):
        abort(400)
    r = db.session.get(Rancho, rid) or abort(404)
    setattr(r, field, not getattr(r, field))
    db.session.commit()
    return redirect(url_for("admin_home"))


@app.route("/admin/rancho/<int:rid>/relatorio")
@admin_required
def admin_report(rid):
    r = db.session.get(Rancho, rid) or abort(404)
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
            "views": sel.count("view"),
            "whatsapp": sel.count("whatsapp"),
        })
    months.reverse()
    cur = months[0]
    prev = months[1]
    first = (r.owner_name or "").split()[0] if r.owner_name else ""
    text = (f"Olá{(' ' + first) if first else ''}! Resumo de {cur['label']} do {r.name} no {SITE_NAME}:\n"
            f"👀 {cur['views']} pessoas viram o anúncio\n"
            f"💬 {cur['whatsapp']} pessoas clicaram para falar com você no WhatsApp\n"
            f"No mês anterior foram {prev['whatsapp']} contatos.\n"
            f"Link do anúncio: {site_url()}/rancho/{r.slug}")
    wa_link = f"https://wa.me/{r.whatsapp_digits}?text={quote(text)}" if r.whatsapp_digits else ""
    peak = max([m["views"] for m in months] + [1])
    return render_template("admin/report.html", r=r, months=months, text=text, wa_link=wa_link, peak=peak)


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
