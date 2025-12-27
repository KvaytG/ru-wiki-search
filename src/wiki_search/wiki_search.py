import re
from functools import lru_cache
from typing import Optional
import regex
import wikipediaapi
from .internal.wiki_title_finder import WikiTitleFinder

USER_AGENT = "RuWikiSearch/1.0.0 (kvaytg0@gmail.com)"

BRACKET_PATTERN = regex.compile(r'\s*\((?:[^()]+|(?R))*\)')
SENTENCES_PATTERN = re.compile(r'(?<=[.!?])\s+')
SENTENCE_END_PATTERN = re.compile(r'[.!?]$')

class WikiSearch:
    def __init__(self):
        self._wiki = wikipediaapi.Wikipedia(
            language='ru',
            extract_format=wikipediaapi.ExtractFormat.WIKI,
            user_agent=USER_AGENT
        )
        self._wiki_title_finder = WikiTitleFinder()
        self._wiki_title_finder.load()

    @staticmethod
    def _get_sentences(text: str, count: int)-> list[str]:
        return [s.strip() for s in SENTENCES_PATTERN.split(text) if s.strip()][:count]

    @lru_cache(maxsize=100)
    def search(self, query: str) -> Optional[dict]:
        query = query.strip()
        results = self._wiki_title_finder.find(query, 1)
        if not results:
            return None
        title = results[0]
        page = self._wiki.page(title)
        if page.exists:
            summary = None
            if page.summary:
                summary = BRACKET_PATTERN.sub('', page.summary)
                sentences = self._get_sentences(summary, 2)
                summary = ' '.join(sentences).replace('\u0301', '')
                summary = SENTENCE_END_PATTERN.sub('', summary) + '...'
            return {
                'title': title,
                'url': page.canonicalurl,
                'summary': summary
            }
        else:
            return None
