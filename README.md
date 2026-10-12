
# ru-wiki-search

![US](https://kvaytg.ru/common/flags/us-21x16.svg) **English** | [![RU](https://kvaytg.ru/common/flags/ru-21x16.svg) Русский](README.ru.md)

![Python 3.10](https://img.shields.io/badge/Python-3.10-blue) ![PolyForm License](https://img.shields.io/badge/License-PolyForm-blue) [![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-red)](https://kvaytg.ru/donate.php?lang=en)

A lightweight library for high-speed local searching through Russian Wikipedia titles, featuring fuzzy matching and automatic summary extraction.

## 📚 Usage
```python
from wiki_search import WikiSearcher

with WikiSearcher('your-email@example.com') as searcher:
    result = searcher.search('Великого шелкового пути')

    if result:
        print(f'Title: {result.title}')      # Великий шёлковый путь
        print(f'URL: {result.url}')          # https://ru.wikipedia.org/wiki/Великий_шёлковый_путь
        print(f'Summary: {result.summary}')  # Великий шёлковый путь — караванная дорога, связывавшая Восточную Азию...
```

More than one answer, or titles only:
```python
searcher.search_many('Пушкин', limit=5)   # up to 5 different articles (redirects to one article are merged)
searcher.suggest('Пушкин', limit=5)       # best titles from the local index, no network requests
```

`SearchResult` fields: `title` (article title after redirects), `url`, `summary`, `matched_title` (what matched in the local index), `description` (short Wikidata description) and `is_disambiguation`. Dict-style access (`result["title"]`) still works.

`search()` tries the next candidate if the best title no longer exists. "Not found" gives `None`; network failures raise `WikiApiError`.

Options: `WikiSearcher(email=None, *, user_agent=None, data_dir=None, ranking=None, summary_sentences=2, max_summary_chars=None, fallback_candidates=5, session=None, load_index=True, ...)`.
Pass `user_agent="MyApp/1.0 (contact@example.com)"` instead of an e-mail if you prefer.

## 💾 First run and index storage
On first start the library downloads the Wikipedia titles dump and builds a local SQLite index. **This takes a while** (every title is lemmatized), so the constructor blocks; pass `load_index=False` and call `searcher.load()` later if that is a problem. It happens once.

- The index lives in the user cache directory (`~/.cache/ru-wiki-search` on Linux), not inside the package. Override with `data_dir=...` or the `RU_WIKI_SEARCH_DATA_DIR` environment variable.
- The build is atomic: an interrupted build (Ctrl+C, crash, no network) leaves no broken index, and the next start continues from the downloaded archive. Parallel processes are serialized with a file lock.
- Titles in Cyrillic and Latin letters, digits and punctuation are indexed (e.g. `Python`, `Wi-Fi`). Titles with other scripts are skipped.
- `searcher.index_info()` returns the dump date and size. The index is **not** updated automatically; delete the data directory to rebuild it from the latest dump.

## 📥 Installation
```bash
pip install git+https://github.com/KvaytG/ru-wiki-search.git
```

## 📝 License
Licensed under the **[PolyForm Noncommercial](LICENSE.md)** license — commercial use is not permitted.

This project uses open-source components. For license details see **[pyproject.toml](pyproject.toml)** and dependencies' official websites.
