import pytest

from crew.core import credentials
from crew.core.errors import CredentialNotFoundError


def _cred(root, name, body):
    d = root / "data" / "credentials"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.env").write_text(body)


def test_list_credentials_lists_env_stems(tmp_path):
    _cred(tmp_path, "anthropic", "ANTHROPIC_API_KEY=a\n")
    _cred(tmp_path, "openai", "OPENAI_API_KEY=o\n")
    assert credentials.list_credentials(tmp_path) == ["anthropic", "openai"]


def test_list_credentials_empty_when_no_pool(tmp_path):
    assert credentials.list_credentials(tmp_path) == []


def test_validate_credentials_raises_for_unknown(tmp_path):
    _cred(tmp_path, "anthropic", "ANTHROPIC_API_KEY=a\n")
    credentials.validate_credentials(tmp_path, ["anthropic"])  # no raise
    with pytest.raises(CredentialNotFoundError, match="ghost"):
        credentials.validate_credentials(tmp_path, ["ghost"])


def test_credential_files_in_order(tmp_path):
    _cred(tmp_path, "a", "K=1\n")
    _cred(tmp_path, "b", "K=2\n")
    files = credentials.credential_files(tmp_path, ["a", "b"])
    assert files == [tmp_path / "data" / "credentials" / "a.env",
                     tmp_path / "data" / "credentials" / "b.env"]


def test_credential_keys_union_order_preserving(tmp_path):
    _cred(tmp_path, "a", "ANTHROPIC_API_KEY=x\nSHARED=1\n")
    _cred(tmp_path, "b", "OPENAI_API_KEY=y\nSHARED=2\n")
    assert credentials.credential_keys(tmp_path, ["a", "b"]) == \
        ["ANTHROPIC_API_KEY", "SHARED", "OPENAI_API_KEY"]
