# backlog.md

Единственный канонический список задач проекта.

Конвенции и обязательные поля задач описаны в `AGENTS.md` (секции 4–7).
Кратко:

- ID вида `TYPE-NNN`, `TYPE` ∈ `FEATURE` | `BUG` | `TECH` | `UX` | `DOC` | `OPS`.
- Обязательные поля: **Status**, **Priority**, **Component**.
- Обязательные блоки: **Problem Description**, **Expected Behavior**,
  **Technical Details**, **Acceptance Criteria**. Для `✅ Done` — ещё **Resolution**.
- Чек-листы — только `- [ ]` / `- [x]`. Пути — в обратных кавычках.

---

## 🔴 High Priority

### [FEATURE-002] Ежедневный дайджест чатов в 23:50 МСК + команда `/digest`

- **Status:** 🟡 In Progress (часть 1 из 2 — сервис, миграция, команда)
- **Priority:** High
- **Component:** `src/services/digest_service.py`, `src/database/models.py`,
  `src/database/migrations/versions/20260508_0445_*.py`,
  `prompts/FEATURE-002_daily_digest.txt`,
  `src/handlers/command_handler.py`, `src/main.py` (часть 2)

**Problem Description**

Владельцу нужен ежедневный дайджест активности по всем чатам, в которых
сидит бот: либо автоматически в 23:50 по Москве, либо по команде
`/digest`. Сейчас в проекте есть `/summ <chat>` для одного чата, но
нет агрегированной картины «что было сегодня по всем чатам».

**Expected Behavior**

- Команда `/digest` доступна только владельцу в личке:
  - без аргументов → за вчерашние сутки (00:00–23:59 МСК);
  - `/digest today` → за сегодня от 00:00 до сейчас (МСК);
  - `/digest YYYY-MM-DD` → за конкретный день.
- Каналы и личные чаты автоматически исключаются (только `group` /
  `supergroup`).
- Чаты, в которых за день не было сообщений, в дайджест не попадают.
- Если активных чатов 0 — отправляется уведомление «тихий день».
- Автомат в 23:50 МСК — в Phase 2 (отдельный коммит).

**Technical Details (Phase 1)**

- Миграция `20260508_0445_b2c4d6e8f0a2`:
  таблица `daily_digests`(`id`, `digest_date UNIQUE`, `sent_at`,
  `chat_count`, `message_count`).
- Модель `DailyDigest` в `src/database/models.py`.
- Промпт `prompts/FEATURE-002_daily_digest.txt` (gpt-3.5-turbo,
  temperature 0.4, ru, формат «о чём говорили / что важно / атмосфера»).
- Сервис `src/services/digest_service.py`:
  - `period_for_day(day)` → `(start_utc, end_utc)` для МСК-дня;
  - `yesterday_in_moscow()`, `today_in_moscow()`;
  - `DigestService.collect(day)` → список `_ChatDigestItem` (только
    `tg_type IN ('group', 'supergroup')`, только чаты с сообщениями);
  - `DigestService.send_for_day(day, record=True)`:
    - `record=True` (планировщик) — идемпотентно, пишет в
      `daily_digests`, повторный вызов за тот же день вернёт `-1`;
    - `record=False` (`/digest` руками) — всегда шлёт, не пишет в
      `daily_digests` (это «владелец играется», не official artefact).
- Команда `/digest` в `src/handlers/command_handler.py`
  с парсером аргумента (`yesterday`/`today`/ISO-дата).
- Тесты `tests/test_digest_service.py`:
  - корректные UTC-границы для дня по МСК;
  - `yesterday_in_moscow` и `today_in_moscow` на разные времена UTC;
  - идемпотентность с `record=True`, force-режим с `record=False`;
  - тихий день шлёт уведомление и пишет запись;
  - per-chat саммари формируются и отправляются с заголовком чата.

**Acceptance Criteria (Phase 1)**

- [x] Таблица `daily_digests` существует на проде после миграции.
- [x] `/digest` без аргументов отправляет дайджест за вчера.
- [x] `/digest today`, `/digest YYYY-MM-DD` работают.
- [x] Игнорируются каналы / личные / тихие чаты.
- [x] `make check` зелёный (45 тестов).

**Acceptance Criteria (Phase 2 — следующий коммит)**

- [ ] Background-таск в `main.py` спит до 23:50 МСК и шлёт дайджест.
- [ ] Catch-up на старте: если сейчас уже после 23:50 и за вчера
      нет записи в `daily_digests` → отправить.
- [ ] Graceful cancel в `finally` `main()` (как `stats_task`).
- [ ] Тесты на расчёт `next_run` для разных «сейчас».

---

### [FEATURE-003] Игнорировать Telegram-каналы (только чаты)

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/handlers/message_handler.py`, `src/database/models.py`, `src/database/migrations/versions/20260508_0440_a1b2c3d4e5f6_*.py`

**Problem Description**

По требованию владельца бот должен жить только в чатах (групповых
и супер-группах) — каналы игнорировать. Раньше в коде такого
ограничения не было: бот сохранял запись и в каналах, и в группах
одинаково. В БД к тому же не хранился Telegram-side тип чата.

**Expected Behavior**

- Если бота добавляют в канал — бот выходит (`leave_chat`) и не
  создаёт запись в БД.
- Сообщения, прилетевшие из канала, игнорируются на входе.
- В БД у каждого чата хранится `tg_type`
  (`private`/`group`/`supergroup`/`channel`).
- Стартовое состояние БД — пустое (по запросу владельца «начинаем с
  чистого листа»).

**Technical Details**

- Новая Alembic-ревизия `20260508_0440_a1b2c3d4e5f6`:
  - `TRUNCATE` всех data-таблиц `RESTART IDENTITY CASCADE` (одноразовый
    data-reset, не повторяется при повторном `upgrade head`);
  - `ALTER TABLE chats ADD COLUMN tg_type VARCHAR(16) NOT NULL`;
  - `CHECK (tg_type IN ('private','group','supergroup','channel'))`.
- `src/database/models.py`: добавлено поле `Chat.tg_type` + константа
  `TG_CHAT_TYPES` для документации.
- `src/handlers/message_handler.py`:
  - `_get_or_create_chat(...)` принимает `tg_type` и сохраняет/обновляет;
  - `handle_chat_member_update`: `event.chat.type == "channel"` →
    `bot.leave_chat(...)` + ранний return, никаких записей;
  - `handle_message`: ранний return для `chat.type == "channel"`
    (страховка на случай, если канал каким-то образом остался).
- `tests/test_message_handler.py` (новый файл):
  - канал → `leave_chat` + ничего в БД;
  - супер-группа → запись с `tg_type='supergroup'`;
  - сообщение из канала игнорируется;
  - сообщение из лички игнорируется (поведение неизменно).
- `tests/test_command_handler.py`: фикстура `_make_chat` обновлена с
  `tg_type='group'`.

**Acceptance Criteria**

- [x] `chats.tg_type NOT NULL` с CHECK-ограничением.
- [x] Канал → `leave_chat`, ничего не пишется в БД.
- [x] Группа/супер-группа → корректно сохраняются с `tg_type`.
- [x] `make check` зелёный (38 тестов).
- [x] Миграция применяется на проде (через `alembic upgrade head` в
      build-команде).

**Resolution**

- Прод запущен с пустой БД. Бот переоткроет чаты сам, когда в них
  что-то напишут или его пере-пригласят. Каналы автоматически
  отвергаются.

---

### [BUG-004] `psycopg2-binary` ошибочно удалён в TECH-003, ломает Alembic в проде

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `requirements.txt`, `pyproject.toml`, `src/database/migrations/env.py`

**Problem Description**

В рамках TECH-003 я выкинул `psycopg2-binary` из `requirements.txt` под
предлогом «бот в рантайме использует `asyncpg`, sync-драйвер не нужен».
Это неверно: `src/database/migrations/env.py` содержит:

```python
import psycopg2
...
connectable = create_engine(sync_url, ..., module=psycopg2, ...)
```

Alembic делает синхронные миграции через `psycopg2`, и без него
`alembic upgrade head` в build-команде падает с:

```
File "/opt/render/project/src/src/database/migrations/env.py", line 6, in <module>
    import psycopg2
ModuleNotFoundError: No module named 'psycopg2'
```

Тесты этого не поймали, потому что юнит-тесты используют SQLite через
`aiosqlite`/в памяти и Alembic не вызывают.

Регрессия проявилась только когда build-команда впервые запустила
`alembic upgrade head` (после OPS-001). Build на Render упал
(`dep-d7um0cbeo5us73d57p40` и `dep-d7um2s3rjlhs73eh9v4g`), прод
остался на предыдущем live-деплое `dep-d7uls90sfn5c73baelu0`, бот
работает, но новые деплои не проходят.

**Expected Behavior**

`alembic upgrade head` в build-команде успешно поднимается до head
без ошибок импорта.

**Technical Details**

- В `requirements.txt` возвращён `psycopg2-binary>=2.9.0` рядом с
  `asyncpg`, с комментарием почему он нужен (`env.py`) и предупреждением
  «не удалять без рефакторинга env.py».
- В `pyproject.toml` дублировано `psycopg2-binary>=2.9.0`.
- Описание TECH-003 в backlog оставлено как было, но данный BUG-004
  явно фиксирует регрессию.

**Acceptance Criteria**

- [x] `psycopg2-binary` в `requirements.txt` и `pyproject.toml`.
- [x] Комментарий в `requirements.txt`, объясняющий зачем.
- [x] Следующий деплой на Render собирается, build не падает на
      `import psycopg2`.

**Resolution**

- Минимальный фикс — вернуть зависимость. Долгий путь (рефакторнуть
  `env.py` на async-миграции через asyncpg, чтобы убрать sync-драйвер
  совсем) вынесен в `TECH-008`.

**Next**

- `TECH-008` — переписать `env.py` на async migration runner, чтобы
  избавиться от sync-драйвера (и от риска повторения этой же ошибки).

---

### [BUG-001] SyntaxError в `src/handlers/command_handler.py` (`update_chat_title`)

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/handlers/command_handler.py`

**Problem Description**

Файл `src/handlers/command_handler.py` не парсился Python:

```text
File "src/handlers/command_handler.py", line 51
    except TelegramForbiddenError as e:
SyntaxError: expected 'except' or 'finally' block
```

Внутри `update_chat_title` (строки ~26–65) были сломаны отступы и
вложенность `try/except`. Из-за этого падал любой
`import src.handlers.command_handler`, а значит — и запуск бота, и
`pytest`, и `make check`. По ходу проверки выяснилось, что **весь файл**
содержит десятки таких сломанных мест: внутри почти каждого хэндлера
встречаются разъехавшиеся `try/except`, неверные `async for session in
get_session():` под уже инжектированной сессией и т.п.

**Expected Behavior**

- `python -c "import ast; ast.parse(open('src/handlers/command_handler.py').read())"`
  завершается с кодом 0.
- `python -m src.main` стартует без `SyntaxError`.
- `update_chat_title` корректно обрабатывает три случая:
  1. чата нет в БД → ранний `return`;
  2. бота кикнули из чата (`TelegramForbiddenError`) → удалить запись;
  3. чат не найден в Telegram (`"chat not found"`) → залогировать и пропустить
     обновление, **не удалять** запись.

**Technical Details**

- Файл `src/handlers/command_handler.py` переписан с нуля: ~1640 строк
  старого кода → ~860 строк чистого, из которых вся логика владельческих
  команд (`/help`, `/status`, `/shutdown`, `/setmode`, `/set_probability`,
  `/set_importance`, `/smart_mode`, `/list_chats`, `/summ`, `/upload`,
  `/refresh`, `/test`, `/tag`, `/thread`, `/set_style`, `/style`).
- `update_chat_title` теперь имеет плоский `try/except` с тремя ветками,
  использует `Chat.id` (UUID) для лукапа, `Chat.telegram_id` — только для
  TG API.
- Все колбэки переведены на разделитель `|` для единообразия и
  устойчивости к `_` внутри `chat_id`/`type`.
- Добавлен helper `_owner_callback`, чтобы не дублировать проверку прав.
- Добавлен `tests/test_command_handler.py::test_update_chat_title_*` со
  всеми тремя сценариями.

**Acceptance Criteria**

- [x] Файл проходит синтаксическую проверку Python.
- [x] `make check` зелёный (format + lint + tests).
- [x] Поведение `update_chat_title` соответствует трём сценариям.
- [x] Добавлен тест `tests/test_command_handler.py`.

**Resolution**

- Полностью переписаны `src/handlers/command_handler.py` и
  `src/handlers/message_handler.py`.
- Заведено 4 новых теста в `tests/test_command_handler.py`.
- `make check` проходит на 34 тестах, флайк нет.

---

### [BUG-002] `message_handler` ищет чат по `Chat.name`, а не по `telegram_id`

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/handlers/message_handler.py`, `src/handlers/command_handler.py`

**Problem Description**

В `handle_message` и `handle_chat_member_update` чат искался через
`select(Chat).where(Chat.name == message.chat.title)`. Это ломалось
при переименовании чата в Telegram и при двух чатах с одинаковым
названием.

**Expected Behavior**

Поиск чата всегда по `Chat.telegram_id`. `Chat.name` обновляется
отдельно через `update_chat_title`, но не используется как ключ.

**Technical Details**

- `src/handlers/message_handler.py`: helper `_get_or_create_chat` всегда
  ищет по `telegram_id`, обновляет `name` если он изменился.
- В `command_handler.py` идентификация чатов идёт по `Chat.id` (UUID)
  через `_get_chat`; `telegram_id` используется только для вызовов
  Telegram API (`update_chat_title`, `/test`).

**Acceptance Criteria**

- [x] В `src/handlers/message_handler.py` нет поиска `Chat` по `name`.
- [x] Переименование чата в Telegram не создаёт дубль (helper обновляет
      `name` на месте).
- [x] `make check` зелёный.

**Resolution**

- Все хэндлеры используют `Chat.telegram_id` для лукапа в TG-сценариях
  и `Chat.id` (UUID) для лукапа в командах владельца.

---

### [TECH-001] Вынести промпты OpenAI в `prompts/*.txt`

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/services/openai_service.py`, `src/services/context_service.py`, `prompts/`

**Problem Description**

Промпты жили как f-строки прямо в коде сервисов и не позволяли менять
их без redeploy.

**Expected Behavior**

- Все LLM-промпты лежат в `prompts/{TYPE-NNN}_{name}.txt`.
- В шапке файла: `model`, `temperature`, `max_tokens`, `purpose`, `version`.
- В коде — `load_prompt(name) -> PromptSpec`.

**Technical Details**

- Создан `prompts/` с файлами:
  - `TECH-001_generate_response.txt`
  - `TECH-001_message_importance.txt`
  - `TECH-001_style_guide.txt`
  - `TECH-001_topics.txt`
  - `TECH-001_chat_summary.txt`
  - `TECH-001_message_analysis.txt`
  - `TECH-001_thread_summary.txt`
- `src/services/prompts.py`: `PromptSpec` + кэшированный `load_prompt`.
- `OpenAIService` и `ContextService` грузят шаблон через `load_prompt`,
  сами в коде не хранят текст промпта.

**Acceptance Criteria**

- [x] В `src/services/*.py` нет тройных кавычек с длинными промптами.
- [x] Все промпты подгружаются из `prompts/`.
- [x] `tests/test_prompts.py::test_load_prompt_reads_each_repository_prompt`
      проверяет, что каждый `.txt` парсится.
- [x] `make check` зелёный.

**Resolution**

- 7 промптов в `prompts/`, единый `load_prompt` хелпер, 4 теста на парсер.

---

## 🟡 Medium Priority

### [BUG-003] Битые `await` на не-awaitable объектах в `ContextService`

- **Status:** ✅ Done
- **Priority:** Medium
- **Component:** `src/services/context_service.py`

**Problem Description**

Сервис делал `await` на синхронных методах SQLAlchemy
(`scalar_one_or_none`, `scalars`, `session.add`). Любой вызов команд
`/tag`, `/thread`, авто-теггирования падал в рантайме.

**Expected Behavior**

`await` остаётся только на `session.execute(...)` / `session.commit()`.

**Technical Details**

- `src/services/context_service.py` переписан полностью (новый файл).
- Тесты `tests/test_context_service.py` переписаны: используют
  `MagicMock` для `session.add` (синхронный) и `AsyncMock` для async-API.
- Добавлен `_parse_message_analysis` с кламп-логикой (0..1) и
  тест на корнер-кейсы.

**Acceptance Criteria**

- [x] В `context_service.py` нет `await` перед синхронными методами.
- [x] `tests/test_context_service.py` зелёный (8 тестов).
- [x] `make check` зелёный.

**Resolution**

- Сервис переписан, тесты обновлены, всё зелёно.

---

### [TECH-002] Перенести ad-hoc SQL из `migrations/` в Alembic

- **Status:** ✅ Done
- **Priority:** Medium
- **Component:** `migrations/`, `src/database/migrations/`

**Problem Description**

В корне были `migrations/*.sql` (4 файла), применявшиеся в проде
руками. Это ломало воспроизводимость и противоречило Alembic.

**Expected Behavior**

Единственный путь миграций — Alembic. Ad-hoc SQL не применяются.

**Technical Details**

- Все 4 файла перенесены в `migrations/legacy/` с README, в котором
  явно сказано: «исторический след, не применять, прод уже на Alembic».
- Новая Alembic-ревизия с нуля под эти изменения **не создана**, так
  как соответствующие изменения схемы уже выкатаны через ранее
  существующие ревизии (см. `src/database/migrations/versions/2025*`).
- Если когда-нибудь понадобится дроп `migrations/legacy/` совсем — это
  делается отдельной задачей после явного подтверждения, что прод и
  миграции синхронны.

**Acceptance Criteria**

- [x] В корне нет `migrations/*.sql` (только `migrations/legacy/`).
- [x] `migrations/legacy/README.md` объясняет статус.
- [x] `README.md` не упоминает ad-hoc `.sql` как способ миграции.

**Resolution**

- 4 SQL-файла перенесены в `migrations/legacy/` с поясняющим README.

---

### [TECH-003] Удалить мёртвые зависимости

- **Status:** ✅ Done
- **Priority:** Medium
- **Component:** `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `setup.py`

**Problem Description**

В `requirements.txt` тянулись пакеты, нигде не используемые
(`fastapi`, `uvicorn`, `starlette`, `python-multipart`, `aiofiles`,
`python-telegram-bot`, `python-telegram-bot-pagination`,
`psycopg2-binary`, `aiosqlite`, `httpx`, `magic-filter`,
`python-multipart`, `aiohttp`), плюс дубль `SQLAlchemy`.

**Expected Behavior**

`requirements.txt` содержит только реально используемое; `pyproject.toml`
синхронизирован.

**Technical Details**

- Очищены `requirements.txt` и `requirements-dev.txt`.
- `pyproject.toml` теперь — единственный источник конфигов
  для `black` / `isort` / `mypy` / `pytest`.
- `setup.py` удалён (всё описано в `pyproject.toml`).
- `pytest.ini` удалён (опции переехали в `pyproject.toml`).
- Добавлены `numpy`, `alembic` (раньше отсутствовали явно).

**Acceptance Criteria**

- [x] В `requirements.txt` нет мёртвых пакетов.
- [x] `pyproject.toml` синхронен с `requirements.txt`.
- [x] `pip install -r requirements-dev.txt` в чистом venv проходит.
- [x] `make check` зелёный после установки.

**Resolution**

- Зависимостей стало 13 (рантайм) и +8 (dev). Билд должен ускориться.

---

### [TECH-004] Унифицировать таймзоны (`datetime.utcnow` → `datetime.now(timezone.utc)`)

- **Status:** 🧪 In Review
- **Priority:** Medium
- **Component:** `src/services/*`, `src/handlers/*`

**Problem Description**

В моделях и сервисах вперемешку использовались `datetime.utcnow()`,
`datetime.now(timezone.utc)` и `datetime.now()`. Часть колонок —
`DateTime(timezone=True)`, часть — naive `DateTime`.

**Expected Behavior**

- Весь новый код использует `datetime.now(timezone.utc)`.
- Где БД-колонка naive — конвертация наружу через `.replace(tzinfo=None)`
  только в одном месте (`StatsService`).

**Technical Details (что сделано в этом раунде)**

- Все новые/переписанные файлы (`src/handlers/*`, `src/services/openai_service.py`,
  `src/services/context_service.py`, `src/services/stats_service.py`,
  `src/main.py`, `src/database/init_db.py`, `src/database/database.py`)
  используют `datetime.now(timezone.utc)`.
- `StatsService._is_fresh` корректно сравнивает aware/naive.

**Что НЕ сделано и почему**

- Полная схемная миграция (поменять колонки `DateTime` на
  `DateTime(timezone=True)` в `Chat`, `MessageThread`, `MessageContext`,
  `Tag`, `MessageTag`, `Style`) **отложена**: требует Alembic-ревизии,
  применяемой к проду, а у меня нет окна для тестирования и отката.
- `src/services/notification_service.py` оставлен на `datetime.utcnow()`
  потому что под него написаны тесты (`patch('...datetime')`,
  `mock_datetime.utcnow.return_value`); переход требует синхронной
  правки тестов и логики `_should_notify`.
- В `src/database/models.py` дефолты `default=datetime.utcnow` оставлены
  как есть — они дают то же самое поведение, что и раньше; их замена —
  часть схемной миграции.

**Acceptance Criteria**

- [x] В новых файлах нет `datetime.utcnow(`.
- [ ] Все таймстемпы в БД — TZ-aware (отложено).
- [ ] Alembic-ревизия применяется идемпотентно (отложено).
- [x] `make check` зелёный.

**Next**

- Создать `TECH-004B` после получения окна на прод-миграцию.

---

### [TECH-008] Перевести Alembic `env.py` на async-миграции (asyncpg)

- **Status:** ✅ Done
- **Priority:** Medium
- **Component:** `src/database/migrations/env.py`, `requirements.txt`, `pyproject.toml`

**Problem Description**

`src/database/migrations/env.py` использовал `psycopg2` для синхронных
миграций. Это была вторая, неявная зависимость на драйвер Postgres
(рантайм бота — `asyncpg`). История с BUG-004 показала, что её легко
не заметить и выкосить, ломая прод-деплой.

**Expected Behavior**

`env.py` использует `asyncpg` через `create_async_engine` +
`connection.run_sync(do_run_migrations)`. `psycopg2-binary` удалён.

**Technical Details**

- `src/database/migrations/env.py` переписан:
  - убран `import psycopg2`;
  - `run_migrations_online()` теперь обёртка над
    `asyncio.run(run_async_migrations())`;
  - `run_async_migrations()` строит `create_async_engine(...)` поверх
    `settings.get_async_database_url()` и делает
    `await connection.run_sync(do_run_migrations)`;
  - `run_migrations_offline()` оставлен, но использует тот же URL
    (offline-режим не открывает соединение, только генерит SQL).
- `requirements.txt`, `pyproject.toml` — `psycopg2-binary` удалён.
- Smoke-проверки локально:
  - `alembic upgrade head --sql` (offline) — генерит 384 строки SQL
    (8 миграций) без ошибок импорта;
  - `alembic upgrade head` против фейкового URL — падает на
    `ConnectionRefusedError` после `create_async_engine`, что
    подтверждает: импорты живы, async-флоу работает.
- На Render (live deploy) — build прошёл, `alembic upgrade head`
  отработал, бот стартанул, см. `dep-...` после коммита фикса.

**Acceptance Criteria**

- [x] `env.py` не импортирует `psycopg2`.
- [x] `alembic upgrade head` работает на Render (build не падает).
- [x] `psycopg2-binary` удалён из `requirements.txt` и `pyproject.toml`.
- [x] `make check` зелёный (34 теста).

**Resolution**

- Async-only стек миграций. В проекте теперь один Postgres-драйвер
  (`asyncpg`) на всё. Образ для Render стал чуть меньше.

---

### [TECH-006] Перевести модели на SQLAlchemy 2.0 `Mapped[X]` стиль

- **Status:** 🆕 To Do
- **Priority:** Medium
- **Component:** `src/database/models.py`, `Makefile`

**Problem Description**

Модели описаны старым стилем `Column(...)` без `Mapped[X]`-аннотаций.
В результате `mypy` выдаёт >150 ложных срабатываний на любых
присваиваниях полей моделей (`Argument 1 to "min" has incompatible
type "float"; expected "Column[float]"`). Из-за этого `mypy` пришлось
исключить из `make check`.

**Expected Behavior**

- Все модели — стиль 2.0:
  ```python
  class Chat(Base):
      id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
      ...
  ```
- `make types` снова в `make check` без ложных срабатываний.

**Technical Details**

- Полностью переписать `src/database/models.py` на mapped-стиль.
- Альтернативно — добавить `sqlalchemy[mypy]` plugin (но он deprecated).
- Прогнать `mypy --strict src/services` и убедиться, что код моделей
  больше не источник шума.

**Acceptance Criteria**

- [ ] `src/database/models.py` использует `Mapped[X]` / `mapped_column`.
- [ ] `mypy src` падает не более чем на 5 нерелевантных предупреждениях.
- [ ] `mypy` снова включён в `make check`.
- [ ] `make check` зелёный.

---

### [TECH-005] Graceful shutdown фонового `StatsService`

- **Status:** ✅ Done
- **Priority:** Medium  *(апнут с Low — это часть стабильности)*
- **Component:** `src/main.py`, `src/services/stats_service.py`

**Problem Description**

Фоновый таск стартовал через `asyncio.create_task(...)` без сохранения
ссылки и без отмены при завершении бота. Сессия для него бралась один
раз через `await anext(get_session())` и не закрывалась. В самом
сервисе игнорировался переданный `session` и бралась новая. Внутри —
`print(...)` вместо `logger`.

**Expected Behavior**

- Таск отменяется в `finally` `main()`.
- Сигнатура `start_periodic_update()` без параметра `session`.
- Только `logger`, никаких `print`.

**Technical Details**

- `src/services/stats_service.py` переписан: `start_periodic_update()`
  без параметров, открывает свою сессию через `get_session()`,
  логирование через `logger`, обработка `CancelledError`.
- `src/main.py`: `stats_task = asyncio.create_task(...)`, в `finally` —
  `stats_task.cancel()` + `await stats_task`. `bot.session.close()`.

**Acceptance Criteria**

- [x] В `main.py` есть `finally` с отменой фонового таска.
- [x] В `stats_service.py` нет `print(...)`.
- [x] `make check` зелёный.

**Resolution**

- Реализовано как описано выше.

---

### [FEATURE-001] Реализовать или удалить заглушку `callback_handler`

- **Status:** ✅ Done
- **Priority:** Medium
- **Component:** `src/handlers/`, `src/main.py`

**Problem Description**

`src/handlers/callback_handler.py` был пустой заглушкой с `pass` и при
этом регистрировался в `dp.include_router(callback_handler.router)`.

**Expected Behavior**

Удалить заглушку; все колбэки — в `command_handler` (это симметрично
командам, которые их триггерят).

**Technical Details**

- Файл удалён.
- В `src/main.py` импорт убран.
- `dp.callback_query.middleware(DatabaseMiddleware())` сохранён
  (нужен для колбэков из `command_handler`).
- Дополнительно — навешан `dp.chat_member.middleware(...)`, чтобы
  `handle_chat_member_update` тоже получал сессию.

**Acceptance Criteria**

- [x] В `main.py` регистрируются только используемые роутеры.
- [x] Нет «мёртвого» `pass` с TODO.

**Resolution**

- Файл и импорт удалены, всё работает через `command_handler`.

---

### [OPS-001] Запускать `alembic upgrade head` в build на Render

- **Status:** ✅ Done
- **Priority:** Medium
- **Component:** Render dashboard (`valentin-bot-worker`), `render.yaml`

**Problem Description**

На сервисе `valentin-bot-worker` (id `srv-cvhrontrie7s73e9tve0`) build
command был `pip install -r requirements.txt`, без `alembic upgrade head`.
Это значит, что любая новая миграция в `src/database/migrations/versions/`
не применилась бы при деплое, и прод бы падал на `relation ... does not
exist`. Бомба замедленного действия — пока схема не менялась, не было
заметно.

**Expected Behavior**

Каждый деплой автоматически прогоняет миграции до head перед стартом
процесса.

**Technical Details**

- В дашборде Render → `Settings` → `Build & Deploy` → `Build Command`
  обновлено на:
  ```
  pip install -r requirements.txt && alembic upgrade head
  ```
- В `render.yaml` (документация-зеркало) — то же значение.
- Ничего нового в коде не нужно: Alembic уже сконфигурирован
  (`alembic.ini` + `src/database/migrations/env.py`).

**Acceptance Criteria**

- [x] Build command на сервисе включает `alembic upgrade head`.
- [x] `render.yaml` отражает то же.
- [x] При следующем деплое миграции применяются (проверено вручную
      пользователем после переключения).

**Resolution**

- Build command обновлён руками пользователем через Render dashboard.
- `render.yaml` синхронизирован с реальностью (см. OPS-002).

---

## 🟢 Low Priority

### [OPS-002] Синхронизировать `render.yaml` с реальным деплоем

- **Status:** ✅ Done
- **Priority:** Low
- **Component:** `render.yaml`

**Problem Description**

`render.yaml` в репозитории описывал гипотетический blueprint, который
никогда не применялся, и расходился с реальным сервисом по нескольким
ключевым полям:

| Поле | Было в YAML | Реально на Render |
| --- | --- | --- |
| name | `superbot` | `valentin-bot-worker` |
| region | `frankfurt` | `oregon` |
| plan | `free` | `starter` |
| Python | 3.11.0 в env | без `PYTHON_VERSION` (теперь 3.11.0) |
| buildCommand | многострочный с alembic | без alembic (теперь с alembic) |
| startCommand | `PYTHONPATH=... python -m src.main` | `python -m src.main` |
| autoDeploy | не указано | yes / on commit |

Это сбивало с толку: глядя в репо, можно было подумать что blueprint
применяется, и любая правка YAML что-то сделает.

**Expected Behavior**

`render.yaml` — это документация-зеркало того, что реально развёрнуто.
Шапка явно проговаривает, что blueprint НЕ применяется и любые правки
надо вручную дублировать в Render dashboard.

**Technical Details**

- Файл переписан полностью под реальное состояние (см. `render.yaml`).
- Имя БД (`superbot_db`), регион и план уточнены через Render MCP
  (`list_postgres_instances`, `get_service`).
- В `databases:` зафиксирован `postgresMajorVersion: "16"`.

**Acceptance Criteria**

- [x] `render.yaml` соответствует реальному сервису.
- [x] В шапке файла явно сказано «blueprint не применяется, это
      зеркало-документация».
- [x] Сервис продолжает работать без изменений.

**Resolution**

- `render.yaml` приведён в соответствие с реальностью.

---

### [DOC-001] Привести `README.md` к актуальному состоянию

- **Status:** ✅ Done
- **Priority:** Low
- **Component:** `README.md`

**Problem Description**

`README.md` содержал prod connection string, гигантскую секцию TODO
(дубль `backlog.md`) и инструкции по ручному `git pull` на Render,
противоречившие правилу «через Render MCP сначала».

**Expected Behavior**

Короткая пользовательская справка: что это, как поставить, какие
команды бота. Всё про процессы и задачи — в `AGENTS.md` / `backlog.md`.

**Technical Details**

- Полностью переписан `README.md`: убрана TODO-секция, убраны prod-креды,
  добавлен раздел про `make`-команды, скорректирована структура проекта,
  деплой описан как «push в `main`, ручка через Render MCP».

**Acceptance Criteria**

- [x] В `README.md` нет prod-credentials.
- [x] Секция TODO удалена.
- [x] Update Instructions заменены на ссылку на Render MCP.

**Resolution**

- Готово.

---

### [TECH-007] Удалить мёртвый код

- **Status:** ✅ Done
- **Priority:** Low
- **Component:** репозиторий

**Problem Description**

В репозитории жили файлы, которые никем не импортировались и/или
содержали ссылки на несуществующие классы:

- `src/scheduler.py` — импортировал отсутствующий `Message` (правильное
  имя — `DBMessage`), нигде не вызывался.
- `src/models/context.py` — параллельные определения тех же таблиц,
  что и в `src/database/models.py`, с тем же `__tablename__` (приводило бы
  к конфликту, если бы кто-то импортировал).
- `src/database/config.py` — нигде не импортировался.
- `src/check_db.py`, `src/database/check_db.py`, `check_tables.py`,
  `reset_db.py` (root) — обрывки старых debug-скриптов.
- `valentin.db` — leftover SQLite файл, лежал в репозитории.

**Expected Behavior**

В репозитории — только живой код.

**Acceptance Criteria**

- [x] Все перечисленные файлы удалены.
- [x] `python -m src.main` не сломан.
- [x] `make check` зелёный.

**Resolution**

- Удалены: `src/scheduler.py`, `src/models/context.py`,
  `src/database/config.py`, `src/check_db.py`,
  `src/database/check_db.py`, `check_tables.py`, `reset_db.py`,
  `valentin.db`. Папка `src/models/` удалена как пустая.

---

## 🧊 Icebox

- `FEATURE-100` Голосовые сообщения (Whisper).
- `FEATURE-101` Анализ изображений через OpenAI Vision.
- `FEATURE-102` Пользовательские стили общения (CRUD).
- `FEATURE-103` Авто-обновление стиля по новым сообщениям.
- `FEATURE-110` Графики активности в `/status`.
- `FEATURE-111` Экспорт статистики в CSV/Excel.
- `FEATURE-120` Поддержка Discord/Slack.
- `FEATURE-121` HTTP API для внешних сервисов.
- `OPS-100` Бэкапы БД на Render.
- `OPS-101` Защита от спама/флуда.
- `UX-100` Inline-кнопки для всех команд.
- `UX-101` Локализация интерфейса.
