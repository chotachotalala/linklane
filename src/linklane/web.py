"""HTTP API and HTML pages. Public redirects never require an admin session."""

import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Config
from .database import Database
from .security import password_hash, validate_url, verify_password, visitor_info

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{2,39}$")


class LinkInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=2048)
    slug: str = Field(default="", max_length=40)
    tag: str = Field(default="", max_length=32)
    expires_at: float | None = None
    active: bool = True

    @field_validator("title", "tag")
    @classmethod
    def trim(cls, value):
        value = value.strip()
        if any(ord(c) < 32 for c in value):
            raise ValueError("Недопустимые управляющие символы.")
        return value

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, value):
        if not value:
            raise ValueError("Укажите название.")
        return value

    @field_validator("destination")
    @classmethod
    def url(cls, value):
        return validate_url(value)

    @field_validator("slug")
    @classmethod
    def slug_format(cls, value):
        value = value.strip().lower()
        if value and not SLUG.fullmatch(value):
            raise ValueError(
                "Короткий адрес: 3–40 латинских букв, цифр, дефисов или подчёркиваний."
            )
        return value

    @field_validator("expires_at")
    @classmethod
    def expiration(cls, value):
        import math

        if value is not None and (not math.isfinite(value) or value > 32503680000 or value < 0):
            raise ValueError("Некорректная дата окончания.")
        return value


class Credentials(BaseModel):
    password: str = Field(min_length=12, max_length=200)


class PasswordChange(Credentials):
    current_password: str = Field(min_length=1, max_length=200)


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def secured(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-frame-options", b"DENY"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                        ),
                    ]
                )
                if scope.get("path", "").startswith(("/api", "/app", "/login", "/setup", "/s/")):
                    headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, secured)


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.from_env()
    config.validate()
    db = Database(config.data_dir / "linklane.sqlite3")
    app = FastAPI(
        title="Linklane", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.db, app.state.config = db, config
    root = Path(__file__).parent
    templates = Jinja2Templates(directory=str(root / "templates"))
    app.mount("/static", StaticFiles(directory=str(root / "static")), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.secret(),
        session_cookie="linklane_session",
        max_age=8 * 3600,
        same_site="strict",
        https_only=config.secure_cookies,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(config.base_url).hostname])
    app.add_middleware(SecurityHeaders)

    def authenticated(request):
        owner = db.owner()
        return bool(owner and request.session.get("owner_revision") == owner["revision"])

    def csrf(request):
        expected = request.session.get("csrf", "")
        actual = request.headers.get("x-csrf-token", "")
        if not expected or not actual or not hmac.compare_digest(expected, actual):
            raise HTTPException(403, "Обновите страницу и попробуйте ещё раз.")
        if request.headers.get("origin") not in {None, config.base_url.rstrip("/")}:
            raise HTTPException(403, "Запрос отправлен с другого сайта.")

    def admin(request, *, mutation=False):
        if not authenticated(request):
            raise HTTPException(401, "Войдите в кабинет.")
        if mutation:
            csrf(request)

    def page(request, template, **context):
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(32)
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "csrf": request.session["csrf"],
                "base_url": config.base_url.rstrip("/"),
                **context,
            },
        )

    async def body(request, model):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 16_384:
                raise HTTPException(413, "Запрос слишком большой.")
        try:
            value = json.loads(data)
            return model.model_validate(value)
        except (ValueError, ValidationError, UnicodeError) as error:
            if isinstance(error, ValidationError):
                message = error.errors()[0]["msg"].removeprefix("Value error, ")
            else:
                message = "Не удалось прочитать данные запроса."
            raise HTTPException(400, message) from error

    def output(row):
        return {
            **row,
            "short_url": f"{config.base_url.rstrip('/')}/s/{row['slug']}",
            "status": "paused"
            if not row["active"]
            else "expired"
            if row["expires_at"] is not None and row["expires_at"] <= time.time()
            else "active",
        }

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": str(error.detail)}, status_code=error.status_code)
        response = page(
            request,
            "message.html",
            title="Ссылка недоступна" if error.status_code == 410 else "Страница не найдена",
            message=str(error.detail),
            status=error.status_code,
        )
        response.status_code = error.status_code
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"error": "Некорректный запрос."}, status_code=400)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def index(request: Request):
        return RedirectResponse(
            "/app" if authenticated(request) else "/login" if db.owner() else "/setup",
            status_code=303,
        )

    @app.get("/login")
    def login_page(request: Request):
        if not db.owner():
            return RedirectResponse("/setup", status_code=303)
        if authenticated(request):
            return RedirectResponse("/app", status_code=303)
        return page(request, "auth.html", setup=False)

    def can_setup(request):
        return (
            config.allow_setup
            and request.client
            and request.client.host in {"127.0.0.1", "::1", "testclient"}
        )

    @app.get("/setup")
    def setup_page(request: Request):
        if db.owner():
            return RedirectResponse("/login", status_code=303)
        if not can_setup(request):
            raise HTTPException(403, "Первую настройку нужно выполнить локально на сервере.")
        return page(request, "auth.html", setup=True)

    @app.post("/api/setup")
    async def setup(request: Request):
        if db.owner() or not can_setup(request):
            raise HTTPException(403, "Первичная настройка недоступна.")
        csrf(request)
        payload = await body(request, Credentials)
        try:
            db.create_owner(password_hash(payload.password))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "Кабинет уже настроен.") from error
        request.session.clear()
        request.session.update({"owner_revision": 1, "csrf": secrets.token_urlsafe(32)})
        return {"ok": True}

    @app.post("/api/login")
    async def login(request: Request):
        csrf(request)
        payload = await body(request, Credentials)
        subject = hashlib.sha256(
            (request.client.host if request.client else "unknown").encode()
        ).hexdigest()
        if db.throttled(subject):
            raise HTTPException(429, "Слишком много попыток. Попробуйте через 10 минут.")
        owner = db.owner()
        db.attempt(subject)
        if not owner or not verify_password(payload.password, owner["password_hash"]):
            raise HTTPException(401, "Неверный пароль.")
        request.session.clear()
        request.session.update(
            {"owner_revision": owner["revision"], "csrf": secrets.token_urlsafe(32)}
        )
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request):
        admin(request, mutation=True)
        request.session.clear()
        return {"ok": True}

    @app.post("/api/password")
    async def change_password(request: Request):
        admin(request, mutation=True)
        payload = await body(request, PasswordChange)
        if not verify_password(payload.current_password, db.owner()["password_hash"]):
            raise HTTPException(400, "Текущий пароль указан неверно.")
        db.change_password(password_hash(payload.password))
        request.session.clear()
        return {"ok": True}

    @app.get("/app")
    def dashboard(request: Request):
        if not authenticated(request):
            return RedirectResponse("/login", status_code=303)
        return page(request, "dashboard.html")

    @app.get("/api/overview")
    def overview(request: Request):
        admin(request)
        return {"links": [output(row) for row in db.list_links()], "analytics": db.analytics()}

    @app.post("/api/links", status_code=201)
    async def create_link(request: Request):
        admin(request, mutation=True)
        values = (await body(request, LinkInput)).model_dump()
        if values["expires_at"] is not None and values["expires_at"] <= time.time():
            raise HTTPException(400, "Выберите дату в будущем.")
        if values["destination"].startswith(config.base_url.rstrip("/") + "/s/"):
            raise HTTPException(400, "Укажите исходный адрес, а не короткую ссылку этого сервиса.")
        try:
            slug = db.create_link(values)
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "Этот короткий адрес уже занят.") from error
        return output(db.get_link(slug))

    @app.put("/api/links/{slug}")
    async def update_link(slug: str, request: Request):
        admin(request, mutation=True)
        values = (await body(request, LinkInput)).model_dump()
        if values["destination"].startswith(config.base_url.rstrip("/") + "/s/"):
            raise HTTPException(400, "Укажите исходный адрес, а не короткую ссылку этого сервиса.")
        if not db.update_link(slug, values):
            raise HTTPException(404, "Ссылка не найдена.")
        return output(db.get_link(slug))

    @app.delete("/api/links/{slug}")
    def delete_link(slug: str, request: Request):
        admin(request, mutation=True)
        if not db.delete_link(slug):
            raise HTTPException(404, "Ссылка не найдена.")
        return {"ok": True}

    @app.get("/api/links/{slug}/qr.svg")
    def qr_code(slug: str, request: Request):
        admin(request)
        if not db.get_link(slug):
            raise HTTPException(404, "Ссылка не найдена.")
        image = qrcode.make(
            f"{config.base_url.rstrip('/')}/s/{slug}",
            image_factory=qrcode.image.svg.SvgPathImage,
            box_size=10,
            border=4,
        )
        return Response(
            image.to_string(),
            media_type="image/svg+xml",
            headers={"Content-Disposition": f'attachment; filename="linklane-{slug}.svg"'},
        )

    @app.get("/api/export.csv")
    def export(request: Request):
        admin(request)
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            ["Название", "Короткая ссылка", "Назначение", "Метка", "Переходы", "Состояние"]
        )
        for link in db.list_links():
            row = output(link)
            # Spreadsheet applications interpret formula-like CSV cells as commands.
            cells = [
                row["title"],
                row["short_url"],
                row["destination"],
                row["tag"],
                row["clicks"],
                row["status"],
            ]
            writer.writerow(
                [
                    "'" + cell
                    if isinstance(cell, str) and cell.startswith(("=", "+", "-", "@", "\t", "\r"))
                    else cell
                    for cell in cells
                ]
            )
        return Response(
            "\ufeff" + stream.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="linklane-export.csv"'},
        )

    @app.api_route("/s/{slug}", methods=["GET", "HEAD"])
    def follow(slug: str, request: Request):
        if not SLUG.fullmatch(slug.lower()):
            raise HTTPException(404, "Такой ссылки нет.")
        browser, source = visitor_info(
            request.headers.get("user-agent", ""), request.headers.get("referer", "")
        )
        destination, status = db.follow(slug, browser, source, count=request.method == "GET")
        if not destination:
            raise HTTPException(
                status,
                "Владелец отключил ссылку или срок её действия закончился."
                if status == 410
                else "Проверьте адрес: такой ссылки нет.",
            )
        return RedirectResponse(destination, status_code=302)

    @app.get("/p/{slug}")
    def preview(slug: str, request: Request):
        link = db.get_link(slug)
        if not link:
            raise HTTPException(404, "Такой ссылки нет.")
        row = output(link)
        if row["status"] != "active":
            raise HTTPException(410, "Ссылка отключена или срок её действия закончился.")
        return page(request, "preview.html", link=row, domain=urlsplit(row["destination"]).hostname)

    return app
