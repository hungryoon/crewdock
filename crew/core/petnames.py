import random

# Short words from the EFF short wordlist (CC-BY 3.0):
# https://www.eff.org/files/2016/09/08/eff_short_wordlist_1.txt
WORDS = [
    "acorn", "apple", "bacon", "badge", "bagel", "barn", "bath", "bean",
    "bird", "blue", "boat", "bolt", "bony", "book", "boss", "brave",
    "bud", "bunch", "cabin", "cake", "cargo", "cedar", "chess", "city",
    "clay", "clip", "coach", "coast", "comet", "coral", "crisp", "daisy",
    "dawn", "deer", "delta", "dune", "ember", "fable", "fern", "ferry",
    "finch", "fox", "frost", "gem", "glade", "gold", "harbor", "hazel",
    "ivy", "jade", "kite", "lake", "leaf", "lily", "lion", "lotus",
    "maple", "mint", "moss", "oak", "ocean", "olive", "onyx", "opal",
    "otter", "owl", "peak", "pearl", "pine", "quail", "quartz", "reef",
    "river", "robin", "sage", "sky", "spark", "swan", "teal", "vine",
    "wave", "willow", "wolf", "wren",
]


def suffix() -> str:
    """A short readable token: word + two digits, e.g. 'fox42'."""
    return random.choice(WORDS) + f"{random.randint(0, 99):02d}"
