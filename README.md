# vAIlentin 2.0 Bot

Telegram бот с расширенными возможностями управления и аналитики.

## Основные возможности

### Управление режимами работы
- **Глобальный режим** (`/shutdown`) - управление работой бота во всех чатах
- **Режим чата** (`/setmode`) - полное отключение бота в конкретном чате
- **Тихий режим** (`/silent`) - бот читает сообщения, но не отвечает
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
Полное отключение бота в конкретном чате:
- ❌ Отключен: бот не читает и не отвечает
- ✅ Включен: бот работает в обычном режиме

#### `/silent`
Управление тихим режимом в чате:
- 🤫 Тихий режим: бот читает сообщения, но не отвечает
- 🗣 Обычный режим: бот работает в обычном режиме

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

#### `/summ <chat_id>`
Генерирует сводку по чату:
- Основные темы обсуждений
- Активность пользователей
- Ключевые теги
- Связанные треды

#### `/list_chats`
Список всех чатов с настройками:
- ID и название чата
- Статус активности
- Вероятность ответа
- Умный режим
- Порог важности

### Настройка

#### `/set_probability <chat_id> <probability>`
Устанавливает вероятность ответа (0-1):
- 0.0 - никогда не отвечает
- 1.0 - отвечает всегда
- По умолчанию: 0.25

#### `/set_importance <chat_id> <threshold>`
Устанавливает порог важности для умного режима (0-1):
- 0.0 - низкий порог, отвечает чаще
- 1.0 - высокий порог, отвечает реже
- По умолчанию: 0.3

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

### Тестирование

#### `/test`
Тестирование ответов бота:
1. Введите ID чата
2. Отправьте тестовое сообщение
3. Получите ответ с учетом настроек чата

## Установка и настройка

1. Клонируйте репозиторий
2. Установите зависимости: `pip install -r requirements.txt`
3. Настройте переменные окружения на Render:
   - `BOT_TOKEN` - токен вашего Telegram бота
   - `OPENAI_API_KEY` - ключ API OpenAI
   - `OWNER_ID` - ваш Telegram ID
   - `DATABASE_URL` - URL базы данных PostgreSQL
4. Запустите бота: `python -m src.main`

## Требования

- Python 3.9+
- PostgreSQL
- OpenAI API ключ
- Telegram Bot Token 

## Основные промпты

### Анализ важности сообщения
```
Analyze the importance of this message in the context of the chat. Consider:
1. Is it a question or request?
2. Does it require immediate attention?
3. Is it part of an ongoing discussion?
4. Does it contain actionable information?

Rate importance from 0.0 to 1.0, where:
- 0.0: Low importance, no action needed
- 1.0: Critical, requires immediate response

Message: {message_text}
```

### Генерация ответа
```
You are a helpful AI assistant in a Telegram chat. Your communication style is {chat_style}.
Previous context: {context}

User message: {message}

Generate a helpful and appropriate response. Consider:
1. Stay on topic
2. Be concise and clear
3. Match the chat's style
4. Address the user's needs

Response:
```

### Анализ темы обсуждения
```
Analyze this message and identify:
1. Main topic or theme
2. Key points discussed
3. Related topics
4. Suggested tags

Message: {message_text}

Format the response as JSON with these fields.
```

### Сводка чата
```
Generate a comprehensive summary of this chat's activity:
1. Main topics discussed
2. Key participants and their roles
3. Important decisions or conclusions
4. Action items or follow-ups

Chat history: {chat_history}

Format the response in a clear, structured way.
``` 