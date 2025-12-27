import re
from functools import lru_cache
import regex
import wikipediaapi
from .internal.constants import PROJECT_VERSION, PROJECT_NAME
from .internal.utils import is_valid_email
from .internal.wiki_title_finder import WikiTitleFinder

_BRACKET_PATTERN = regex.compile(r'\s*\((?:[^()]+|(?R))*\)')
_SENTENCES_PATTERN = re.compile(r'(?<=[.!?])\s+')
_SENTENCE_END_PATTERN = re.compile(r'[.!?]$')


class WikiSearch:
    def __init__(self, email: str):
        if not is_valid_email(email):
            raise ValueError(f"'{email}' is not a valid email address.")
        self._wiki = wikipediaapi.Wikipedia(
            language='ru',
            extract_format=wikipediaapi.ExtractFormat.WIKI,
            user_agent=f'{PROJECT_NAME}/{PROJECT_VERSION} (https://github.com/KvaytG/ru-wiki-search; {email})'
        )
        self._wiki_title_finder = WikiTitleFinder()
        self._wiki_title_finder.load()

    @staticmethod
    def _get_sentences(text: str, count: int)-> list[str]:
        return [s.strip() for s in _SENTENCES_PATTERN.split(text) if s.strip()][:count]

    @lru_cache(maxsize=100)
    def search(self, query: str) -> dict | None:
        query = query.strip()
        results = self._wiki_title_finder.find(query, 1)
        if not results:
            return None
        title = results[0]
        page = self._wiki.page(title)
        if page.exists:
            summary = None
            if page.summary:
                summary = _BRACKET_PATTERN.sub('', page.summary)
                sentences = self._get_sentences(summary, 2)
                summary = ' '.join(sentences).replace('\u0301', '')
                summary = _SENTENCE_END_PATTERN.sub('', summary) + '...'
            return {
                'title': title,
                'url': page.canonicalurl,
                'summary': summary
            }
        else:
            return None
