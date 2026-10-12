#
# text.py
#
from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"\w+")
_SPACES_PATTERN = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,;:.!?])")
_TRAILING_PUNCT = re.compile(r"[\s.!?…,;:—–-]+$")

_BOUNDARY = re.compile(r"([.!?…]+)([\"»”)\]]*)(\s+)")
_WORD_BEFORE = re.compile(r"(\w+)$")

ABBREVIATIONS = frozenset({
    "гг", "вв", "др", "пр", "им", "ул", "пл", "просп", "пер", "обл", "кв", "корп", "стр",
    "рис", "табл", "тыс", "млн", "млрд", "трлн", "руб", "коп", "долл", "англ", "лат", "рус",
    "нем", "фр", "итал", "исп", "греч", "араб", "яп", "кит", "букв", "ср", "см", "напр",
    "прим", "проф", "акад", "доц", "чл", "корр", "канд", "докт", "ген", "св", "пос", "пгт",
    "оз", "тт", "вып", "изд", "ред", "сост", "авт", "сокр", "мин", "сек", "гос", "евр",
})


def normalize_text(text: str) -> str:
    return text.lower().replace("ё", "е")


def split_words(text: str) -> list[str]:
    return _WORD_PATTERN.findall(normalize_text(text))


def collapse_spaces(text: str) -> str:
    return _SPACES_PATTERN.sub(" ", text).strip()


def remove_parenthesized(text: str) -> str:
    pairs: list[tuple[int, int]] = []
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            pairs.append((stack.pop(), i + 1))
    pairs.sort(key=lambda p: (p[0], -p[1]))
    outer: list[tuple[int, int]] = []
    last_end = -1
    for start, end in pairs:
        if start >= last_end:
            outer.append((start, end))
            last_end = end
    if not outer:
        return text
    parts: list[str] = []
    pos = 0
    for start, end in outer:
        parts.append(text[pos:start].rstrip(" \t") if start > pos else "")
        pos = end
    parts.append(text[pos:])
    result = "".join(parts)
    return _SPACE_BEFORE_PUNCT.sub(r"\1", result).strip()


def _ends_with_abbreviation(text: str, punct_start: int) -> bool:
    m = _WORD_BEFORE.search(text[max(0, punct_start - 16):punct_start])
    if not m:
        return False
    word = m.group(1)
    if len(word) == 1 and word.isalpha():
        return True
    return word.lower() in ABBREVIATIONS


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        nxt = text[m.end():m.end() + 1]
        if not nxt or nxt.islower():
            continue
        if m.group(1) == "." and _ends_with_abbreviation(text, m.start(1)):
            continue
        sentence = text[start:m.end(2)].strip()
        if sentence:
            sentences.append(sentence)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def make_summary(
    text: str | None,
    max_sentences: int = 2,
    max_chars: int | None = None,
) -> str | None:
    if not text:
        return None
    text = collapse_spaces(remove_parenthesized(text).replace("\u0301", ""))
    if not text:
        return None

    max_sentences = max(1, max_sentences)
    parts = split_sentences(text)
    truncated = len(parts) > max_sentences
    summary = " ".join(parts[:max_sentences])

    if max_chars is not None and len(summary) > max_chars:
        cut = summary[:max_chars]
        if summary[max_chars] != " " and " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        summary = cut
        truncated = True

    if truncated:
        summary = _TRAILING_PUNCT.sub("", summary) + "..."
    return summary
