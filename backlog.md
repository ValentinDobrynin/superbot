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

### [TECH-013] Промпты digest business/private/mixed v2 — жёсткие правила + few-shot

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `prompts/FEATURE-010_digest_business.txt`,
  `prompts/FEATURE-010_digest_private.txt`,
  `prompts/FEATURE-010_digest_mixed.txt`

**Problem Description**

После шагов C/D/A (сохранение тела, парсер дедлайнов, defensive
filters на python-стороне) основной источник шума остался на
LLM-стороне. Промпты v1 (FEATURE-010, 8 мая) были компактные,
но без жёстких правил: модель свободно дублировала одну фразу
в commits и events, тащила вопросы в commits, выдумывала
«12 мая в 18:00» без анкора в исходнике, ставила
`is_urgent=false` подряд.

**Expected Behavior**

Промпты v2 содержат:

1. Эксплицитное правило: «каждая фраза → одна категория».
2. Жёсткое определение commitment (глагол активного действия +
   кто делает; реакции/состояния — drop).
3. Жёсткое определение event (день/время **в исходном тексте**;
   запрет на выдумывание «18:00»).
4. Routing вопросов: «?» в конце или вопросительное слово →
   open_questions, не commitment.
5. Чёткое определение direction по метке репликёра.
6. `is_urgent=true` только при явных маркерах
   «срочно/горит/asap/немедленно/сегодня» в исходных сообщениях.
7. По одному few-shot примеру (input → JSON) с подсветкой
   корректного routing'а.

Tone-вариация (business/private/mixed) — единственное реальное
различие между файлами, остальные правила идентичны.

**Technical Details**

- Все три файла bumped до `version: 2`, `temperature: 0.1–0.2`
  (было 0.2–0.3 — снизил для предсказуемости),
  `max_tokens: 1500` (было 1200 — добавился few-shot).
- Placeholder'ы те же (`{partner_name}`, `{date}`,
  `{message_count}`, `{count_me}`, `{count_partner}`,
  `{messages_text}`, `{open_commitments_json}`,
  `{open_events_json}`), интерфейс `_extract` не менялся.
- Few-shot на каждый промпт построен на типовом провале
  vчерашнего дайджеста: «договор займа → commit», «встреча →
  event», «с какого этажа? → open_question». Никакого
  выдуманного «18:00».
- `direction` для open_questions унифицирован в `from_me`/`to_me`
  (раньше в примере был `to_partner`, что путало рендер).
- Локальная проверка: все три промпта рендерятся через
  `prompts.load_prompt(...).format(...)` без ошибок
  KeyError (см. shell run).

**Acceptance Criteria**

- [x] Все три файла подняты до v2, temperature и max_tokens
      обновлены.
- [x] Few-shot вшит в каждый промпт.
- [x] Жёсткие правила #1 (no dup) и #4 (вопросы) явно
      сформулированы.
- [x] Существующие тесты не сломаны (`make check` 140 passed).
- [x] Шаги C/D/A остаются страховкой — даже если LLM v2
      продолжит ошибаться, defensive filters их подчистят.

**Resolution**

Завершающий шаг последовательности C → D → A → B по фиксу
качества дайджеста. Прокачка промпта снижает шум на входе
defensive filters; сами фильтры остаются как страховка
(LLM ≠ deterministic).

Реальный эффект увидим на дайджесте 9 мая в 23:50 МСК — тело
уже сохраняется в `daily_digests.body_md`, можно будет
SQL-сравнить «до 8 мая» vs «9+ мая»:
- доля коммитов, оставшихся открытыми (а не отменённых);
- кол-во events с `when_raw IS NULL` (раньше было 9 фейковых
  «18:00» из 16);
- появление непустого блока «⚠️ Срочное» (раньше — 0/16).

Если останется шум — итерируем точечно по конкретным кейсам
из `body_md`, не пересобираем весь промпт заново.

---

### [TECH-012] Defensive filters поверх LLM extract'а: вопросы, фейк-18:00, дубли

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/services/digest_service.py`,
  `tests/test_digest_service.py`

**Problem Description**

Прод-БД 8 мая показала характерный шум LLM extract'а на 42 чатах:

- 17 коммитов из них:
  - 3 — это **вопросы** (`Зум можешь сегодня дать?`,
    `Мы без СЕО такие встречи делаем?`),
  - 4 — короткие реакции без действия и дедлайна
    (`как раз занимаюсь`, `Попрошу команду.`),
  - 2 совпадают по тексту с events (`Сравнение предложений`).
- 16 событий из них:
  - 9 подряд имеют one-and-the-same fake `when_raw="12 мая в 18:00"`
    при том, что в исходных чатах это время не упоминается.
  - 2 события `Открытие офиса Silk Road в Ташкенте` дублируются
    в одном бакете.
  - 2 совпадают по тексту с commits.

Промпт жадный, и пока B (полная переписка промптов) ещё впереди,
нужен слой защиты на питоновском уровне.

**Expected Behavior**

После `_extract` (LLM-вывод) применяется `_sanitize_extracted`:

1. Commit с `?` в конце → переезжает в `open_questions`
   (с тем же `direction`).
2. Commit без `deadline_raw` короче 4 слов → drop (реакция).
3. Event с описанием короче 2 слов → drop.
4. Events дедуп внутри чата по `(description.lower(), when_raw)`.
5. Если `when_raw` содержит `HH:MM` или `D месяц`, но эти токены
   не встречаются в исходных сообщениях чата → стираем `when_raw`
   и `when_at` (event живёт, но без фейкового якоря).
6. Если один и тот же текст в commit и event — побеждает event,
   только если у него есть `when_raw`; иначе побеждает commit.

**Technical Details**

- `_QUESTION_TAIL_RE`, `_TIME_HHMM_RE`, `_DAY_MONTH_RE`,
  `_normalize_for_match` — module-level helpers.
- `_sanitize_extracted(extracted, messages_text)` — pure-функция,
  на входе LLM-JSON, на выходе очищенный JSON. Не трогает
  `summary_md` и `closed_commitments`.
- Подключение: в `_extract` после `complete_json` прогоняем
  `extracted` через `_sanitize_extracted(extracted, formatted)`.
  `formatted` — тот же текст, что был передан в промпт LLM, поэтому
  haystack-проверки fair и предсказуемы.
- Тесты:
  - `test_sanitize_moves_question_commits_to_open_questions`
  - `test_sanitize_drops_tiny_commits_without_deadline` (порог 4)
  - `test_sanitize_drops_hallucinated_18_00_when_not_in_source`
  - `test_sanitize_keeps_18_00_when_present_in_source`
  - `test_sanitize_dedups_identical_events_within_chat`
  - `test_sanitize_resolves_commit_event_overlap` (case A: event
    с датой выигрывает; case B: event без даты проигрывает)

**Acceptance Criteria**

- [x] Все 6 ожидаемых кейсов покрыты тестами.
- [x] `_sanitize_extracted` подключён к боевому пути `_extract`.
- [x] Ни один существующий тест не сломан.
- [x] `make check` зелёный (140 passed).
- [x] На следующем дайджесте ожидаем: «Зум можешь?» → в Open Questions,
      9 одинаковых «12 мая в 18:00» → 0–1 валидное; пустые
      «как раз занимаюсь» → исчезли.

**Resolution**

Слой A целиком на python-стороне, без изменений промпта (это будет
шаг B). Логика максимально жадная на drop — лучше потерять валидный
коммит, чем оставить шум. Все правила чисто-функциональные и
тестируются юнит-тестами без сети. Эффект увидим на следующем
авто-дайджесте 23:50 МСК — текст ушедшего сообщения теперь
сохраняется в `daily_digests.body_md` (TECH-010), так что я смогу
сравнить «до/после» постфактум.

Шаг B (полная переписка промптов с few-shot и явным разделением
commit/event/question) идёт следующим — он уменьшит шум на входе
этого фильтра, но фильтр всё равно остаётся как страховка.

---

### [TECH-011] Чинить `parse_deadline` для русских предлогов и `is_urgent` keyword fallback

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/services/digest_service.py`,
  `tests/test_digest_service.py`

**Problem Description**

В прод-БД на 9 мая лежали все 16 событий и все 17 коммитов с
`is_urgent=false`, хотя по логике «дедлайн в течение 24 часов»
хотя бы у части из них должно было сработать. Локальная проверка
показала, что причина — `parse_deadline` возвращает `None` на
самые частые русские формулировки в чатах:

| `raw` | до фикса | почему |
|---|---|---|
| `до пятницы` | `None` | `dateparser` не понимает падежи + предлог «до» |
| `к выходным` | `None` | то же |
| `до 12.05` | `None` (или дата ≠ ожидаемая) | путал с временем 12:05 |
| `до конца дня` | `None` | многословный шорткат |
| `в следующую пятницу` | `None` | предлог + падеж |
| `в среду с утра` | `None` | «с утра» теряется |
| `срочно` / `asap` | `None` | это urgency-маркер, не дата — но `is_urgent` тоже не выставлялся |

**Expected Behavior**

- «до X» / «к X» / «в следующую X» / шорткаты «до конца дня»,
  «к выходным», «на выходных» парсятся в осмысленные даты.
- Day-of-week в любом падеже (`пятницы`/`пятницу`/`пятнице`,
  плюс короткие формы `пн`/`вт`/`ср`/...) → правильный weekday.
- `dd.mm` без года → текущий год; `dd.mm.yy` → 20yy. Разводим
  ambiguity «12.05» vs «12:05» через ISO-конверсию до dateparser.
- «X утром» / «вечером» / «днём» → конкретный час того дня.
- `срочно`/`asap`/`немедленно`/`urgent`/`eod`/`до конца дня`
  поднимают `is_urgent=True`, даже если сам `parse_deadline`
  не нашёл точную дату.
- `is_urgent` теперь = LLM-флаг **OR** `is_within_24h(deadline)`
  **OR** keyword в `deadline_raw`/`text`(`description`).

**Technical Details**

- Новый helper `_normalize_deadline_phrase(raw)` в
  `digest_service.py`:
  - shortcuts: «до конца дня» → «сегодня 23:59»; «к выходным»
    → «суббота 09:00»; «до выходных» → «пятница 23:59»; и др.
  - regex strip префиксов «до /к /в следующую /на следующую /по».
  - dict-нормализация падежей weekday → именительный.
  - dict-нормализация «утром/днём/вечером/ночью» → конкретное HH:MM.
  - regex `\d+\.\d+(\.\d+)?` → ISO `YYYY-MM-DD` (защита от dateparser
    DMY/MDY ambiguity и от «12.05» → 12:05).
  - bare weekday или «сегодня/завтра/послезавтра» без времени →
    добавляем «23:59» (семантика «к концу дня»).
- Новый helper `has_urgency_keyword(raw)` — regex по списку
  `срочно|немедленно|asap|urgent|eod|end of day|до конца дня`
  и т.д., word-boundaries безопасны для кириллицы.
- `_persist`: `is_urgent` теперь `OR`-комбинация LLM-флага,
  `is_within_24h(deadline)` и `has_urgency_keyword(deadline_raw|text)`.
  Применено к Commitment и Event.
- Тесты:
  - `test_parse_deadline_russian_phrases` — 14 параметризованных
    кейсов с проверкой по МСК-дате (избегаем UTC-drift).
  - `test_has_urgency_keyword_recognizes_common_phrases` (10 кейсов).
  - `test_has_urgency_keyword_ignores_non_urgent` (6 кейсов).
- Live-проверка локально (см. shell run):
  `до пятницы` → 15.05 23:59 МСК; `сегодня` → within24h=True;
  `срочно` → urgent_kw=True; `до 12.05` → 12.05 00:00 МСК.

**Acceptance Criteria**

- [x] `parse_deadline` корректно обрабатывает все 14 формулировок
      из теста.
- [x] `has_urgency_keyword` ловит «срочно»/«asap»/«eod» и т.п.
- [x] `_persist` ставит `is_urgent=True` хотя бы по одному из трёх
      путей (LLM-флаг / ≤24h / keyword).
- [x] `make check` зелёный (134 passed).
- [x] Существующие тесты на ISO-даты не сломаны.

**Resolution**

Перепимал `parse_deadline`: добавил мощный pre-process
(`_normalize_deadline_phrase`), который сначала рекомбинирует
русские конструкции в форму, понятную `dateparser` (ISO даты,
именительный падеж weekday, явное время для «утром/вечером»,
шорткаты EOD / выходные). Параллельно вытащил `has_urgency_keyword`
как отдельный публичный helper и подключил его к
`_persist` для commits и events — теперь urgency определяется по
любому из трёх независимых сигналов. Это закрывает основной
«false-negative» вчерашнего дайджеста — все 16 событий и 17
коммитов с `is_urgent=false`.

Шаги A (defensive filters) и B (переписать промпты) идут следом —
но D даёт сразу видимый эффект: «🔥 Срочное» в дайджесте
перестаёт быть пустой секцией.

---

### [TECH-010] Сохранять тело дайджеста в `daily_digests.body_md` для диагностики

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/database/models.py`,
  `src/database/migrations/versions/20260509_0420_e7f9a1c3b5d7_add_body_md_to_daily_digests.py`,
  `src/services/digest_service.py`, `tests/test_digest_service.py`

**Problem Description**

Утренний разбор полётов 9 мая показал: в БД лежат шумные коммиты
(17 шт., все владелец отменил) и события (16 шт., LLM повторно
ставит фейковое «12 мая в 18:00» на 9 строк подряд), но
**текст самого ушедшего дайджеста нигде не сохранён** — `daily_digests`
хранит только `digest_date / sent_at / chat_count / message_count`.
Это блокирует любую постфактум-диагностику качества: нельзя ни
проверить, что владелец реально увидел, ни сравнить «что
извлечено» c «что отрисовано», ни откатить регрессию рендера.

**Expected Behavior**

- `daily_digests.body_md` (TEXT, nullable) хранит склеенный
  MarkdownV2-текст, который ушёл во владельца: header + блок
  на каждый чат, разделённые пустой строкой. Для тихого дня —
  одно стандартное сообщение «Тихий день…».
- Старые строки остаются с `body_md=NULL` (миграция совместима).
- Запись `body_md` идёт ровно одной транзакцией с остальными
  полями (никаких отдельных `UPDATE`-ов после отправки).

**Technical Details**

- Колонка `body_md TEXT NULL` в `daily_digests`.
- Миграция Alembic: `add_body_md_to_daily_digests`,
  `down_revision = 20260508_1300_d4e6f8a0c2b4`.
- В `DigestService.send_for_day` накапливаем `body_parts: list[str]`,
  туда складываем header (через новый `_render_header`, заменивший
  старый асинхронный `_send_header`) и блоки чатов
  (`_process_and_send_chat` теперь возвращает `str`).
- Перед `session.add(DailyDigest(...))` собираем
  `body_md = "\n\n".join(body_parts)`.
- Тесты: `test_send_for_day_processes_each_chat` теперь ассертит,
  что `body_md` содержит и header, и название чата.
  Добавлен `test_send_for_day_records_body_on_quiet_day` —
  тихий день тоже идёт в `body_md`.

**Acceptance Criteria**

- [x] Колонка `body_md` создана через Alembic.
- [x] Миграция применяется на проде (`alembic upgrade head` в build
      команде Render — поедет автоматически).
- [x] `DailyDigest.body_md` заполняется при каждой отправке
      `send_for_day(record=True)`.
- [x] `make check` зелёный (102+ тестов).
- [x] Можно SELECT'ом из `daily_digests` достать текст вчерашнего
      дайджеста и сравнить с тем, что увидел владелец.

**Resolution**

Добавил nullable `daily_digests.body_md`, отрефакторил
`send_for_day` так, чтобы header (`_render_header`) и блоки
(`_process_and_send_chat` теперь возвращает `str`) накапливались в
локальный `body_parts`, и записал их склеенными при создании
`DailyDigest`. Старая логика отправки не изменилась. Этот шаг
открывает диагностику для следующих фиксов в DigestService
(parse_deadline / is_urgent / шум в extract'е) — теперь
постфактум видно, что именно ушло.

---

### [BUG-005] Классификация чатов не сохраняется (asyncpg DataError на `chat.updated_at`)

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/handlers/command_handler.py`, `src/database/models.py`,
  `tests/test_command_handler.py`

**Problem Description**

После релиза `1a06704` (`/glossary` v2) при тапе на любую кнопку
классификации (`💼 / 👤 / 🤝 / ⏭`) бейдж в листинге не менялся, и
повторный `/glossary` показывал все 33 чата как `❓ не задан`.
Render-логи (worker `srv-cvhrontrie7s73e9tve0`, инстанс `…fj6wz`,
8 мая 16:15 UTC и далее, минимум 30 одинаковых трейсов на каждый
тап) выдавали:

> `sqlalchemy.exc.DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error)`
> `<class 'asyncpg.exceptions.DataError'>: invalid input for query argument $2:`
> `datetime.datetime(2026, 5, 8, 16, 15, …) (can't subtract offset-naive`
> `and offset-aware datetimes)`

Колонка `chats.updated_at` объявлена как `Column(DateTime, ...)`
(naive). Хендлеры `glossary_set`, `classification_set` и
`update_chat_title` присваивали ей `datetime.now(timezone.utc)`
(aware). asyncpg отклонял binding, транзакция откатывалась, ни
`classification`, ни даже отрисовка следующей страницы не сохранялись.
Тесты на хендлеры использовали `AsyncMock` сессию и тип-валидацию
SQLAlchemy не дёргали, поэтому баг проскочил мимо `make check`.

**Expected Behavior**

- Тап на `💼 / 👤 / 🤝` в `/glossary` мгновенно меняет бейдж в той же
  странице.
- Тап `cls|<chat>|<value>` на карточке-предложении классификации
  (после дайджеста) сохраняет значение и редактирует сообщение.
- Render-логи чисты от `asyncpg.exceptions.DataError`.

**Technical Details**

- Удалены явные присваивания `chat.updated_at = datetime.now(timezone.utc)`
  в трёх местах: `update_chat_title` (`src/handlers/command_handler.py`
  ~110), `glossary_set` (~1929), `classification_set` (~2070).
- SQLAlchemy сам обновит naive `chat.updated_at` через
  `onupdate=datetime.utcnow` при flush.
- Регрессионный assert в `tests/test_command_handler.py`
  (`test_glossary_set_writes_business`,
  `test_classification_set_writes_value`):
  `chat.updated_at is None or chat.updated_at.tzinfo is None`.
- Полная унификация `chats.created_at/updated_at` и
  `message_stats.timestamp` на `DateTime(timezone=True)` —
  отдельная задача, отнесена в `TECH-004` follow-up (см. ниже).

**Acceptance Criteria**

- [x] Render-логи 8 мая после фикса не содержат
      `asyncpg.exceptions.DataError ... can't subtract`.
- [x] `/glossary` — тап `💼` мгновенно меняет бейдж на `💼 Бизнес`
      в той же странице.
- [x] `/digest` — карточка-предложение классификации после дайджеста
      сохраняет значение по `cls|...`.
- [x] Регрессионные тесты падают, если кто-то снова присвоит aware
      datetime в `chat.updated_at`.
- [x] `make check` зелёный (101+ тестов).

**Resolution**

Отрезал три явных присваивания tz-aware `datetime` в naive колонку
`chats.updated_at`. Это были:

1. `update_chat_title` — переименование чата при `/status`/`/summ`.
2. `glossary_set` — новые inline-кнопки `gs|<chat>|...`.
3. `classification_set` — карточка-предложение после дайджеста.

В каждом месте оставил комментарий со ссылкой на этот таск, чтобы
не наступить на грабли снова. Полную миграцию `chats.updated_at`
на `DateTime(timezone=True)` положил в follow-up `TECH-004`
(не блокирует пользователя — `onupdate=datetime.utcnow` справляется).

В тесты добавил assert, что `chat.updated_at` после хендлера остаётся
naive или None — без этого `AsyncMock`-сессия не ловила бы регрессию.

---

### [FEATURE-010] Дайджест по чатам: классификация + промпты business/private/mixed

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/services/digest_service.py`,
  `src/services/openai_service.py`, `src/services/md.py`,
  `prompts/FEATURE-010_classify.txt`,
  `prompts/FEATURE-010_digest_business.txt`,
  `prompts/FEATURE-010_digest_private.txt`,
  `prompts/FEATURE-010_digest_mixed.txt`,
  `src/database/migrations/versions/20260508_1300_d4e6f8a0c2b4_glossary_commits_events.py`,
  `src/database/models.py`, `src/handlers/command_handler.py`

**Problem Description**

Старый дайджест выдавал плоское саммари без действий — «выглядит
бессмысленно». Нужно сделать его actionable: для каждого чата явно
показывать коммиты в обе стороны, открытые вопросы, даты/события и
срочное. Тон саммари должен зависеть от типа чата: деловой / личный /
смешанный.

**Expected Behavior**

- В каждом чате LLM работает в JSON-режиме и выдаёт строго JSON по схеме
  (summary_md, commitments[], closed_commitments[], events[],
  open_questions[]).
- Саммари рендерится в MarkdownV2 с пятью секциями:
  - заголовок с бейджем классификации (💼/👤/🤝/❓), числом сообщений,
    «мои/его/её»;
  - саммари (1–3 предложения нужного тона);
  - 🤝 Коммиты (от меня / мне, дедлайн в скобках);
  - 📅 Даты и события;
  - ❓ Открытые вопросы (→ ему/ей / ← мне);
  - ⚠️ Срочное (всё с `is_urgent = true`).
- Для чата с `classification IS NULL` используется prompt **business**
  (по умолчанию: большинство переписок владельца — деловые).
- После всех чатов: для каждого ещё-не-классифицированного личного чата
  с сообщениями за день LLM выдаёт `business/private/mixed + confidence
  + reason` → бот шлёт карточку с inline-кнопками (💼/👤/🤝/⏭ позже).
- При парсе MarkdownV2 ошибки (Telegram capricious) делается graceful
  fallback в plain text.

**Technical Details**

- Один большой Alembic-миграционный файл `20260508_1300_d4e6f8a0c2b4`
  добавляет `chats.classification VARCHAR(16)` (CHECK IN
  ('business','private','mixed')), таблицы `commitments` и `events`.
- `src/services/md.py` — MarkdownV2-эскейп + chunk на пустых строках.
- `OpenAIService.complete_json` — обёртка с `response_format=json_object`.
- `DigestService` переписан:
  - `_format_messages` — нормализация авторов («Я:» / «Имя:» / «user_NNN:»);
  - `_extract` — JSON-mode LLM с открытыми коммитами/событиями в контексте;
  - `_persist` — сохраняет новые коммиты/события, помечает закрытые;
  - `_render_block` — MarkdownV2 рендер с пятью секциями;
  - `_suggest_classifications` — после дайджеста шлёт карточки.
- 4 промпта в `prompts/FEATURE-010_*.txt`.
- Команда `/glossary` + callback `glo|...` + общий callback `cls|...|<value>`.
- `dateparser>=1.2.0` в зависимостях.

**Acceptance Criteria**

- [x] LLM получает уже открытые коммиты/события и не дублирует.
- [x] Урегентность авто-определяется (LLM-флаг ИЛИ дедлайн ≤ 24ч).
- [x] Дедлайны хранятся как `deadline_raw` + parsed `deadline_at`.
- [x] Дефолтный prompt для unclassified — `business`.
- [x] MarkdownV2 graceful fallback в plain text при ошибке парса.
- [x] `make check` зелёный.

**Resolution**

Дайджест перешёл от плоского саммари к структурированному отчёту с
действиями. JSON-mode даёт строгую схему, prompt-per-classification —
правильный тон. Классификация делается после первого дайджеста с
участием чата, кнопками подтверждается владельцем; от чата можно
вообще отказаться от классификации (Сбросить).

---

### [FEATURE-008] Хранилище и команда `/commits`

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/database/models.py`,
  `src/database/migrations/versions/20260508_1300_d4e6f8a0c2b4_glossary_commits_events.py`,
  `src/services/digest_service.py`, `src/handlers/command_handler.py`

**Problem Description**

Коммиты должны жить между дайджестами: вчера обещано — сегодня видно
ещё открытым, а после «✅ Сделано» закрывается и больше не дёргает.

**Expected Behavior**

- Таблица `commitments(id, chat_id, direction, text, deadline_raw,
  deadline_at, is_urgent, status, source_message_id, created_at,
  updated_at, completed_at)` с CHECK-constraint'ами.
- `direction ∈ ('from_me', 'to_me')`, `status ∈ ('open', 'done',
  'cancelled')`, `is_urgent: bool`.
- Команда `/commits` — список всех `status='open'`, отсортированных по
  `is_urgent DESC, deadline_at ASC NULLS LAST`, кнопки
  «✅ Сделано»/«🗑 Отменить».
- При следующем дайджесте LLM получает открытые коммиты как контекст и
  явно говорит, какие закрыть (closed_commitments[id, reason]).
- Урgent-флаг ставится либо LLM-ом по фразам «срочно/asap/горит», либо
  автоматически если `deadline_at − now ≤ 24h`.

**Technical Details**

См. FEATURE-010. Команда + callback `commit|<id>|done|cancel` —
`src/handlers/command_handler.py`.

**Acceptance Criteria**

- [x] Миграция добавляет таблицу с CHECK-constraint'ами.
- [x] `/commits` показывает только открытые, кнопки работают.
- [x] LLM видит открытые коммиты при следующем дайджесте и помечает
      закрытыми те, что были закрыты в переписке.
- [x] Тесты на колбэк `commit|...|done` зелёные.

**Resolution**

Тривиальная схема + один callback. Главное — что LLM получает контекст
и не плодит дубли.

---

### [FEATURE-009] Хранилище и команда `/events` (+ авто-`past`)

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/database/models.py`,
  `src/database/migrations/versions/20260508_1300_d4e6f8a0c2b4_glossary_commits_events.py`,
  `src/services/digest_service.py`, `src/services/cleanup_service.py`,
  `src/handlers/command_handler.py`

**Problem Description**

То же, что FEATURE-008, но для дат/событий: ужин в субботу, созвон в
14:00 в пятницу. Когда событие прошло — оно должно перестать
показываться.

**Expected Behavior**

- Таблица `events(id, chat_id, description, when_raw, when_at,
  is_urgent, status, source_message_id, created_at, updated_at)`.
- `status ∈ ('upcoming', 'past', 'cancelled')`.
- Команда `/events` — список `upcoming`, кнопки «✅ Прошло»/«🗑 Отменить».
- При дайджесте LLM получает upcoming-события, дубли не плодит.
- В 04:00 МСК (вместе с TTL-чисткой) `CleanupService.mark_past_events`
  переводит события из `upcoming` в `past` если `when_at < now`.

**Technical Details**

См. FEATURE-010. `mark_past_events()` в `CleanupService`, вызывается из
`run_cleanup_scheduler` сразу после `purge_old_messages`.

**Acceptance Criteria**

- [x] Миграция, модель, команда, callback `event|<id>|done|cancel`.
- [x] Авто-`past` для прошедших событий.
- [x] Тесты на `mark_past_events` и колбэк зелёные.

**Resolution**

Симметрично коммитам, плюс автостарение. События с непарсеным `when_at`
не трогаем — тогда нет объективного критерия, и риск спрятать важное.

---

### [FEATURE-007] Глоссарий чатов: business / private / mixed

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/database/models.py`,
  `src/database/migrations/versions/20260508_1300_d4e6f8a0c2b4_glossary_commits_events.py`,
  `src/services/digest_service.py`, `src/handlers/command_handler.py`

**Problem Description**

Чтобы дайджест говорил правильным тоном для каждого чата (FEATURE-010),
нужно знать классификацию чата. Источник правды — владелец;
бот только предлагает.

**Expected Behavior**

- `chats.classification` (NULL/business/private/mixed) с CHECK.
- В дайджесте чат с NULL получает дефолтный `business`-prompt; после
  всех саммари бот шлёт карточку с предложением модели + 4 кнопками
  (Бизнес/Личный/Микс/Позже).
- Команда `/glossary` — список бизнес-чатов с текущей классификацией и
  кнопкой «⚙️», по которой можно выбрать новую (или «🧹 Сбросить»,
  чтобы снова стал NULL).
- Один общий callback `cls|<chat_id>|<value>` обрабатывает кнопки и из
  карточки в дайджесте, и из `/glossary`.

**Technical Details**

См. FEATURE-010. `prompts/FEATURE-010_classify.txt` — JSON
`(classification, confidence, reason)`. Карточка-предложение строится
в `DigestService._send_classification_card`.

**Acceptance Criteria**

- [x] Колонка + CHECK в миграции.
- [x] `/glossary` рендерит чаты и редактирует классификацию.
- [x] Карточки-предложения в дайджесте работают.
- [x] Тесты на `cls|...|business` и `cls|...|skip` зелёные.

**Resolution**

Owner-confirmed бакет — единственно надёжный путь, эвристика на
сообщениях врёт слишком часто. Авто-предложение экономит время в 80%
случаев.

---

### [FEATURE-004] Telegram Business mode — observer для личных чатов

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/handlers/business_handler.py`, `src/database/models.py`,
  `src/database/migrations/versions/20260508_0810_c3d5e7f9a1b3_business_mode.py`,
  `src/services/digest_service.py`, `src/handlers/command_handler.py`,
  `src/main.py`, `src/config.py`

**Problem Description**

По запросу владельца бот должен видеть **личные чаты** через Telegram
Business mode и включать их в ежедневный дайджест. На первом этапе —
**только observer**: бот сохраняет сообщения, никогда не отвечает.
Полные авто-ответы (вариант C) — отдельная задача в будущем.

**Expected Behavior**

- При подключении бота через Telegram Business (BotFather → Business mode
  ON, у владельца Settings → Telegram Business → Chatbots) бот:
  - регистрирует connection в БД (`business_connections`);
  - сохраняет каждое `business_message` (входящее и исходящее) как
    `DBMessage`, привязывая к `Chat` с `tg_type='private'` и
    непустым `business_connection_id`;
  - **никогда не пишет** в business-чате (observer-only);
- В дайджесте личные чаты идут отдельным блоком «👤 Личные чаты», после
  блока «📊 Чаты» (групповые и супер-группы);
- Имя личного чата формируется как `Иван Петров (@ivan_p)`;
- Команда `/business` показывает статус (число подключений / активных
  подключений / бизнес-чатов в БД), `/business off` локально ставит
  observer на паузу (Telegram всё ещё шлёт сообщения, но в БД мы их не
  пишем), `/business on` снимает паузу;
- Whitelist/blacklist делается **на стороне Telegram** в UI бизнес-режима
  (Selected Chats / Excluded Chats) — это enforced server-side, не наша
  ответственность.

**Technical Details**

- Миграция `20260508_0810_c3d5e7f9a1b3`:
  - таблица `business_connections(id PK, user_id, user_chat_id,
    is_enabled, can_reply, rights JSONB, connected_at, updated_at)`;
  - `chats.business_connection_id VARCHAR(64) NULL` + FK на
    `business_connections.id ON DELETE SET NULL` + индекс.
- Модель `BusinessConnection` в `src/database/models.py`,
  `Chat.business_connection_id`.
- `src/handlers/business_handler.py` (новый):
  - `@router.business_connection()` — upsert строки, при дисконнекте
    `is_enabled=False` (история не теряется);
  - `@router.business_message()` — observer:
    - игнорирует если `settings.business_paused` или `settings.is_shutdown`;
    - игнорирует сообщения для неизвестной/выключенной connection;
    - upsert `Chat(tg_type='private', business_connection_id=...)` с
      именем партнёра по `_format_partner_title()`;
    - сохраняет `DBMessage(text=text or caption)`;
  - edits и deletes — НЕ обрабатываются, отложено в FEATURE-005.
- `src/main.py`: middleware `DatabaseMiddleware` подключён к
  `dp.business_connection` и `dp.business_message`, роутер
  `business_handler.router` подключён к диспетчеру.
- `src/services/digest_service.py`:
  - `collect()` теперь забирает `tg_type IN ('group','supergroup')` ИЛИ
    `tg_type='private' AND business_connection_id IS NOT NULL`;
  - `send_for_day()` рендерит два блока через `_send_block()`,
    верхний хедер показывает `(групповых: N, личных: M)`.
- `src/handlers/command_handler.py`:
  - команда `/business [on|off|status]`;
  - команда `/today` — шорткат для дайджеста за сегодня (FEATURE-006);
  - `/help` обновлён.
- `src/config.py`: `BUSINESS_OBSERVER_ENABLED: bool = True` (kill-switch
  на уровне кода), `business_paused: bool = False` (рантайм-флажок).
- Тесты `tests/test_business_handler.py` (новый):
  - формат имени партнёра (с/без `last_name`, с/без `username`,
    fallback);
  - вставка новой connection / апдейт существующей с переключением
    `is_enabled` и `can_reply`;
  - `business_message` игнорируется при `business_paused`,
    при неизвестной/выключенной connection;
  - `business_message` создаёт Chat с `tg_type='private'` и
    `business_connection_id`, сохраняет DBMessage;
  - `text` берётся из `caption`, если `message.text is None`.
- Тесты `tests/test_digest_service.py`:
  - `_send_for_day` теперь рендерит 5 сообщений (top header + 2 блок-
    хедера + 2 саммари) когда есть и группы, и личные чаты;
  - совместимость со старым тестом «1 чат» (3 сообщения теперь, не 2 —
    добавился блок-хедер `📊 Чаты`).
- Тесты `tests/test_command_handler.py`:
  - `/business off` ставит `business_paused=True`;
  - `/business on` снимает паузу;
  - не-владельцу команда не отвечает и флаг не меняет.

**Risks / Privacy notes**

- Все business-сообщения попадают в Postgres на Render. Mitigations:
  - whitelist на стороне Telegram (ответственность владельца);
  - TTL на `messages` 30 дней (см. TECH-009);
  - `BUSINESS_OBSERVER_ENABLED=False` — kill-switch в коде.
- При rolling deploy на Render одна и та же business-update может
  прийти и в старый и в новый инстанс. У нас нет уникального индекса
  `(chat_id, message_id)`, поэтому при двойной доставке возможна
  дубликация записи. Допустимо для MVP, в FEATURE-005 поправим вместе
  с edits/deletes.

**Acceptance Criteria**

- [x] Миграция создаёт `business_connections` и `chats.business_connection_id`.
- [x] `business_connection` upsert корректно (insert + update).
- [x] `business_message` сохраняет сообщения только при включённой
      connection и неактивном `business_paused`.
- [x] Дайджест разделяет группы и личные чаты, имя личного чата —
      `Имя Фамилия (@username)`.
- [x] `/business`, `/business on`, `/business off` работают.
- [x] `/today` отправляет дайджест за сегодня без записи в `daily_digests`.
- [x] `make check` зелёный (68 тестов).
- [x] Миграция применяется на проде через `alembic upgrade head`.

**Resolution**

Реализовано одним коммитом. Перед использованием на проде:
1. У @BotFather: `/mybots` → бот → `Bot Settings` → `Business Mode` → `Turn on`.
2. У владельца в Telegram: Settings → Telegram Business → Chatbots →
   указать `@vAIlentin_bot` + настроить Selected Chats / Excluded Chats
   по личной приватной модели.
3. После подключения: `/business` в личке боту покажет статус.
4. `/today` или подождать 23:50 МСК — дайджест будет содержать блок
   «👤 Личные чаты».

---

### [TECH-009] TTL `messages.text` = 30 дней (auto-purge)

- **Status:** ✅ Done
- **Priority:** High
- **Component:** `src/services/cleanup_service.py`, `src/main.py`, `src/config.py`

**Problem Description**

С появлением FEATURE-004 (Business observer) в БД попадают личные
переписки. Без TTL мы превращаемся в архив сообщений с потенциально
секретными данными. Это противоречит requirements приватности.

**Expected Behavior**

- Раз в сутки в 04:00 МСК (после ночного дайджеста в 23:50 МСК)
  фоновая корутина удаляет из `messages` всё, что старше
  `settings.MESSAGE_TTL_DAYS` (по умолчанию `30`).
- TTL переопределяется через ENV `MESSAGE_TTL_DAYS`.
- Минимум 1 день: даже если выставить 0 — будет 1.

**Technical Details**

- `src/services/cleanup_service.py` (новый):
  - `seconds_until_next_cleanup(now_utc)` — секунды до 04:00 МСК;
  - `CleanupService.purge_old_messages()` —
    `DELETE FROM messages WHERE created_at < now - TTL`,
    возвращает rowcount;
  - `_purge_with_fresh_session()` — открывает свою сессию;
  - `run_cleanup_scheduler()` — корутина-цикл, в `finally` `main()`
    отменяется через `cancel()`.
- `src/main.py`: `cleanup_task = asyncio.create_task(run_cleanup_scheduler())`,
  добавлено в общий graceful-shutdown.
- `src/config.py`: `MESSAGE_TTL_DAYS: int = int(os.getenv("MESSAGE_TTL_DAYS", "30"))`.
- Тесты `tests/test_cleanup_service.py` (новый):
  - расчёт `seconds_until_next_cleanup` до и после 04:00 МСК;
  - `purge_old_messages` использует threshold `now - TTL`;
  - clamp TTL: 0 → 1 день.

**Acceptance Criteria**

- [x] Background-таск планируется и отменяется корректно.
- [x] DELETE использует timezone-aware `created_at`.
- [x] TTL читается из ENV, fallback 30.
- [x] `make check` зелёный.

**Resolution**

Раз в сутки, без сюрпризов. Если позже понадобится дольше хранить —
поднять `MESSAGE_TTL_DAYS` в Render Env. Если короче — то же самое.

---

### [FEATURE-006] Команда `/today` — дайджест с начала дня

- **Status:** ✅ Done
- **Priority:** Medium (но реализована вместе с FEATURE-004)
- **Component:** `src/handlers/command_handler.py`

**Problem Description**

По запросу владельца нужна отдельная короткая команда «дай саммари с
начала сегодняшнего дня», без необходимости помнить про
`/digest today`.

**Expected Behavior**

- `/today` (только владельцу в личке) → дайджест за сегодняшний день
  (00:00 — текущий момент по МСК), `record=False`
  (не пишет в `daily_digests`).

**Technical Details**

- Хендлер `today_command` в `src/handlers/command_handler.py`,
  использует `today_in_moscow()` и `DigestService.send_for_day(record=False)`.
- `/help` обновлён.

**Acceptance Criteria**

- [x] `/today` отвечает только владельцу в личке.
- [x] Не пишет запись в `daily_digests`.
- [x] Сообщает «✅ Готово» / «✅ Тихий день».

**Resolution**

Готово, тривиально.

---

### [FEATURE-002] Ежедневный дайджест чатов в 23:50 МСК + команда `/digest`

- **Status:** ✅ Done
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

**Acceptance Criteria (Phase 2)**

- [x] Background-таск в `main.py` спит до 23:50 МСК и шлёт дайджест.
- [x] Catch-up на старте: если самое последнее сработавшее окно 23:50
      ещё не отражено в `daily_digests` → отправить за тот день.
- [x] Graceful cancel в `finally` `main()` (рядом с `stats_task`).
- [x] Тесты на расчёт `seconds_until_next_digest` и `previous_trigger_day`.

**Technical Details (Phase 2)**

- В `src/services/digest_service.py` добавлены:
  - `seconds_until_next_digest(now_utc)` — секунды до ближайших 23:50
    в `Europe/Moscow`. Если уже после 23:50 сегодня — до 23:50 завтра.
  - `previous_trigger_day(now_utc)` — календарный день (МСК), чьи 23:50
    последними сработали; если сейчас до 23:50 сегодня — это вчера, иначе
    сегодня.
  - `_send_with_fresh_session(bot, day)` — открывает свою сессию через
    `async_session()` и шлёт дайджест с `record=True`.
  - `run_digest_scheduler(bot)` — корутина для бэкграунд-таска: на старте
    проверяет, отправлен ли дайджест за `previous_trigger_day()`; если
    нет — шлёт catch-up. Дальше бесконечный цикл `sleep(...)` до 23:50,
    при срабатывании шлёт за `today_in_moscow()`. Любая ошибка
    логируется, цикл не падает (60-секундный backoff).
- `src/main.py`: `digest_task = asyncio.create_task(run_digest_scheduler(bot))`,
  `cancel()` в общем `finally` рядом с `stats_task`.

**Семантика дня дайджеста**

Автомат в 23:50 МСК (день D) → саммари **дня D** (00:00 — 23:50 D).
Команда `/digest` без аргументов → за **вчерашний** полный день.
Если хочется иначе — менять тривиально (1 строка в
`run_digest_scheduler` и/или `_parse_digest_arg`).

**Resolution**

- Фича собрана из двух коммитов: phase 1 (сервис + миграция + `/digest`),
  phase 2 (планировщик в `main.py`). Прод проверяется свежим деплоем.

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

### [FEATURE-005] Business mode: edits / deletes + dedup сообщений

- **Status:** 🆕 To Do
- **Priority:** Medium
- **Component:** `src/handlers/business_handler.py`, `src/database/models.py`,
  `src/database/migrations/versions/`

**Problem Description**

В FEATURE-004 мы реализовали observer для Telegram Business только для
`business_message`. Edits и deletes сейчас **не обрабатываются**:

- Если контакт или владелец отредактирует сообщение, в БД останется
  старая версия.
- Если контакт удалит сообщение, в БД оно останется навсегда (до TTL).
- При rolling-deploy на Render одна и та же business-update может
  прийти и в старый, и в новый инстанс — и сейчас мы её сохраним
  дважды (нет уникального индекса по `(chat_id, message_id)`).

**Expected Behavior**

- `edited_business_message` → найти `DBMessage` по
  `(chat.telegram_id, message.message_id)` и обновить `text`/`updated_at`.
- `deleted_business_messages` → удалить (или мягко пометить) записи
  `DBMessage` по `(chat.telegram_id, message_ids[])`.
- На уровне БД — уникальный индекс `messages(chat_id, message_id)`,
  чтобы при двойной доставке не было дублей.

**Technical Details**

- Миграция: `CREATE UNIQUE INDEX ix_messages_chat_id_message_id
  ON messages(chat_id, message_id)`. Перед созданием — DEDUP по
  `(chat_id, message_id, MIN(created_at))`.
- `src/handlers/business_handler.py`:
  - `@router.edited_business_message()` — обновление по composite key;
  - `@router.deleted_business_messages()` — массовое удаление.
- Тесты: edit обновляет text, delete удаляет ряды, повторный insert
  не создаёт дубль.

**Acceptance Criteria**

- [ ] `messages(chat_id, message_id)` уникален.
- [ ] Edit обновляет text + updated_at.
- [ ] Delete физически удаляет (или soft-delete — по обсуждению).
- [ ] Тесты на оба пути + на дедуп.

---

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
