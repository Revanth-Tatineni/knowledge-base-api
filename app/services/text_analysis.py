import math
import re
from collections import Counter
from dataclasses import dataclass

WORDS_PER_MINUTE = 200
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")

STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers herself him himself his how i if in into is it
    its itself just me more most my myself no nor not now of off on once only or other our ours
    ourselves out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up very was we were
    what when where which while who whom why will with would you your yours yourself yourselves
    """.split()
)


@dataclass(frozen=True)
class TextStats:
    word_count: int
    reading_time_minutes: int
    keywords: list[str]


def analyze(title: str, content: str, max_keywords: int = 5) -> TextStats:
    words = _WORD_RE.findall(content)
    word_count = len(words)
    reading_time = math.ceil(word_count / WORDS_PER_MINUTE) if word_count else 0

    candidates = (w.lower() for w in _WORD_RE.findall(f"{title} {content}"))
    counts = Counter(
        w for w in candidates if len(w) >= 3 and w not in STOPWORDS and not w.isdigit()
    )
    # Sort by frequency, then alphabetically so ties give a stable result.
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    keywords = [word for word, _ in ranked[:max_keywords]]

    return TextStats(word_count=word_count, reading_time_minutes=reading_time, keywords=keywords)
