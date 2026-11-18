import argparse
import getpass
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .config import Config
from .database import Database
from .demo import seed_demo
from .security import password_hash
from .web import create_app


def main():
    parser = argparse.ArgumentParser(description="Linklane — личный сервис коротких ссылок")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--open", action="store_true", help="Открыть браузер после запуска")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument(
        "--init-admin", action="store_true", help="Создать владельца через терминал"
    )
    parser.add_argument(
        "--reset-password", action="store_true", help="Сменить пароль при локальном доступе к базе"
    )
    args = parser.parse_args()
    if args.init_admin or args.reset_password:
        data = args.data_dir or Path(os.environ.get("LINKLANE_DATA_DIR", "data"))
        database = Database(data / "linklane.sqlite3")
        exists = bool(database.owner())
        if args.init_admin and exists:
            parser.error("Владелец уже создан. Для восстановления используйте --reset-password.")
        if args.reset_password and not exists:
            parser.error("Сначала создайте владельца через --init-admin.")
        password = getpass.getpass("Новый пароль (12–200 символов): ")
        if not 12 <= len(password) <= 200:
            parser.error("Пароль должен содержать от 12 до 200 символов.")
        if password != getpass.getpass("Повторите пароль: "):
            parser.error("Пароли не совпадают.")
        if exists:
            database.change_password(password_hash(password))
        else:
            database.create_owner(password_hash(password))
        print("Пароль сохранён. Можно запускать сервер.")
        return
    local = args.host in {"127.0.0.1", "localhost", "::1"}
    if not local and not os.environ.get("LINKLANE_BASE_URL"):
        parser.error(
            "Для внешнего доступа задайте LINKLANE_BASE_URL и сначала настройте кабинет локально."
        )
    if args.demo and not local:
        parser.error("Демонстрация с известным паролем доступна только на loopback-интерфейсе.")
    data = args.data_dir or Path(
        os.environ.get("LINKLANE_DATA_DIR", ".demo" if args.demo else "data")
    )
    fallback_host = f"[{args.host}]" if ":" in args.host else args.host
    config = Config(
        data,
        os.environ.get("LINKLANE_BASE_URL", f"http://{fallback_host}:{args.port}").rstrip("/"),
        os.environ.get("LINKLANE_SECURE_COOKIES", "0") == "1",
        allow_setup=local,
    )
    if not local and (not config.base_url.startswith("https://") or not config.secure_cookies):
        parser.error(
            "Для внешнего доступа нужны HTTPS в LINKLANE_BASE_URL и LINKLANE_SECURE_COOKIES=1."
        )
    if args.demo:
        seed_demo(Database(data / "linklane.sqlite3"))
    if not local and not Database(data / "linklane.sqlite3").owner():
        parser.error("Сначала запустите сервис локально и создайте пароль владельца.")
    app = create_app(config)
    if args.open:
        timer = threading.Timer(1.2, lambda: webbrowser.open(config.base_url))
        timer.daemon = True
        timer.start()
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)
