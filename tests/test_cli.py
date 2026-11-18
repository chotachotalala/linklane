import pytest

from linklane.cli import main
from linklane.database import Database
from linklane.security import verify_password


def test_init_and_reset_local_password(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["linklane", "--data-dir", str(tmp_path), "--init-admin"])
    monkeypatch.setattr("getpass.getpass", lambda _: "local-initial-password")
    main()
    db = Database(tmp_path / "linklane.sqlite3")
    assert verify_password("local-initial-password", db.owner()["password_hash"])
    monkeypatch.setattr("sys.argv", ["linklane", "--data-dir", str(tmp_path), "--reset-password"])
    monkeypatch.setattr("getpass.getpass", lambda _: "local-updated-password")
    main()
    assert verify_password("local-updated-password", db.owner()["password_hash"])
    assert db.owner()["revision"] == 2


def test_external_binding_requires_configuration(monkeypatch):
    monkeypatch.delenv("LINKLANE_BASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["linklane", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_demo_cannot_be_exposed(monkeypatch):
    monkeypatch.setenv("LINKLANE_BASE_URL", "https://links.example.com")
    monkeypatch.setattr("sys.argv", ["linklane", "--host", "0.0.0.0", "--demo"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
