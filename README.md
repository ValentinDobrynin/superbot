# SuperBot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-aiogram%203.0%2B-blue.svg)](https://core.telegram.org/bots/api)

Умный Telegram бот с контекстным пониманием диалогов и тематическим анализом сообщений.

## Возможности

- Анализ контекста сообщений и группировка их в тематические потоки
- Умное определение важности сообщений
- Автоматическая маркировка сообщений тегами
- Поиск связанных обсуждений
- Адаптивная настройка порога важности для ответов

## Технологии

- Python 3.9+
- aiogram 3.0+
- SQLAlchemy 2.0+
- OpenAI API
- SQLite (для разработки)
- PostgreSQL (для продакшена)

## Требования

- Python 3.9 или выше
- PostgreSQL (для продакшена)
- Telegram Bot Token
- OpenAI API ключ

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/your-username/superbot.git
cd superbot
```

2. Создайте виртуальное окружение и установите зависимости:
```bash
python -m venv venv
source venv/bin/activate  # для Linux/macOS
# или
.\venv\Scripts\activate  # для Windows
pip install -r requirements.txt
```

3. Создайте файл `.env` с необходимыми переменными окружения:
```env
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
OWNER_ID=your_telegram_id
DATABASE_URL=sqlite+aiosqlite:///vailentin.db  # для разработки
```

## Запуск

Для локального запуска:
```bash
python -m src.main
```

## Деплой на Render

1. Создайте аккаунт на [Render](https://render.com)
2. Подключите ваш GitHub репозиторий
3. Создайте новый Web Service, выбрав ваш репозиторий
4. Настройте следующие переменные окружения в Render:
   - `BOT_TOKEN`
   - `OPENAI_API_KEY`
   - `OWNER_ID`
   - `DATABASE_URL` (для PostgreSQL)

Render автоматически определит `Dockerfile` и развернет приложение.

## Тестирование

Для запуска тестов:
```bash
pytest tests/ -v
```

## Структура проекта

```
superbot/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database/
│   │   ├── __init__.py
│   │   └── models.py
│   └── services/
│       ├── __init__.py
│       └── context_service.py
├── tests/
│   └── test_context_service.py
├── Dockerfile
├── requirements.txt
├── render.yaml
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
└── README.md
```

## Безопасность

Если вы обнаружили уязвимость безопасности, пожалуйста, следуйте нашей [политике безопасности](SECURITY.md).

## Контрибуция

Пожалуйста, прочитайте [руководство по контрибуции](CONTRIBUTING.md) перед созданием пулл-реквеста.

## Лицензия

Этот проект лицензирован под MIT License - см. файл [LICENSE](LICENSE) для деталей. 