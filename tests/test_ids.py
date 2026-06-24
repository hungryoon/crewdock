import re
from crew.core import ids


def test_token_shape():
    for _ in range(50):
        assert re.fullmatch(r"[0-9a-f]{6}", ids.token())
