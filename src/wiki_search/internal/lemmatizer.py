#
# lemmatizer.py
#
from __future__ import annotations

import re
from functools import lru_cache

from .text import split_words

_CYRILLIC = re.compile(r"[а-яё]")


class Lemmatizer:
    def __init__(self, cache_size: int = 200_000):
        self._morph = None
        self._lemma = lru_cache(maxsize=cache_size)(self._lemma_uncached)

    def _lemma_uncached(self, word: str) -> str:
        if not _CYRILLIC.search(word):
            return word
        if self._morph is None:
            import pymorphy3
            self._morph = pymorphy3.MorphAnalyzer()
        return self._morph.parse(word)[0].normal_form.replace("ё", "е")

    def lemma(self, word: str) -> str:
        return self._lemma(word)

    def lemmatize_text(self, text: str) -> str:
        return " ".join(self._lemma(w) for w in split_words(text))
