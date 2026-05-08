# SuperBot (vAIlentin 2.0)

Telegram-бот, который имитирует стиль общения владельца в групповых чатах:
читает историю, учится стилю, оценивает важность сообщений и отвечает
там, где это уместно.

> Это пользовательская справка. Правила работы агента, продуктовый контекст
> и список задач лежат в `AGENTS.md`, `project_description.md` и `backlog.md`.

## Возможности

- 🤖 Ответы в стиле владельца (OpenAI GPT)
- 🎨 Три типа стиля: `work`, `friendly`, `mixed`
- 🎯 Smart-режим: GPT оценивает важность сообщения и решает, отвечать ли
- 🎲 Probability-режим: ответ с заданной вероятностью
- 🔇 Silent-режим: бот молча копит контекст
- 📈 Статистика по чатам, top-words / top-emoji / тренд активности
- 📝 Тегирование сообщений и треды
- 📦 Загрузка дампов переписки для обучения стилю

## Требования

- Python 3.11+
- PostgreSQL 13+
- Telegram Bot Token, OpenAI API Key, ваш Telegram user ID

## Установка

```bash
git clone https://github.com/ValentinDobrynin/superbot.git
cd superbot

python -m venv venv
source venv/bin/activate

pip install -r requirements-dev.txt
```

Создайте `.env` в корне проекта:

```env
BOT_TOKEN=...
OPENAI_API_KEY=...
OWNER_ID=...
DATABASE_URL=postgresql+asyncpg://user:password@localhost/superbot
```

Примените миграции и запустите:

```bash
make migrate
make run
```

## Команды разработчика

Канонические проверки — через `make`:

| Команда           | Что делает                                       |
| ----------------- | ------------------------------------------------ |
| `make check`      | format-check + lint + types + tests              |
| `make format`     | автоформат (`isort` + `black`)                   |
| `make lint`       | `flake8`                                         |
| `make types`      | `mypy` (мягкий режим)                            |
| `make test`       | `pytest`                                         |
| `make migrate`    | `alembic upgrade head`                           |
| `make revision`   | `alembic revision -m "..."` (требует `m="..."`) |
| `make run`        | запустить бота локально                          |
| `make reset-db`   | пересоздать локальную БД (DESTRUCTIVE)           |
| `make help`       | список команд                                    |

## Команды бота

Все команды управления отправляются в **личный чат** с ботом и работают
только для пользователя из `OWNER_ID`.

### Статус и аналитика

- `/help` — справка по командам
- `/status` — статус бота и статистика по выбранному чату
- `/list_chats` — все чаты со своими настройками
- `/summ` — пересказ переписки по периоду

### Настройки чата

- `/setmode` — переключить silent-режим
- `/smart_mode` — переключить smart-режим
- `/set_probability` — вероятность ответа (0/25/50/75/100%)
- `/set_importance` — порог важности для smart-режима
- `/set_style` — стиль чата (`work` / `friendly` / `mixed`)

### Обучение и тестирование

- `/upload` — загрузить дамп переписки (.txt или JSON-экспорт Telegram)
- `/refresh` — пересобрать стиль из истории сообщений
- `/test` — отправить тестовое сообщение в выбранный чат

### Контент

- `/tag add|remove|list <message_id> [<tag>]` / `/tag stats`
- `/thread info|list|new|close <chat_telegram_id> [<topic>]`

### Системное

- `/shutdown` — глобальный silent (все чаты в silent), повторный вызов снимает
- `/style` — посмотреть текущие стилевые профили

## База данных

Миграции — Alembic, конфиг `src/alembic.ini`, ревизии в
`src/database/migrations/versions/`.

```bash
make migrate                   # alembic upgrade head
make revision m="add foo bar"  # alembic revision -m ...
```

Папка `migrations/legacy/` — исторические `.sql` скрипты, которые когда-то
применялись руками. Применять их вручную больше не нужно (см. `TECH-002`).

## Деплой (Render)

Деплой автоматический по push в `main`: см. `render.yaml`. Билд
запускает `alembic upgrade head` перед стартом.

Любые ручные действия на Render (рестарт, env vars, логи) — **через Render
MCP**, как описано в `AGENTS.md` §10.

## Разработка

Структура:

```
superbot/
├── AGENTS.md / CLAUDE.md
├── project_description.md
├── backlog.md
├── README.md
├── Makefile
├── pyproject.toml / requirements*.txt
├── render.yaml / Dockerfile / alembic.ini
├── prompts/                   # LLM-промпты
├── migrations/legacy/         # исторические SQL-скрипты
├── src/
│   ├── main.py
│   ├── config.py / middleware.py / lock.py
│   ├── handlers/              # aiogram-роутеры (тонкие)
│   ├── services/              # бизнес-логика и OpenAI
│   └── database/              # модели + Alembic
└── tests/
```

Конвенции и процессы — `AGENTS.md`, текущие задачи — `backlog.md`.

## Лицензия

MIT — см. [`LICENSE`](LICENSE).
