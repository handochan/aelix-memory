"""Safe FTS queries and deterministic rank fusion; scores are relevance, not truth."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "that",
        "the",
        "this",
        "to",
        "use",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        "would",
        "you",
        "your",
        "해주세요",
        "알려주세요",
        "있습니다",
        "어떻게",
        "무엇",
    ]
)


def words(text: str) -> list[str]:
    return list(dict.fromkeys(w for w in _WORDS.findall(text.casefold()) if w not in _STOP))


def grams(text: str) -> list[str]:
    # Encode each CJK gram as an ASCII token, independent of FTS tokenizer/version.
    result: dict[str, None] = {}
    for word in _CJK.findall(unicodedata.normalize("NFC", text).casefold()):
        for size in (2, 3):
            for pos in range(len(word) - size + 1):
                result["c" + word[pos : pos + size].encode("utf-8").hex()] = None
    return list(result)


def match_query(tokens: Iterable[str], limit: int = 64) -> str:
    # No raw MATCH syntax, operators, column filters, wildcards, or SQL interpolation.
    bounded = list(tokens)[:limit]
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in bounded)


def fuse(channels: dict[str, list[str]]) -> list[tuple[str, float, tuple[str, ...]]]:
    scores: dict[str, float] = defaultdict(float)
    matched: dict[str, list[str]] = defaultdict(list)
    weights = {"lexical": 1.0, "cjk": 0.7, "semantic": 1.0}
    for channel, ids in channels.items():
        for rank, memory_id in enumerate(dict.fromkeys(ids), start=1):
            scores[memory_id] += weights[channel] / (60 + rank)
            matched[memory_id].append(channel)
    return [
        (memory_id, scores[memory_id], tuple(matched[memory_id]))
        for memory_id in sorted(scores, key=lambda mid: (-scores[mid], mid))
    ]
