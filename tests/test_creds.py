from crew.core.creds import parse_env_file, merge_env


def test_parse_env_file_skips_comments_and_blanks(tmp_path):
    f = tmp_path / "x.env"
    f.write_text("# comment\n\nA=1\nB = two \nMALFORMED\n")
    assert parse_env_file(f) == {"A": "1", "B": "two"}


def test_parse_missing_file_returns_empty(tmp_path):
    assert parse_env_file(tmp_path / "missing.env") == {}


def test_merge_precedence_instance_over_shared_over_defaults():
    merged = merge_env(
        defaults={"A": "d", "B": "d"},
        shared={"B": "s", "C": "s"},
        instance={"C": "i"},
    )
    assert merged == {"A": "d", "B": "s", "C": "i"}
