"""Password hashing, URL validation and coarse visitor classification."""

import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit, urlunsplit


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return f"scrypt${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt, expected = encoded.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def validate_url(value: str) -> str:
    value = value.strip()
    if len(value) > 2048 or any(ord(c) < 33 or c == "\\" for c in value):
        raise ValueError("Адрес содержит недопустимые символы или длиннее 2048 символов.")
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError
        host = parts.hostname.encode("idna").decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9.:-]+", host) or host.startswith("."):
            raise ValueError
        port = f":{parts.port}" if parts.port else ""
        if ":" in host:
            host = f"[{host}]"
        return urlunsplit(
            (parts.scheme, host + port, parts.path or "/", parts.query, parts.fragment)
        )
    except (ValueError, UnicodeError) as error:
        raise ValueError(
            "Укажите корректный http:// или https:// адрес без логина и пароля."
        ) from error


def visitor_info(user_agent: str, referer: str) -> tuple[str, str]:
    agent = user_agent.lower()
    browser = next(
        (
            title
            for token, title in [
                ("edg/", "Edge"),
                ("firefox/", "Firefox"),
                ("chrome/", "Chrome"),
                ("safari/", "Safari"),
            ]
            if token in agent
        ),
        "Другое",
    )
    try:
        source = urlsplit(referer).hostname or "Прямой переход"
    except ValueError:
        source = "Прямой переход"
    return browser, source[:180]
