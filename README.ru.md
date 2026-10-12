
# ru-wiki-search

[![US](https://kvaytg.ru/common/flags/us-21x16.svg) English](README.md) | ![RU](https://kvaytg.ru/common/flags/ru-21x16.svg) **Русский**

![Python 3.10](https://img.shields.io/badge/Python-3.10-blue) ![PolyForm License](https://img.shields.io/badge/License-PolyForm-blue) [![Sponsor](https://img.shields.io/badge/Поддержать-%E2%9D%A4-red)](https://kvaytg.ru/donate.php?lang=ru)

Библиотека для быстрого локального поиска по заголовкам Русской Википедии с поддержкой нечеткого сопоставления и автоматическим извлечением кратких описаний.

```python
from wiki_search import WikiSearcher

with WikiSearcher('your-email@example.com') as searcher:
    result = searcher.search('Великого шелкового пути')

    if result:
        print(f'Заголовок: {result.title}')  # Великий шёлковый путь
        print(f'Ссылка: {result.url}')       # https://ru.wikipedia.org/wiki/Великий_шёлковый_путь
        print(f'Суть: {result.summary}')     # Великий шёлковый путь — караванная дорога, связывавшая Восточную Азию...
```

Несколько ответов или только заголовки:
```python
searcher.search_many('Пушкин', limit=5)   # до 5 разных статей (редиректы на одну статью схлопываются)
searcher.suggest('Пушкин', limit=5)       # лучшие заголовки из локального индекса, без запросов в сеть
```

Поля `SearchResult`: `title` (заголовок статьи после редиректов), `url`, `summary`, `matched_title` (что совпало в локальном индексе), `description` (короткое описание из Викиданных) и `is_disambiguation`. Доступ как к словарю (`result["title"]`) сохранён.

Если страница лучшего заголовка уже удалена, `search()` пробует следующего кандидата. «Не найдено» даёт `None`, сетевые сбои — исключение `WikiApiError`.

Параметры: `WikiSearcher(email=None, *, user_agent=None, data_dir=None, ranking=None, summary_sentences=2, max_summary_chars=None, fallback_candidates=5, session=None, load_index=True, ...)`.
Вместо e-mail можно передать `user_agent="MyApp/1.0 (contact@example.com)"`.

## 💾 Первый запуск и хранение индекса
При первом запуске библиотека скачивает дамп заголовков Википедии и строит локальный индекс SQLite. **Это занимает много времени** (каждый заголовок лемматизируется), и конструктор блокируется; если это неудобно, передайте `load_index=False` и вызовите `searcher.load()` позже. Происходит один раз.

- Индекс лежит в пользовательском кэше (`~/.cache/ru-wiki-search` в Linux), а не внутри пакета. Путь меняется параметром `data_dir=...` или переменной окружения `RU_WIKI_SEARCH_DATA_DIR`.
- Сборка атомарна: прерванная сборка (Ctrl+C, сбой, нет сети) не оставляет битого индекса, а следующий запуск продолжит со скачанного архива. Параллельные процессы синхронизируются файловой блокировкой.
- Индексируются заголовки из кириллицы, латиницы, цифр и знаков препинания (например, `Python`, `Wi-Fi`). Заголовки с другими письменностями пропускаются.
- `searcher.index_info()` возвращает дату дампа и размер. Индекс **не** обновляется автоматически: чтобы пересобрать его из свежего дампа, удалите каталог данных.

## 📥 Установка
```bash
pip install git+https://github.com/KvaytG/ru-wiki-search.git
```

## 📝 Лицензия
Распространяется по лицензии **[PolyForm Noncommercial](LICENSE.md)** — коммерческое использование не допускается.

Проект использует компоненты с открытым исходным кодом. Сведения о лицензиях см. в **[pyproject.toml](pyproject.toml)** и на официальных ресурсах зависимостей.
