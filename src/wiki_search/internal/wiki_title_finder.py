import gzip
import os
import re
import sqlite3
import string
import pathlib
import pymorphy3
import requests
from rapidfuzz import fuzz
from tqdm import tqdm

CURRENT_DIR = pathlib.Path(__file__).parent.resolve()
RESOURCES_PATH = CURRENT_DIR.parent / "resources"


class WikiTitleFinder:
    def __init__(self):
        self._db_file = os.path.join(RESOURCES_PATH, "wiki-titles.db")
        self._archive_file = os.path.join(RESOURCES_PATH, "ru-wiki-latest-all-titles.gz")
        self._morph = pymorphy3.MorphAnalyzer()
        self._lemma_cache = {}
        self._conn = None
        self._is_loaded = False
        self._word_pattern = re.compile(r'\w+')

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.lower().replace('ё', 'е')

    def _get_lemma(self, word: str) -> str:
        word = self._normalize_text(word)
        if word not in self._lemma_cache:
            self._lemma_cache[word] = self._morph.parse(word)[0].normal_form.replace('ё', 'е')
        return self._lemma_cache[word]

    def _lemmatize_text(self, text: str):
        words = self._word_pattern.findall(self._normalize_text(text))
        return " ".join([self._get_lemma(w) for w in words])

    def _download_and_build(self):
        os.makedirs(RESOURCES_PATH, exist_ok=True)
        url = "https://dumps.wikimedia.org/ruwiki/latest/ruwiki-latest-all-titles-in-ns0.gz"
        try:
            if not os.path.exists(self._archive_file):
                response = requests.get(url, stream=True)
                total = int(response.headers.get('content-length', 0))
                with tqdm(total=total, unit='iB', unit_scale=True, desc="Loading the dump", ncols=100) as pbar:
                    with open(self._archive_file, 'wb') as f:
                        for data in response.iter_content(4096):
                            f.write(data)
                            pbar.update(len(data))
            conn = sqlite3.connect(self._db_file)
            cursor = conn.cursor()
            cursor.execute('CREATE VIRTUAL TABLE titles_fts USING fts5(title, lemmas, tokenize="trigram")')
            _ru_pattern = re.compile(r'^[а-яА-ЯёЁ\s\d' + re.escape(string.punctuation + '–«»') + r']+$')
            seen = set()
            batch = []
            with gzip.open(self._archive_file, 'rt', encoding='utf-8') as f:
                for line in tqdm(f, desc="Creating the database", unit="стр", ncols=100):
                    title = line.replace('_', ' ').strip()
                    if len(title) >= 3 and _ru_pattern.match(title):
                        lower_t = self._normalize_text(title)
                        if lower_t not in seen:
                            seen.add(lower_t)
                            batch.append((title, self._lemmatize_text(title)))
                            if len(batch) >= 50000:
                                cursor.executemany("INSERT INTO titles_fts (title, lemmas) VALUES (?, ?)", batch)
                                batch = []
                                conn.commit()
            if batch:
                cursor.executemany("INSERT INTO titles_fts (title, lemmas) VALUES (?, ?)", batch)
                conn.commit()
            cursor.execute("INSERT INTO titles_fts(titles_fts) VALUES('optimize')")
            conn.commit()
            conn.close()
        finally:
            if os.path.exists(self._archive_file):
                os.remove(self._archive_file)
        self.load()

    def load(self):
        if self._is_loaded:
            return
        if not os.path.exists(self._db_file):
            self._download_and_build()
            return
        self._conn = sqlite3.connect(self._db_file, check_same_thread=False)
        self._is_loaded = True

    def find(self, query: str, top_n: int) -> list[str]:
        if not self._is_loaded or self._conn is None:
            raise RuntimeError("It is necessary to call .load() before use .find()")
        raw_words = self._word_pattern.findall(query.lower())
        if not raw_words: return []
        search_terms = []
        for w in raw_words:
            w = w.replace('"', '""')
            search_terms.append(f'"{w}"')
            lemma = self._get_lemma(w)
            if lemma != w:
                search_terms.append(f'"{lemma}"')
        match_query = " OR ".join(search_terms)
        cursor = self._conn.cursor()
        try:
            cursor.execute("""
                SELECT title, lemmas 
                FROM titles_fts 
                WHERE titles_fts MATCH ? 
                ORDER BY rank 
                LIMIT 500
            """, (match_query,))
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return []
        if not rows: return []
        query_lower = query.lower()
        query_lemmas = " ".join([self._get_lemma(w) for w in raw_words])

        def score_func(row):
            title, lemmas = row
            title_lower = title.lower()
            if query_lower == title_lower: return 200.0
            score_raw = fuzz.WRatio(query_lower, title_lower)
            score_lemma = fuzz.token_set_ratio(query_lemmas, lemmas)
            word_matches = sum(1 for w in raw_words if w in title_lower or self._get_lemma(w) in lemmas)
            bonus = (word_matches / len(raw_words)) * 20
            length_penalty = 1.0 - (min(abs(len(query_lower) - len(title_lower)), 20) / 40)
            return (score_raw * 0.4 + score_lemma * 0.4 + bonus) * length_penalty

        ranked = sorted(rows, key=score_func, reverse=True)
        return [item[0] for item in ranked[:top_n]]

    def __del__(self):
        if hasattr(self, '_conn') and self._conn:
            self._conn.close()
