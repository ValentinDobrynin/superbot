# SuperBot 🤖

An intelligent Telegram bot that uses OpenAI's GPT models to provide context-aware responses in group chats. The bot can adapt its communication style based on chat type and learn from conversation history.

## Features

- 🤖 Intelligent responses using OpenAI's GPT models
- 🎯 Context-aware communication
- 🎨 Multiple chat styles (work, friendly, mixed)
- 🔄 Smart mode for adaptive responses
- 📊 Response probability control
- 🔍 Importance threshold for message filtering
- 🔇 Silent mode for learning without responding
- 📝 Message tagging and threading
- 📈 Chat analytics and statistics

## Prerequisites

- Python 3.9+
- PostgreSQL database (version 13 or higher)
- OpenAI API key
- Telegram Bot Token

## Installation

1. Клонируйте репозиторий:
```bash
git clone https://github.com/ValentinDobrynin/superbot.git
cd superbot
```

2. Создайте и активируйте виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # для Linux/Mac
# или
venv\Scripts\activate  # для Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Настройте PostgreSQL:
```bash
# Создайте базу данных
createdb superbot

# Создайте пользователя (если еще не создан)
createuser -P superbot_user
# Введите пароль когда попросят

# Предоставьте права
psql -d superbot -c "GRANT ALL PRIVILEGES ON DATABASE superbot TO superbot_user;"
```

5. Создайте файл `.env` в корневой директории проекта:
```env
BOT_TOKEN=your_bot_token_here
OPENAI_API_KEY=your_openai_api_key_here
OWNER_ID=your_telegram_id_here
DATABASE_URL=postgresql+asyncpg://superbot_user:your_password@localhost/superbot
```

6. Примените миграции базы данных:
```bash
alembic -c src/alembic.ini upgrade head
```

## Usage

1. Запустите бота:
```bash
python src/main.py
```

2. Добавьте бота в групповой чат Telegram

3. Используйте команды для управления ботом:

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

## Database Checks

### Check Messages Table Structure
```bash
psql "postgresql://superbot_user:fGKUr4bbKVXRYusJMepx5GH7WrF5f706@dpg-cvm4r2je5dus73afbbo0-a.oregon-postgres.render.com/superbot" -c "\d messages"
```
This command displays the structure of the messages table, including column names, data types, and constraints.

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

## Development

### Project Structure

```
superbot/
├── src/
│   ├── database/
│   │   ├── models.py
│   │   └── migrations/
│   ├── handlers/
│   │   ├── command_handler.py
│   │   ├── message_handler.py
│   │   └── callback_handler.py
│   ├── services/
│   │   ├── openai_service.py
│   │   ├── context_service.py
│   │   └── notification_service.py
│   ├── config.py
│   └── main.py
├── tests/
├── alembic.ini
├── requirements.txt
└── README.md
```

### Database Migrations

The project uses Alembic for database migrations. All migration files are located in `src/database/migrations/versions/`.

#### Migration Structure
The database includes the following main tables:
- `chats` - Information about Telegram chats
- `messages` - Message history and content
- `message_threads` - Conversation threads and topics
- `message_contexts` - Context information for threads
- `message_tags` - Tags for message categorization
- `message_stats` - Chat statistics and analytics
- `styles` - Communication styles for different chat types
- `tags` - Available message tags
- `thread_relations` - Relationships between threads

#### Managing Migrations

##### Applying Migrations
To apply all pending migrations:
```bash
alembic -c src/alembic.ini upgrade head
```

##### Creating New Migrations
When you make changes to the database models:
1. Create a new migration:
```bash
alembic -c src/alembic.ini revision -m "description of changes"
```
2. Edit the generated migration file in `src/database/migrations/versions/`
3. Apply the migration:
```bash
alembic -c src/alembic.ini upgrade head
```

##### Rolling Back Migrations
To roll back the last migration:
```bash
alembic -c src/alembic.ini downgrade -1
```

To roll back all migrations:
```bash
alembic -c src/alembic.ini downgrade base
```

##### Important Notes
- Always backup your database before applying migrations
- Test migrations in a development environment first
- Keep migrations atomic and focused on specific changes
- Document any manual steps required for migration

### Running Tests

```bash
pytest
```

## Contributing

Пожалуйста, прочитайте [CONTRIBUTING.md](CONTRIBUTING.md) для деталей о нашем коде поведения и процесса для отправки pull requests.

## License

Этот проект лицензирован под лицензией MIT - см. файл [LICENSE](LICENSE) для деталей.

## Update Instructions

To update the bot on Render:

1. First time setup (if Git repository is not configured):
```bash
cd /opt/render/project/src && PYTHONPATH=$PYTHONPATH:. git remote add origin https://github.com/ValentinDobrynin/superbot.git
```

2. Pull latest changes and apply database migrations:
```bash
cd /opt/render/project/src && PYTHONPATH=$PYTHONPATH:. git pull origin main && alembic -c alembic.ini upgrade head && sudo systemctl restart superbot
```

Or execute commands separately:
```bash
# 1. Pull latest changes
cd /opt/render/project/src && PYTHONPATH=$PYTHONPATH:. git pull origin main

# 2. Apply database migrations
PYTHONPATH=$PYTHONPATH:. alembic -c alembic.ini upgrade head

# 3. Restart the service
sudo systemctl restart superbot
```

These commands will:
1. Update the code to the latest version
2. Apply any new database migrations
3. Restart the bot service

Note: The Git repository is located in `/opt/render/project/src/.git`

## TODO

### Оптимизация
- [ ] Добавить кэширование результатов анализа тем для оптимизации запросов к OpenAI API
  - Увеличить время кэширования для анализа тем до 1 часа
  - Реализовать отдельный кэш для тем, независимый от общего кэша статистики
  - Добавить возможность принудительного обновления кэша тем

### Функциональность
- [ ] Добавить поддержку голосовых сообщений
- [ ] Реализовать анализ изображений через OpenAI Vision
- [ ] Добавить возможность создания пользовательских стилей общения
- [ ] Реализовать систему автоматического обновления стиля на основе новых сообщений

### Аналитика
- [ ] Добавить графики активности в статистику
- [ ] Реализовать экспорт статистики в CSV/Excel
- [ ] Добавить анализ настроения в чате
- [ ] Реализовать предсказание активности в чате

### Безопасность
- [ ] Добавить систему ролей и прав доступа
- [ ] Реализовать логирование действий администраторов
- [ ] Добавить защиту от спама и флуда
- [ ] Реализовать систему бэкапов базы данных

### Интеграции
- [ ] Добавить интеграцию с GitHub для отслеживания задач
- [ ] Реализовать интеграцию с календарем для напоминаний
- [ ] Добавить поддержку других мессенджеров (Discord, Slack)
- [ ] Реализовать API для внешних сервисов

### Улучшение UX
- [ ] Добавить inline-кнопки для всех команд
- [ ] Реализовать систему подсказок для новых пользователей
- [ ] Добавить возможность настройки языка интерфейса
- [ ] Реализовать систему уведомлений о важных событиях