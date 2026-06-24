from crew.core import paths
from crew.gateway import discovery


def _instance(root, name, port, emails, hexid="aaaaaa"):
    """Write a hashed instance dir (data/instances/<name>-<hex>/) with meta
    {'name': <name>} + instance.env, like a real `crew create`."""
    iid = f"{name}-{hexid}"
    d = root / "data" / "instances" / iid
    d.mkdir(parents=True, exist_ok=True)
    paths.write_meta(root, iid, {"name": name})
    body = f"CREW_PORT={port}\n"
    if emails is not None:
        body += f"CREW_ALLOWED_EMAILS={emails}\n"
    (d / "instance.env").write_text(body)
    return d


def test_published_instances_uses_base_name_and_instance_id(tmp_path):
    (tmp_path / "data" / "instances").mkdir(parents=True)
    _instance(tmp_path, "ted", 9120, "a@x.com, b@y.com")
    pubs = {p.name: p for p in discovery.published_instances(tmp_path)}
    assert set(pubs) == {"ted"}
    assert pubs["ted"].instance_id == "ted-aaaaaa"
    assert pubs["ted"].port == 9120
    assert pubs["ted"].allowed_emails == ["a@x.com", "b@y.com"]


def test_published_instances_lists_all_with_a_port(tmp_path):
    (tmp_path / "data" / "instances").mkdir(parents=True)
    _instance(tmp_path, "alice", 9120, "a@x.com, b@y.com", hexid="aaaaaa")
    _instance(tmp_path, "bob", 9121, None, hexid="bbbbbb")  # no whitelist -> empty
    pubs = {p.name: p for p in discovery.published_instances(tmp_path)}
    assert set(pubs) == {"alice", "bob"}
    assert pubs["alice"].port == 9120
    assert pubs["alice"].instance_id == "alice-aaaaaa"
    assert pubs["alice"].allowed_emails == ["a@x.com", "b@y.com"]
    assert pubs["bob"].instance_id == "bob-bbbbbb"
    assert pubs["bob"].allowed_emails == []


def test_union_emails_spans_all_instances_and_dedupes(tmp_path):
    (tmp_path / "data" / "instances").mkdir(parents=True)
    _instance(tmp_path, "alice", 9120, "a@x.com, b@y.com", hexid="aaaaaa")
    _instance(tmp_path, "bob", 9121, "b@y.com, c@z.com", hexid="bbbbbb")
    _instance(tmp_path, "carol", 9122, None, hexid="cccccc")  # empty contributes nothing
    assert discovery.union_emails(tmp_path) == ["a@x.com", "b@y.com", "c@z.com"]


def test_set_instance_emails_replaces_preserving_other_keys(tmp_path):
    from crew.gateway import discovery
    from crew.core import paths
    d = tmp_path / "data" / "instances" / "alice"
    d.mkdir(parents=True)
    (d / "instance.env").write_text(
        "CREW_PORT=9120\nCREW_ALLOWED_EMAILS=old@x.com\nCREW_TZ=UTC\n")
    stored = discovery.set_instance_emails(tmp_path, "alice", ["a@x.com", "b@x.com"])
    assert stored == ["a@x.com", "b@x.com"]
    text = (d / "instance.env").read_text()
    assert "CREW_ALLOWED_EMAILS=a@x.com,b@x.com" in text
    assert "CREW_PORT=9120" in text          # other keys preserved
    assert "CREW_TZ=UTC" in text
    assert "old@x.com" not in text


def test_set_instance_emails_appends_when_absent_and_dedupes(tmp_path):
    from crew.gateway import discovery
    d = tmp_path / "data" / "instances" / "bob"
    d.mkdir(parents=True)
    (d / "instance.env").write_text("CREW_PORT=9130\n")
    stored = discovery.set_instance_emails(tmp_path, "bob", ["x@y.com", "x@y.com", " "])
    assert stored == ["x@y.com"]
    assert "CREW_ALLOWED_EMAILS=x@y.com" in (d / "instance.env").read_text()


def test_instance_emails_reads_back(tmp_path):
    from crew.gateway import discovery
    d = tmp_path / "data" / "instances" / "carol"
    d.mkdir(parents=True)
    (d / "instance.env").write_text("CREW_ALLOWED_EMAILS=c@x.com,d@x.com\n")
    assert discovery.instance_emails(tmp_path, "carol") == ["c@x.com", "d@x.com"]


def test_write_union_emails_writes_when_gateway_dir_exists(tmp_path):
    from crew.gateway import discovery
    from crew.core import paths
    a = tmp_path / "data" / "instances" / "alice"
    a.mkdir(parents=True)
    (a / "instance.env").write_text("CREW_PORT=9120\nCREW_ALLOWED_EMAILS=a@x.com\n")
    paths.gateway_dir(tmp_path).mkdir(parents=True)
    discovery.write_union_emails(tmp_path)
    assert (paths.gateway_dir(tmp_path) / "emails.txt").read_text() == "a@x.com\n"


def test_write_union_emails_noop_without_gateway_dir(tmp_path):
    from crew.gateway import discovery
    discovery.write_union_emails(tmp_path)   # must not raise
    from crew.core import paths
    assert not (paths.gateway_dir(tmp_path) / "emails.txt").exists()
