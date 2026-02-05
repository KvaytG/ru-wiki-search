
# ru-wiki-search

![Python 3.11](https://img.shields.io/badge/Python-3.11-blue) ![MIT License](https://img.shields.io/badge/License-MIT-green) [![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-red)](https://kvaytg.ru/donate.php?lang=en) [![Telegram](https://img.shields.io/badge/Telegram-Channel-blue?logo=telegram)](https://t.me/kvaytgk)

A lightweight library for high-speed local searching through Russian Wikipedia titles, featuring fuzzy matching and automatic summary extraction.

## 📚 Usage

```python
from wiki_search import WikiSearcher

searcher = WikiSearcher('your-email@example.com')

result = searcher.search('Единой России')

if result:
    print(f'Title: {result["title"]}')      # Единая Россия
    print(f'URL: {result["url"]}')          # https://ru.wikipedia.org/wiki/Единая_Россия
    print(f'Summary: {result["summary"]}')  # Всероссийская политическая партия «Единая Россия»...
```

## 📥 Installation
```bash
pip install git+https://github.com/KvaytG/ru-wiki-search.git
```

## 📝 License
Licensed under the **[MIT](LICENSE.txt)** license.

This project uses open-source components. For license details see **[pyproject.toml](pyproject.toml)** and dependencies' official websites.
