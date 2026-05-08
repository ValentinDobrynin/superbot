# prompts/

Все LLM-промпты живут здесь как `.txt` файлы. Конвенция (см. `AGENTS.md` §9):

- Имя файла: `{TYPE-NNN}_{short_name}.txt`.
- В шапке файла — комментарии-метаданные:

  ```
  # model: gpt-3.5-turbo
  # temperature: 0.7
  # purpose: Generate Valentin-style response
  # version: 1
  ```

- Тело файла — Python `str.format`-шаблон с именованными плейсхолдерами
  (`{message}`, `{context}`, …). Парсер: `src/services/prompts.py::load_prompt`.

Промпты не должны хардкодиться в коде сервисов.
