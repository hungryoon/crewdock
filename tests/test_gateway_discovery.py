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
