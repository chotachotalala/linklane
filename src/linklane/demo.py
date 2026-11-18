"""Repeatable demonstration fixtures. Never fetch or redirect to fixture targets."""

import time

from .database import Database
from .security import password_hash

DEMO_PASSWORD = "linklane-demo-2026"


def seed_demo(db: Database):
    if db.owner():
        return
    db.create_owner(password_hash(DEMO_PASSWORD))
    samples = [
        ("portfolio", "Моё портфолио", "https://github.com/", "Личное", 84, True),
        ("python", "Документация Python", "https://docs.python.org/3/", "Разработка", 51, True),
        ("design", "Вдохновение для проекта", "https://www.figma.com/", "Дизайн", 36, True),
        ("reading", "Список для чтения", "https://www.wikipedia.org/", "Личное", 19, False),
        ("release", "Последний релиз", "https://www.python.org/downloads/", "Разработка", 27, True),
    ]
    for index, (slug, title, url, tag, clicks, active) in enumerate(samples):
        db.create_link({"slug": slug, "title": title, "destination": url, "tag": tag})
        link = db.get_link(slug)
        with db.connection() as conn:
            conn.execute(
                "UPDATE links SET clicks=?,active=?,created_at=? WHERE id=?",
                (clicks, active, time.time() - (index + 1) * 86400, link["id"]),
            )
            for visit in range(clicks):
                day = (visit * 7 + index * 3) % 14
                conn.execute(
                    "INSERT INTO visits(link_id,created_at,browser,source) VALUES (?,?,?,?)",
                    (
                        link["id"],
                        time.time() - day * 86400 - visit * 71,
                        ["Chrome", "Chrome", "Safari", "Firefox", "Edge"][visit % 5],
                        ["Прямой переход", "github.com", "t.me", "Прямой переход"][visit % 4],
                    ),
                )
