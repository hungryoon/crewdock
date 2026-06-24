import re
from crew.core import petnames

def test_suffix_shape():
    for _ in range(50):
        s = petnames.suffix()
        assert re.fullmatch(r"[a-z]+[0-9]{2}", s), s

def test_words_are_clean():
    assert petnames.WORDS
    for w in petnames.WORDS:
        assert re.fullmatch(r"[a-z]+", w), w
        assert 3 <= len(w) <= 8
