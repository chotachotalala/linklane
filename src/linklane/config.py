import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    data_dir: Path
    base_url: str = "http://127.0.0.1:8787"
    secure_cookies: bool = False
    allow_setup: bool = False
    session_secret: str | None = None

    def validate(self):
        parsed = urlsplit(self.base_url)
        _ = parsed.port
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Base URL must be an HTTP(S) origin without path or credentials.")
        if self.secure_cookies and parsed.scheme != "https":
            raise ValueError("Secure cookies require an HTTPS base URL.")

    def secret(self):
        if self.session_secret:
            return self.session_secret
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / ".session-key"
        try:
            # Exclusive creation avoids replacing the key on restart or concurrent startup.
            with path.open("x", encoding="ascii") as stream:
                stream.write(secrets.token_urlsafe(48))
            try:
                path.chmod(0o600)
            except OSError:
                pass
        except FileExistsError:
            pass
        return path.read_text(encoding="ascii").strip()

    @classmethod
    def from_env(cls):
        return cls(
            Path(os.environ.get("LINKLANE_DATA_DIR", "data")),
            os.environ.get("LINKLANE_BASE_URL", "http://127.0.0.1:8787").rstrip("/"),
            os.environ.get("LINKLANE_SECURE_COOKIES", "0") == "1",
            os.environ.get("LINKLANE_ALLOW_SETUP", "0") == "1",
        )
