
# ru-wiki-search

![US](https://kvaytg.ru/common/flags/us-21x16.svg) **English** | [![RU](https://kvaytg.ru/common/flags/ru-21x16.svg) Русский](README.ru.md)

![Python 3.10](https://img.shields.io/badge/Python-3.10-blue) ![PolyForm License](https://img.shields.io/badge/License-PolyForm-blue) [![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-red)](https://kvaytg.ru/donate.php?lang=en)

A lightweight library for high-speed local searching through Russian Wikipedia titles, featuring fuzzy matching and automatic summary extraction.

## 📚 Usage
```python
from wiki_search import WikiSearcher

searcher = WikiSearcher('your-email@example.com')

result = searcher.search('Великого шелкового пути')

if result:
    print(f'Title: {result["title"]}')      # Великий Шелковый Путь
    print(f'URL: {result["url"]}')          # https://ru.wikipedia.org/wiki/Великий_шёлковый_путь
    print(f'Summary: {result["summary"]}')  # Великий шёлковый путь — караванная дорога, связывавшая Восточную Азию...
```

## 📥 Installation
```bash
pip install git+https://github.com/KvaytG/ru-wiki-search.git
```

## 📝 License
Licensed under the **[PolyForm Noncommercial](LICENSE.md)** license.

This project uses open-source components. For license details see **[pyproject.toml](pyproject.toml)** and dependencies' official websites.
