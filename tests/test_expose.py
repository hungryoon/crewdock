import pytest

from crew.core import expose
from crew.core.errors import ExposeError


def _setup_shared(root, body):
    inst = root / "instances"
    inst.mkdir(exist_ok=True)
    (inst / "_shared.env").write_text(body)


def test_load_expose_config_reads_shared_env(tmp_path):
    _setup_shared(tmp_path,
        "CREW_GOOGLE_CLIENT_ID=cid\n"
        "CREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "a" * 32 + "\n"
        "CREW_ALLOWED_EMAILS=a@x.com, b@y.com\n")
    cfg = expose.load_expose_config(tmp_path)
    assert cfg.client_id == "cid"
    assert cfg.client_secret == "sec"
    assert cfg.cookie_secret == "a" * 32
    assert cfg.allowed_emails == ["a@x.com", "b@y.com"]


def test_load_expose_config_missing_secret_raises(tmp_path):
    _setup_shared(tmp_path, "CREW_GOOGLE_CLIENT_ID=cid\n")
    with pytest.raises(ExposeError, match="CREW_GOOGLE_CLIENT_SECRET"):
        expose.load_expose_config(tmp_path)


def test_load_expose_config_allows_missing_emails(tmp_path):
    _setup_shared(tmp_path,
        "CREW_GOOGLE_CLIENT_ID=cid\n"
        "CREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "z" * 32 + "\n")
    cfg = expose.load_expose_config(tmp_path)
    assert cfg.allowed_emails == []
