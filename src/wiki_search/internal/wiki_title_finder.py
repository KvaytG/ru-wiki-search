#
# wiki_title_finder.py
#

import gzip
import os
import pathlib
import re
import sqlite3
import string
import pymorphy3
import requests
from .scoring import calculate_score

_CURRENT_DIR = pathlib.Path(__file__).parent.resolve()
_RESOURCES_PATH = _CURRENT_DIR.parent / "resources"


class RankingConfig:
    """ Параметры подобраны эмпирически """
    W_SIM = 2.1599
    W_RAW_RATIO = 0.3250
    EXACT_BONUS = 0.3274
    EXACT_LEMMA_RATIO = 0.2627
    BRACKETS_PENALTY = 0.9991
    W_LEN_PENALTY = 0.0000


class WikiTitleFinder:
    def __init__(self, user_agent: str):
        self._user_agent = user_agent
        self._config = RankingConfig()
        self._db_file = os.path.join(_RESOURCES_PATH, "wiki-titles.db")
        self._archive_file = os.path.join(_RESOURCES_PATH, "ru-wiki-latest-all-titles.gz")
        self._morph = pymorphy3.MorphAnalyzer()
        self._lemma_cache = {}
        self._conn = None
        self._is_loaded = False
        self._word_pattern = re.compile(r'[а-яА-ЯёЁ\w]+')

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.lower().replace('ё', 'е')

    def _get_lemma(self, word: str) -> str:
        word = self._normalize_text(word)
        if word not in self._lemma_cache:
            self._lemma_cache[word] = self._morph.parse(word)[0].normal_form.replace('ё', 'е')
        return self._lemma_cache[word]

    def _lemmatize_text(self, text: str) -> str:
        words = self._word_pattern.findall(self._normalize_text(text))
        return " ".join([self._get_lemma(w) for w in words])

    def _download_and_build(self):
        os.makedirs(_RESOURCES_PATH, exist_ok=True)
        url = "https://dumps.wikimedia.org/ruwiki/latest/ruwiki-latest-all-titles-in-ns0.gz"
        headers = {'User-Agent': self._user_agent}
        if not os.path.exists(self._archive_file):
            response = requests.get(url, stream=True, headers=headers)
            response.raise_for_status()
            total = int(response.headers.get('content-length', 0))
            from tqdm import tqdm
            with tqdm(total=total, unit='iB', unit_scale=True, desc="Downloading dump", ncols=100) as pbar:
                with open(self._archive_file, 'wb') as f:
                    for data in response.iter_content(chunk_size=8192):
                        f.write(data)
                        pbar.update(len(data))
        conn = None
        try:
            conn = sqlite3.connect(self._db_file)
            cursor = conn.cursor()
            cursor.execute('CREATE VIRTUAL TABLE titles_fts USING fts5(title, lemmas, tokenize="trigram")')
            _ru_pattern = re.compile(r'^[а-яА-ЯёЁ\s\d' + re.escape(string.punctuation + '–«»') + r']+$')
            seen = set()
            batch = []
            with gzip.open(self._archive_file, 'rt', encoding='utf-8') as f:
                from tqdm import tqdm
                for line in tqdm(f, desc="Building DB", unit="line", ncols=100):
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
            conn = None
        except Exception as e:
            if conn:
                conn.close()
            if os.path.exists(self._db_file):
                os.remove(self._db_file)
            raise RuntimeError(f"Failed to build DB: {e}")
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

    def find(self, query: str, top_n: int = 10) -> list[str]:
        if not self._is_loaded or self._conn is None:
            raise RuntimeError("Call .load() first")
        raw_words = self._word_pattern.findall(self._normalize_text(query))
        if not raw_words:
            return []
        word_groups = []
        for w in raw_words:
            w_esc = w.replace('"', '""')
            lemma = self._get_lemma(w)
            if lemma != w:
                word_groups.append(f'("{w_esc}" OR "{lemma}")')
            else:
                word_groups.append(f'"{w_esc}"')
        cursor = self._conn.cursor()
        rows = []
        strict_match_query = " AND ".join(word_groups)
        try:
            cursor.execute(
                "SELECT title, lemmas FROM titles_fts WHERE titles_fts MATCH ? ORDER BY rank LIMIT 1000",
                (strict_match_query,)
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            pass
        if not rows:
            soft_match_query = " OR ".join(word_groups)
            try:
                cursor.execute(
                    "SELECT title, lemmas FROM titles_fts WHERE titles_fts MATCH ? ORDER BY rank LIMIT 1000",
                    (soft_match_query,)
                )
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                return []
        if not rows:
            return []
        query_lemmas = self._lemmatize_text(query)

        def score_func(row: tuple) -> float:
            title, lemmas = row[0], row[1]
            return calculate_score(
                query=query,
                title=title,
                query_lemmas=query_lemmas,
                title_lemmas=lemmas,
                w_sim=self._config.W_SIM,
                w_raw_ratio=self._config.W_RAW_RATIO,
                exact_bonus=self._config.EXACT_BONUS,
                exact_lemma_ratio=self._config.EXACT_LEMMA_RATIO,
                brackets_penalty=self._config.BRACKETS_PENALTY,
                w_len_penalty=self._config.W_LEN_PENALTY,
            )

        ranked = sorted(rows, key=score_func, reverse=True)
        return [item[0] for item in ranked[:top_n]]

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._is_loaded = False

    def __del__(self):
        self.close()
