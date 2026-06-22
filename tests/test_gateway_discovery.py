from crew.gateway import discovery


def _instance(root, name, port, emails):
    d = root / "instances" / name
    d.mkdir(parents=True, exist_ok=True)
    body = f"CREW_PORT={port}\n"
    if emails is not None:
        body += f"CREW_ALLOWED_EMAILS={emails}\n"
    (d / "instance.env").write_text(body)
    return d


def _publish(root, name):
    (root / "instances" / name / "exposed").write_text("")


def test_published_instances_only_lists_marked(tmp_path):
    (tmp_path / "instances").mkdir()
    _instance(tmp_path, "alice", 9120, "a@x.com, b@y.com")
    _instance(tmp_path, "bob", 9121, "b@y.com")
    _publish(tmp_path, "alice")  # only alice published
    pubs = discovery.published_instances(tmp_path)
    assert [p.name for p in pubs] == ["alice"]
    assert pubs[0].port == 9120
    assert pubs[0].allowed_emails == ["a@x.com", "b@y.com"]


def test_union_emails_dedupes_across_published(tmp_path):
    (tmp_path / "instances").mkdir()
    _instance(tmp_path, "alice", 9120, "a@x.com, b@y.com")
    _instance(tmp_path, "bob", 9121, "b@y.com, c@z.com")
    _publish(tmp_path, "alice")
    _publish(tmp_path, "bob")
    assert discovery.union_emails(tmp_path) == ["a@x.com", "b@y.com", "c@z.com"]
