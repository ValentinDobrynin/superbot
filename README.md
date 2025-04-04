# vAIlentin 2.0 Bot

Telegram бот с расширенными возможностями управления и аналитики.

## Основные возможности

### Управление режимами работы
- **Глобальный режим** (`/shutdown`) - управление работой бота во всех чатах
- **Режим чата** (`/setmode`) - включение/выключение бота в конкретном чате
- **Умный режим** (`/smart_mode`) - адаптивные ответы на основе важности сообщений

### Аналитика и статистика
- **Статус** (`/status`) - детальная статистика по всем чатам
- **Сводка чата** (`/summ`) - анализ активности и контекста чата
- **Список чатов** (`/list_chats`) - информация о всех подключенных чатах
- **Теги** (`/tag`) - управление тегами сообщений
- **Треды** (`/thread`) - управление темами обсуждений

### Настройка поведения
- **Вероятность ответа** (`/set_probability`) - настройка частоты ответов
- **Порог важности** (`/set_importance`) - настройка умного режима
- **Стиль общения** (`/set_style`) - выбор типа общения (рабочий/дружеский/смешанный)

## Команды

### Управление режимами

#### `/shutdown`
Переключает глобальный режим работы бота:
- 🔴 Включен: бот читает сообщения, но не отвечает
- 🟢 Выключен: бот работает в обычном режиме

#### `/setmode`
Управление режимом работы в конкретном чате:
- 🔇 Тихий режим: бот читает сообщения, но не отвечает
- 🔊 Обычный режим: бот работает в обычном режиме

#### `/smart_mode`
Управление умным режимом в чате:
- ✅ Включен: бот анализирует важность сообщений
- ❌ Выключен: бот отвечает на все сообщения

### Аналитика

#### `/status`
Показывает детальную статистику:
- Глобальный статус бота
- Статус каждого чата
- Статистика сообщений (24ч и 7д)
- Активность пользователей
- Пиковые часы активности
- Средняя длина сообщений

#### `/summ`
Генерирует сводку по чату:
- Основные темы обсуждений
- Активность пользователей
- Ключевые теги
- Связанные треды
- Периоды сводки:
  - 🔄 С момента последней сводки
  - 📅 Последние 24 часа
  - ⏰ Произвольный период

#### `/list_chats`
Список всех чатов с настройками:
- Название чата
- Статус активности
- Тихий режим
- Вероятность ответа
- Умный режим
- Порог важности
- Стиль общения

### Настройка

#### `/set_probability`
Устанавливает вероятность ответа:
- Кнопки: 25%, 50%, 75%, 100%
- Custom: произвольное значение (0-100%)

#### `/set_importance`
Устанавливает порог важности для умного режима:
- Кнопки: 25%, 50%, 75%
- Custom: произвольное значение (0-100%)

#### `/set_style`
Устанавливает стиль общения:
- 💼 Work - рабочий стиль
- 😊 Friendly - дружеский стиль
- 🤝 Mixed - смешанный стиль

### Управление контентом

#### `/tag`
Управление тегами сообщений:
- `/tag add <message_id> <tag>` - добавить тег
- `/tag remove <message_id> <tag>` - удалить тег
- `/tag list <message_id>` - список тегов
- `/tag stats` - статистика тегов

#### `/thread`
Управление темами обсуждений:
- `/thread info` - информация о текущем треде
- `/thread list` - список активных тредов
- `/thread new <topic>` - создать новый тред
- `/thread close` - закрыть текущий тред

### Тестирование и обучение

#### `/test`
Тестирование ответов бота:
1. Выберите чат из списка
2. Отправьте тестовое сообщение
3. Получите ответ с учетом настроек чата

#### `/upload`
Загрузка дампа переписки для обучения стилю ответов:
- Поддерживает два способа загрузки:
  1. Текстовое сообщение в формате: `[Дата] Имя пользователя: Сообщение`
  2. Файл:
     - Текстовый файл (.txt) с дампом переписки
     - JSON-файл с экспортом переписки из Telegram
- Поддерживает три типа переписок: рабочий, дружеский, смешанный
- Позволяет быстро обучить бота стилю владельца на основе исторических данных

#### `/refresh`
Обновление стиля ответов на основе всех сообщений в базе данных:
- Анализирует все сообщения
- Обновляет стиль для каждого типа чата
- Показывает обновленный стиль

## Основные промпты

### Генерация ответа
```
You are simulating a Telegram user named Valentin. Based on the user's historical messages and reactions in the chat, you have learned their communication style, tone, frequency of replies, and typical triggers for engaging in conversation.

Your job is to generate replies that imitate Valentin as closely as possible.
When composing a response, always consider:

1. The style and tone Valentin typically uses (casual, professional, humorous, sarcastic, etc.).
2. How often he replies and in what situations (e.g., when he's tagged, when a topic interests him, or when someone asks a direct question).
3. His preferred formats (e.g., emojis, short dry comments, voice of authority, etc.).

You are not ChatGPT — you are 🤖 ~ Valentin, responding as if you're him. Do not explain or over-elaborate. Stay in character.

If no reply is appropriate based on Valentin's history and style, stay silent.

Chat Type: {chat_type.value}
Previous conversation:
{context}

Current message: {message}

Style guidelines from training:
{style_prompt}

Respond in Valentin's style. Keep the response concise and natural. Use appropriate emojis and informal language if it matches the style.
Prefix your response with "🤖 ~ Valentin: "
```

### Анализ важности сообщения
```
You are an assistant trained to evaluate the importance of a message in a group chat context. Your goal is to return a **single numeric value from 0.0 to 1.0** representing how important this message is for the user to respond to.

### Scoring Guidelines:

- **1.0 — Critical**
  - Message directly asks the user a question or requests an action
  - Mentions the user explicitly (e.g., @Valentin)
  - Relates to urgent decisions, deadlines, emergencies, or personal matters

- **0.8 — High Importance**
  - Asks for advice, help, or expertise
  - Important group coordination or planning
  - Sensitive or emotionally charged topic
  - Not urgent but likely to require a thoughtful response

- **0.6 — Medium Importance**
  - General question to the group that the user may want to respond to
  - Ongoing group discussion with relevance to the user
  - New information that may be useful, but not urgent

- **0.4 — Low Importance**
  - Casual conversation, jokes, or memes
  - Social chatter or general observations
  - Greeting messages or emoji replies
  - User is not mentioned or expected to respond

- **0.2 — Very Low Importance**
  - Spam, automated replies, bots
  - System messages or notifications
  - Repetitive or off-topic content

### Instructions:
- Use your judgment based on the message content and context.
- Return a **single number between 0.0 and 1.0** (e.g., 0.8, 0.4).
- Do **not** include any explanation or additional text.
```

### Анализ стиля общения
```
You are analyzing a Telegram chat history to extract the unique communication style of a user named **Valentin**.  
Your goal is to generate a detailed **style guide** that can be used by an AI to imitate Valentin's way of writing and reacting in chats.

Focus on identifying consistent **patterns** and **behaviors** based on the provided conversation.

### Analyze and extract:
1. **Language Style** — Typical vocabulary, sentence structure, and language preferences (e.g., simple/direct, slang, formal, etc.)
2. **Tone & Attitude** — Formality level, humor, sarcasm, emotional range, assertiveness, etc.
3. **Emoji & Formatting Usage** — Frequency and types of emojis, use of punctuation, caps, bold, etc.
4. **Response Length & Structure** — Short or long replies, use of lists, replies in-line vs separate, flow of thoughts
5. **Common Phrases & Expressions** — Repeated phrases, signature endings, fillers, or slang Valentin uses regularly
6. **Do's and Don'ts** — Specific habits to **emulate** (Do's) and things to **avoid** (Don'ts) based on his actual usage

### Output Format (strictly use this):
1. **Language Style**: [brief but rich description]
2. **Tone & Attitude**: [description]
3. **Emoji & Formatting Usage**: [description]
4. **Response Structure**: [description]
5. **Common Phrases & Expressions**:
   - "[phrase 1]"
   - "[phrase 2]"
6. **Do's and Don'ts**:
   - ✅ Do: [behavior to copy]
   - ❌ Don't: [behavior to avoid]
```

## 🚀 Установка и запуск

### Предварительные требования
- Python 3.11+
- PostgreSQL (для продакшена)
- Telegram Bot Token (получить у @BotFather)
- OpenAI API Key
- Render.com аккаунт

### Настройка на Render.com

1. Создайте новый Background Worker на Render.com:
   - Выберите "New +" -> "Background Worker"
   - Подключите ваш GitHub репозиторий
   - Выберите ветку для деплоя (обычно main)

2. Настройте переменные окружения в Render:
   ```
   BOT_TOKEN=ваш_токен_бота
   OWNER_ID=ваш_telegram_id
   OPENAI_API_KEY=ваш_openai_api_key
   DATABASE_URL=postgresql://user:password@host:port/database
   ```

3. Настройте команду запуска:
   ```
   python src/main.py
   ```

4. Настройте автоматический деплой:
   - Включите Auto-Deploy
   - Установите Health Check Path (если требуется)

### Локальная разработка

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/ValentinDobrynin/superbot.git
   cd superbot
   ```

2. Создайте виртуальное окружение:
   ```bash
   python -m venv venv
   source venv/bin/activate  # для Linux/Mac
   # или
   .\venv\Scripts\activate  # для Windows
   ```

3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

4. Создайте файл `.env` с переменными окружения:
   ```
   BOT_TOKEN=ваш_токен_бота
   OWNER_ID=ваш_telegram_id
   OPENAI_API_KEY=ваш_openai_api_key
   DATABASE_URL=postgresql://user:password@host:port/database
   ```

5. Запустите бота:
   ```bash
   python src/main.py
   ```

### Миграции базы данных

При первом запуске на Render или после изменений в моделях:

1. Локально:
   ```bash
   alembic upgrade head
   ```

2. На Render:
   - Используйте Render Shell для выполнения миграций:
   ```bash
   # Подключитесь к Render Shell
   render shell
   
   # Перейдите в директорию проекта
   cd /opt/render/project/src
   
   # Выполните миграции
   python apply_migrations.py
   ```
   
   Или используйте команду в панели управления Render:
   ```
   cd /opt/render/project/src && python apply_migrations.py
   ```

### Мониторинг и логи

- Логи доступны в панели управления Render
- Используйте команду `/logs` для просмотра логов в Telegram
- Настройте уведомления о падении сервиса в Render

## 📋 Требования

### База данных
- PostgreSQL 14+ (для продакшена)
- SQLite (для локальной разработки)

### Python зависимости
- aiogram 3.x
- SQLAlchemy 2.x
- Alembic
- python-dotenv
- openai
- psycopg2-binary (для PostgreSQL)
- python-telegram-bot-pagination

### Внешние сервисы
- Telegram Bot API
- OpenAI API
- Render.com (для хостинга)

- Python 3.9+
- SQLite (или PostgreSQL)
- OpenAI API ключ
- Telegram Bot Token 

## Database Setup

### Local Development
1. Create a PostgreSQL database
2. Set up environment variables (copy from `.env.example`):
   ```bash
   cp .env.example .env
   ```
3. Initialize the database:
   ```bash
   python src/database/init_db.py
   ```

### Render Deployment
1. Connect to Render Shell:
   ```bash
   render shell
   ```
2. Navigate to the project directory:
   ```bash
   cd /opt/render/project/src
   ```
3. Initialize the database:
   ```bash
   python src/database/init_db.py
   ``` 

## Troubleshooting

### Telegram Bot Process Conflict

If you see an error like this when starting the bot:
```
TelegramConflictError: Telegram server says - Conflict: terminated by other getUpdates request; make sure that only one bot instance is running
```

This means that another instance of the bot is already running somewhere. Here's how to fix it:

1. Connect to Render Shell:
   ```bash
   render shell
   ```

2. Navigate to the project directory:
   ```bash
   cd /opt/render/project/src
   ```

3. Check for running Python processes:
   ```bash
   ps aux | grep python
   ```
   Look for processes running `python -m src.main`

4. Stop all bot processes:
   ```bash
   pkill -f "python -m src.main"
   ```

5. Start the bot again:
   ```bash
   python -m src.main
   ```

If the problem persists:
1. Check the Render dashboard for other running services with this bot
2. Make sure the bot is not running on your local machine or other servers
3. Wait a few minutes and try again (sometimes Telegram needs time to release the connection) 

### Database Schema Changes

If you see an error like this:
```
ProgrammingError: column chats.last_summary_timestamp does not exist
```

This means that the database schema is out of sync with the code. To fix this:

#### Option 1: Using Render Shell
1. Connect to Render Shell:
   ```bash
   render shell
   ```

2. Navigate to the project directory:
   ```bash
   cd /opt/render/project/src
   ```

3. Create and apply migrations:
   ```bash
   alembic revision --autogenerate -m "add last_summary_timestamp"
   alembic upgrade head
   ```

#### Option 2: Using Render CLI (without Shell)
```bash
render run "cd /opt/render/project/src && alembic upgrade head"
```

#### Option 3: Add to Build Script
Add migration commands to your build script in Render dashboard:
```bash
#!/usr/bin/env bash
cd /opt/render/project/src
alembic upgrade head
python src/main.py
```

Note: Using migrations is safer than resetting the database as it preserves existing data. 

## Database Migrations

We use Alembic for database migrations. Here's how to work with migrations:

### Creating a Migration

1. Connect to Render Shell:
   ```bash
   render shell
   ```

2. Navigate to the project directory:
   ```bash
   cd /opt/render/project/src
   ```

3. Create a new migration:
   ```bash
   alembic revision --autogenerate -m "description of changes"
   ```
   This will create a new migration file in `src/database/migrations/versions/`

4. Review the generated migration file and make any necessary adjustments

### Applying Migrations

There are two ways to apply migrations:

#### Option 1: Using Render Shell

1. Connect to Render Shell:
   ```bash
   render shell
   ```

2. Navigate to the project directory:
   ```bash
   cd /opt/render/project/src
   ```

3. Apply migrations:
   ```bash
   alembic upgrade head
   ```

#### Option 2: Using Render CLI

1. Install Render CLI:
   ```bash
   brew install render
   ```

2. Login to Render:
   ```bash
   render login
   ```

3. Apply migrations:
   ```bash
   render run "cd /opt/render/project/src && alembic upgrade head" --service your-service-name
   ```

### Rolling Back Migrations

To roll back the last migration:
```bash
alembic downgrade -1
```

To roll back to a specific version:
```bash
alembic downgrade <revision_id>
```

### Checking Migration Status

To see the current migration status:
```bash
alembic current
```

To see migration history:
```bash
alembic history
```

### Troubleshooting

If you see an error like:
```
ModuleNotFoundError: No module named 'src'
```

This means you're trying to run migrations from the wrong directory. Make sure you're in the correct directory:
```bash
cd /opt/render/project/src
```

If you see an error about missing `alembic.ini`:
1. Make sure you're in the correct directory
2. Check that the file exists: `ls -la alembic.ini`
3. If the file is missing, you may need to wait for the deployment to complete 