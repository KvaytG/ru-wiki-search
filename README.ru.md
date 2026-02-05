
# ru-wiki-search

![Python 3.11](https://img.shields.io/badge/Python-3.11-blue) ![MIT License](https://img.shields.io/badge/Лицензия-MIT-green) [![Sponsor](https://img.shields.io/badge/Поддержать-%E2%9D%A4-red)](https://kvaytg.ru/donate.php?lang=ru) [![Telegram](https://img.shields.io/badge/Telegram-Канал-blue?logo=telegram)](https://t.me/kvaytgk)

Библиотека для быстрого локального поиска по заголовкам Русской Википедии с поддержкой нечеткого сопоставления и автоматическим извлечением кратких описаний.

## 📚 Использование

```python
from wiki_search import WikiSearcher

searcher = WikiSearcher('your-email@example.com')

result = searcher.search('Единой России')

if result:
    print(f'Заголовок: {result["title"]}')  # Единая Россия
    print(f'Ссылка: {result["url"]}')       # https://ru.wikipedia.org/wiki/Единая_Россия
    print(f'Суть: {result["summary"]}')     # Всероссийская политическая партия «Единая Россия»...
```

## 📥 Установка

```bash
pip install git+https://github.com/KvaytG/ru-wiki-search.git
```

## 📝 Лицензия

Распространяется по лицензии **[MIT](LICENSE.txt)**.

Проект использует компоненты с открытым исходным кодом. Сведения о лицензиях см. в **[pyproject.toml](pyproject.toml)** и на официальных ресурсах зависимостей.
