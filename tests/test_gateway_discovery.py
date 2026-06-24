from crew.gateway import discovery


def _instance(root, name, port, emails):
    d = root / "data" / "instances" / name
    d.mkdir(parents=True, exist_ok=True)
    body = f"CREW_PORT={port}\n"
    if emails is not None:
        body += f"CREW_ALLOWED_EMAILS={emails}\n"
    (d / "instance.env").write_text(body)
    return d


def test_published_instances_lists_all_with_a_port(tmp_path):
    (tmp_path / "data" / "instances").mkdir(parents=True)
    _instance(tmp_path, "alice", 9120, "a@x.com, b@y.com")
    _instance(tmp_path, "bob", 9121, None)  # no whitelist -> still listed, empty
    pubs = {p.name: p for p in discovery.published_instances(tmp_path)}
    assert set(pubs) == {"alice", "bob"}
    assert pubs["alice"].port == 9120
    assert pubs["alice"].allowed_emails == ["a@x.com", "b@y.com"]
    assert pubs["bob"].allowed_emails == []


def test_union_emails_spans_all_instances_and_dedupes(tmp_path):
    (tmp_path / "data" / "instances").mkdir(parents=True)
    _instance(tmp_path, "alice", 9120, "a@x.com, b@y.com")
    _instance(tmp_path, "bob", 9121, "b@y.com, c@z.com")
    _instance(tmp_path, "carol", 9122, None)  # empty whitelist contributes nothing
    assert discovery.union_emails(tmp_path) == ["a@x.com", "b@y.com", "c@z.com"]
