
# ru-wiki-search

[![US](https://kvaytg.ru/common/flags/us-21x16.svg) English](README.md) | ![RU](https://kvaytg.ru/common/flags/ru-21x16.svg) **Русский**

![Python 3.10](https://img.shields.io/badge/Python-3.10-blue) ![PolyForm License](https://img.shields.io/badge/License-PolyForm-blue) [![Sponsor](https://img.shields.io/badge/Поддержать-%E2%9D%A4-red)](https://kvaytg.ru/donate.php?lang=ru)

Библиотека для быстрого локального поиска по заголовкам Русской Википедии с поддержкой нечеткого сопоставления и автоматическим извлечением кратких описаний.

```python
from wiki_search import WikiSearcher

searcher = WikiSearcher('your-email@example.com')

result = searcher.search('Великого шелкового пути')

if result:
    print(f'Заголовок: {result["title"]}')  # Великий Шелковый Путь
    print(f'Ссылка: {result["url"]}')       # https://ru.wikipedia.org/wiki/Великий_шёлковый_путь
    print(f'Суть: {result["summary"]}')     # Великий шёлковый путь — караванная дорога, связывавшая Восточную Азию...
```

## 📥 Установка
```bash
pip install git+https://github.com/KvaytG/ru-wiki-search.git
```

## 📝 Лицензия
Распространяется по лицензии **[PolyForm Noncommercial](LICENSE.md)**.

Проект использует компоненты с открытым исходным кодом. Сведения о лицензиях см. в **[pyproject.toml](pyproject.toml)** и на официальных ресурсах зависимостей.
