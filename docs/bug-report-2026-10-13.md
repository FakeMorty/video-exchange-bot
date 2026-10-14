# Отчёт об аудите багов — 2026-10-13

Ветка: `arena/1f22e40e-video-exchange-bot` (от `master@1116ca7`).
Метод: полное чтение `services.py`, `config.py`, `db.py`, `models.py`, `middlewares.py`,
`donation_shop.py`, `donationalerts_client.py`, `arcade.py`, `i18n.py`; целевое чтение
`main.py`, `user_handlers.py`, `admin_handlers.py`, `user_offer_handlers.py`, `keyboards.py`,
`reports.py`, `utils/db_fix.py`, alembic-цепочки. Гипотезы, помеченные **[проверено]**,
воспроизведены скриптами (см. Приложение) или прямым вызовом кода; остальные — по коду.
Базовое состояние: `pytest` — 134 passed, `alembic upgrade head` на SQLite проходит.

## Статус исправлений (обновлено 2026-10-13)

Все 30 пунктов B-01…B-30 исправлены в этой же ветке (версия `v3.28.0-audit-fixes`,
см. `CHANGELOG.md`). Регрессионные тесты — `app/tests/test_bug_fixes_2026_10_13.py`
(19 тестов); полный прогон `pytest` — 153 passed. Схема БД догнана миграцией
`alembic/versions/schema_drift_2026_10_13.py` (идемпотентна, применяется `migrate.py`
через `start_render.sh`, который теперь и является CMD Docker-образа).

Сознательно не менялось (принято как есть, см. комментарии к пунктам):
порядок деактивации старых перков при смене ника в `donation_shop.py` (до списания),
возврат бюджета офферов, оплаченных Stars, в монетах, «обычный кейс» для
`open_lootbox_for_stars` (так и названа кнопка), особенности `handle_video_upload`
для фото и неэкранированный админский контент в `_show_ad_or_event`.
Кандидаты из раздела 5 (непроверенные) не исправлялись.

Шкала: **P0** — функция сломана / потеря денег / уязвимость; **P1** — серьёзная логическая
ошибка, сработает в проде; **P2** — ошибка ограниченного эффекта; **P3** — мелочь/UX.

---

## Сводка

| ID | P | Область | Суть |
|----|---|---------|------|
| B-01 | P0 | Лотерея | Кнопка «🎫 Купить билеты» всегда падает (дублирующий декоратор `lottery_buy`) **[проверено]** |
| B-02 | P0 | Лотерея | «Мои билеты» падает у любого, у кого есть билеты (затенение `t`) |
| B-03 | P0 | Лотерея | Итоги розыгрыша никогда не рассылаются (затенение `t` в `notify_lottery_results`) |
| B-04 | P0 | Админка | Меню супер-админа «🗄 База данных» падает (затенение `t` в `admin_db_keyboard`) **[проверено]** |
| B-05 | P0 | Экономика | TOCTOU: двойное списание / уход баланса в минус при параллельных запросах **[проверено]** |
| B-06 | P0 | Платежи | DonationAlerts: VIP на 30 дней за любой донат с словом «vip» в сообщении |
| B-07 | P0 | Безопасность | Публичные `/api/videofeed/feed` и `/api/video/{id}` без авторизации — весь контент скачивается бесплатно |
| B-08 | P0 | Онбординг | Пользователь с `<` в имени Telegram не получает главное меню вообще (HTML-инъекция имени) |
| B-09 | P1 | Офферы | Сбой Telegram API при аудите подписок = штраф подписанным пользователям |
| B-10 | P1 | Лотерея | Раунд теряется (не разыгран, ставки не возвращены), если бот был офлайн в 90-секундном окне розыгрыша; раунд в `drawing` после рестарта зависает навсегда |
| B-11 | P1 | Экономика | Пользовательские офферы не обеспечены: создатель платит один раз, каждому участнику награды выдаются «из воздуха» |
| B-12 | P1 | Экономика | VIP ×2.0 понижается до ×1.5 при покупке перка «бустер монет» |
| B-13 | P1 | Деплой | Дрейф схемы: alembic head не содержит `users.lootbox_pity_counter`, `users.promo_month`, таблицу `promo_messages` — Docker-деплой на чистый Postgres неработоспособен **[проверено]** |
| B-14 | P1 | Платежи | DonationAlerts: админам шлётся одно и то же «нужна сверка» каждые 60 с по каждому непривязанному донату |
| B-15 | P1 | Лутбоксы | Админ-бесплатное открытие за Stars падает с `ValueError` (распаковка 2 из 3) |
| B-16 | P1 | VIP | «Бесплатный промокод раз в месяц» работает один раз за всё время |
| B-17 | P1 | Модерация | Повторная награда за загрузку: reject → restore → approve; гонка двух админов на approve |
| B-18 | P1 | Безопасность | HTML-инъекция имени во множестве экранов (топы, подписи к видео, уведомления) |
| B-19 | P2 | Лотерея | Админские бесплатные билеты раздувают `prize_pool`, не оплачивая его; `prize_pool +=` неатомарен; текст итогов ≠ выплатам |
| B-20 | P2 | Офферы | Аудит подписок «голодает»: всегда проверяются одни и те же 200 старейших участий |
| B-21 | P2 | XP | `XP_PER_WATCH` и `XP_PER_GAME` объявлены на экране «Уровень», но никогда не начисляются |
| B-22 | P2 | Админка | Поиск пользователей ломает `_` в username (`john_doe` → `john doe`) |
| B-23 | P2 | Админка | Обычный админ может забанить/изменить баланс супер-админа |
| B-24 | P2 | Платежи | Stars списаны, промокод/лутбокс не выдан при ошибке после оплаты; инвойс не показывает вечерний ×1.5 и бонус первой покупки |
| B-25 | P2 | Лутбоксы | Общий pity-счётчик на все кейсы; `styles_case_toggle_style` пишет state до проверки `STYLES[style_id]`; кейс стилей перезаписывает купленный стиль |
| B-26 | P2 | Mini App | Произвольный `case_id`, «сырой» баланс в ответе, нет max ставки, `timezone` не валидируется |
| B-30 | P2 | Офферы | Ссылка на пост канала (`t.me/channel/123`) никогда не проходит проверку подписки у пользователя (две разные `_chat_id_from_offer_url`) |
| B-27 | P2 | Фон | `onboarding_task` не отменяется при остановке; N+1 полные сканы пользователей каждые 15/30 мин |
| B-28 | P3 | UX/текст | `\n\n` литералом и `<b>` без parse_mode в «своя сумма Stars»; «Твойе обращение», «с тебеи»; `btn_profile` — кнопка-пустышка; «5 видео» vs 3 в retention |
| B-29 | P3 | Код | Комментарии: не-текст → `IntegrityError`; `DeprecationWarning` invalid escape `\.` в `main.py:3218`; `promo_` deep link обходит `ENABLE_PROMOCODES` |

---

## 1. P0 — сломанный функционал

### B-01. «🎫 Купить билеты» в лотерее всегда падает **[проверено]**
- **Где:** `app/user_handlers.py:3675` — `@router.callback_query(F.data == "lottery_buy")` висит над
  синхронным хелпером `_format_lottery_purchase_summary(tickets, total_cost, balance_after, *, admin_free)`;
  настоящий обработчик `lottery_buy` объявлен ниже (`:3715`).
- **Что происходит:** aiogram регистрирует хендлеры по порядку, первый матч побеждает → на нажатие
  вызывается хелпер с `(callback, state)` → `TypeError: _format_lottery_purchase_summary() missing 2
  required positional arguments`. Воспроизведено через `router.callback_query.trigger()` (Приложение A).
- **Фикс:** удалить декоратор на строке 3675.

### B-02. «Мои билеты» падает, если билеты есть
- **Где:** `app/user_handlers.py:3813` — `for t in tickets:` внутри `lottery_my_tickets`, затем ниже в той
  же функции вызывается i18n-функция `t(...)`. После цикла `t` — объект `LotteryTicket` → `TypeError: 'LotteryTicket' object is not callable`.
- **Эффект:** экран работает только у пользователей без билетов.
- **Фикс:** переименовать переменную цикла (`ticket`).

### B-03. Итоги розыгрыша никогда не отправляются
- **Где:** `app/main.py:356` и `:373` (`notify_lottery_results`) — `for t in tickets` / `for t in bets`, затем `t(...)`
  используется для текста уведомлений.
- **Эффект:** выплаты по билетам/ставкам проводятся (`settle_lottery_round`), но функция рассылки
  бросает `TypeError`, который глушится `except` в `lottery_worker` → никто не получает сообщение
  о выигрыше/проигрыше; из логов виден только warning.
- **Фикс:** переименовать переменные циклов.

### B-04. Меню супер-админа «🗄 База данных» падает **[проверено]**
- **Где:** `app/keyboards.py:346` — `for t in tables:` в `admin_db_keyboard`, а на `:352` — `t("...")`.
- **Проверка:** `admin_db_keyboard([("users","..."),("videos","...")])` → `TypeError: 'tuple' object is not callable`.
- **Фикс:** переименовать переменную.

> Системная причина B-02…B-04: массовая замена строк на `t(...)` при внедрении i18n без проверки
> затенения. Стоит добавить lint-правило (ruff `A001`/`PLW0621`-подобное) или грепать `for t in`.
> Остальные `for t in` (`admin_handlers.py:245` — listcomp, `:894`, `selfcheck.py:52`, `reports.py:727`,
> `services.py:2996/3029/3050`) проверены: безопасны.

### B-05. TOCTOU: двойное списание / отрицательный баланс **[проверено]**
- **Где:** `app/services.py:560` `change_balance_atomic` — это просто `UPDATE users SET balance = balance + :amount ... RETURNING`,
  без условия `balance >= :amount` для списаний. Все вызывающие проверяют баланс «до» на устаревшем объекте:
  `open_lootbox_for_coins` (:217), покупка стилей/смена ника, просмотр (`WATCH_COST`), игры,
  `buy_lottery_tickets` (:2774), `donation_shop.py` (покупка перков), Mini App `api_cases_open`
  (`main.py:3146`), `api_lottery_buy` (:2182), `api_lottery_place_bet` (:2268), `arcade.start_run` (`arcade.py:265`).
  Защита есть только в `adjust_balance_by_admin`.
- **Доказательство:** `asyncio.gather` двух `open_lootbox_for_coins(uid, "legendary")` при балансе 5000
  (цена 5000) — оба открытия успешны, итоговый баланс **7538** вместо отказа (Приложение B).
  Через Mini App это делается двумя параллельными HTTP-запросами; в боте — двойным тапом по inline-кнопке.
- **Эффект:** бесплатные кейсы/билеты/перки, баланс в минус, два активных `ArcadeRun` на одного.
- **Фикс:** в `change_balance_atomic` для `amount < 0` добавить `WHERE balance + :amount >= 0` и
  возвращать `None`/бросать при `rowcount == 0` (все вызывающие уже умеют обрабатывать `None`),
  либо `SELECT ... FOR UPDATE` пользователя в начале операции (Postgres). Для арены — уникальный
  частичный индекс `arcade_runs(user_id) WHERE status='active'`.

### B-06. DonationAlerts: VIP за любой донат с «vip» в сообщении
- **Где:** `app/services.py:4645` `process_donationalerts_donation`, `:4682`:
  `is_vip = "vip" in comment_lower or abs(amount_rub - vip_price_rub) < 0.01`.
  `process_donationalerts_event` передаёт в `comment` **сообщение донатера**, а `order.reward_type`
  (что именно оплачивалось) игнорируется; `order.coins_amount` тоже игнорируется — монеты считаются как `amount_rub * rub_to_coins_rate`.
- **Эффект:** заказ на 10 ₽ + текст «DA-XXXX vip» → VIP на 30 дней (обычная цена 150 ₽ / 450 Stars).
  Обратный случай: покупатель монет, написавший «vip» в комментарии, монет не получает.
  Ручной админский путь («зачесть донат вручную») использует тот же хак.
- **Фикс:** тип награды брать только из `order.reward_type`; сумму монет — из `order.coins_amount`;
  сообщение донатера использовать исключительно для извлечения кода.

### B-07. Публичный видеофид без авторизации
- **Где:** `app/main.py:1702` `api_videofeed_feed`, `:1716` `api_video_stream`; маршруты `:4174-4175`.
  Нет проверки `initData`, стоит `Access-Control-Allow-Origin: *`, id последовательные.
- **Эффект:** любой скрипт выкачивает все одобренные видео, минуя списание `WATCH_COST`
  (`curl https://host/api/video/1..N`). Кэш `video_cache/` растёт без ограничения.
- **Фикс:** требовать `X-Telegram-Init-Data` (как в остальных API), отдавать файлы по подписанным
  одноразовым токенам, ограничить CORS, добавить LRU/TTL для кэша.

### B-08. Пользователь с `<` в имени не может пользоваться ботом
- **Где:** `app/user_handlers.py:183-186` (`cmd_start`) и `:570-620` (`send_welcome_banner`):
  `welcome.greeting = "👋 Привет, <b>{name}</b>..."`, `name = get_styled_display_name()` →
  `get_display_name()` (`services.py:373`) отдаёт сырой `first_name`; `format_nick_inline` (`nick_styles.py:266`)
  не экранирует. Все три фолбэка в `send_welcome_banner` снова шлют тот же HTML.
- **Эффект:** имя вида `<3 Аня` или `Tom <3` (очень распространено) → Telegram отвечает
  `can't parse entities` → исключение → ни приветствия, ни reply-клавиатуры главного меню.
  Новый пользователь не может даже задать ник.
- **Фикс:** экранировать (`html.escape`) в `get_display_name`/`get_styled_display_name` либо во всех
  точках подстановки; в `send_welcome_banner` последний фолбэк — без `parse_mode`.

---

## 2. P1 — серьёзные логические ошибки

### B-09. Транзиентная ошибка Telegram = штраф подписанным
- **Где:** `app/main.py:158` `_is_subscribed` возвращает `False` при **любом** исключении
  (`except Exception: return False`), а `subscription_audit_worker` (`:171`) трактует `False` как
  «отписался» и вызывает `apply_offer_unsubscribe_penalty` (`services.py:2005`): отзыв награды + штраф + статус `unsubscribed`
  (необратимо, `unsubscribed_penalized_at` ставится).
- **Триггеры:** 429/5xx Telegram, таймаут сети, бот удалён из админов канала, канал переименован/удалён,
  бот временно без прав `getChatMember` — одним проходом штрафуются все до 200 участий.
- **Фикс:** различать «точно не участник» (`member.status in {left, kicked}`) и «неизвестно»
  (исключение/`TelegramRetryAfter`/`TelegramForbidden`) — во втором случае пропускать и логировать;
  штрафовать только после N последовательных подтверждений.

### B-10. Потеря раунда лотереи
- **Где:** `app/services.py:2676` `_get_lottery_window` — ключ раунда суточный (`lottery_YYYYMMDD`), и окно
  переходит на следующий день, как только `now_msk >= draw_start + draw_duration` (~90 с).
  `ensure_current_lottery_round` (`:2727`) ищет раунд по ключу, `lottery_worker` (`main.py:443`) обрабатывает только `status == "open"`.
- **Сценарии:**
  1. Бот офлайн/перезапускался/подвис дольше окна (деплой на Render вечером!) → воркер
     создаёт раунд следующего дня, а вчерашний `open` с билетами и ставками **никогда не разыгрывается и не возвращается**.
  2. Падение в середине розыгрыша (статус `drawing`) → после рестарта раунд не подхватывается никем.
- **Фикс:** при старте воркера выбирать все раунды со `status in (open, drawing)` и `draw_starts_at < now`,
  дорозыгрывать или возвращать средства; ключ окна не должен «перескакивать» при наличии незакрытого раунда.

### B-11. Пользовательские офферы не обеспечены балансом
- **Где:** `app/user_offer_handlers.py:194` `user_offer_payment` — создатель платит один раз
  `max(50, (preview + final) * 0.20 * days / 30)`; `start_offer_participation` (`services.py:1892`) и
  завершение оффера начисляют **каждому** участнику `reward_preview + reward_final` из ничего.
  Лимит участников отсутствует, `reward_final` без верхней границы, единственный тормоз —
  `OFFER_DAILY_REWARD_CAP = 80`/день на пользователя и ручная модерация.
- **Эффект:** оффер «50+500 монет» за 55 монет создателя раздаёт по 550 неограниченному числу людей
  (твинки/сговор). Для non-auto-verify ссылок `reward_final` выдаётся по нажатию кнопки без проверки.
- **Фикс:** эскроу — создатель вносит `(preview + final) * max_participants` (или бюджет), награды списываются
  из бюджета, остаток возвращается по истечении; капы на `reward_final`/участников; `preview` только после проверки подписки.

### B-12. Бустер монет понижает VIP
- **Где:** `app/services.py:3435-3457` `get_coin_multiplier`: сначала `multiplier = VIP_BONUS_MULTIPLIER` (2.0),
  затем при активном перке `coin_multiplier` **перезаписывается** на `1.5`.
- **Эффект:** VIP, купивший бустер в донат-магазине, зарабатывает меньше, чем без него.
- **Фикс:** `multiplier = max(vip, perk)` или произведение — по замыслу экономики.

### B-13. Дрейф схемы БД: Docker-деплой на чистый Postgres не работает **[проверено]**
- **Где:** сравнение `alembic upgrade head` (head `add_user_language_001`) с `Base.metadata`:
  отсутствуют `users.lootbox_pity_counter`, `users.promo_month`, `users.last_freebie_week/year`,
  `users.timezone`, `events.image_file_id` и вся таблица **`promo_messages`**.
  `utils/db_fix.fix_database` догоняет только `last_freebie_*`, `timezone`, `image_file_id`; не создаёт
  `promo_messages` и не добавляет `lootbox_pity_counter`/`promo_month`.
  Render-путь спасает `migrate.py → ensure_model_columns()`, но `Dockerfile` (`CMD python -m app.main`) и
  `docker-compose.yml` (Postgres) его **не запускают**; `on_startup` вызывает `init_db()` только для SQLite
  или если нет таблицы `users`.
- **Эффект:** на свежем Postgres через docker-compose любой `select(User)` падает `UndefinedColumn`,
  бот нерабочий; `promo_messages`-функционал падает всегда.
- **Фикс:** добавить alembic-миграцию, закрывающую дрейф (`alembic revision --autogenerate` даст точный diff);
  в Docker `CMD` запускать `migrate.py` (или вызывать `ensure_model_columns()` из `on_startup` для всех СУБД).

### B-14. Спам админам от DonationAlerts-сверки
- **Где:** `app/main.py:2094-2124` `handle_event` + REST-цикл `:2139-2150`; `record_donationalerts_exception`
  (`services.py:4491-4508`) возвращает существующую запись без признака «уже уведомляли».
- **Эффект:** каждый донат без кода / с несовпадающей суммой / в чужой валюте с первой страницы
  `/alerts/donations` каждые `DONATION_ALERTS_SYNC_INTERVAL_SECONDS` (≥60 с) генерирует сообщение каждому админу —
  бесконечно, даже после закрытия исключения в админке. При первом включении интеграции —
  вся история донатов (до ~30 шт.) × админов × каждую минуту → лимиты Telegram.
- **Фикс:** возвращать из `record_donationalerts_exception` флаг `created`, уведомлять только при создании;
  хранить `last_seen_donation_id` для REST-сверки.

### B-15. Админ-открытие лутбокса за Stars падает
- **Где:** `app/user_handlers.py:2816` — `reward, rarity = _roll_lootbox_reward_coins()`, а функция (`services.py:185`)
  возвращает кортеж из трёх элементов `(reward, rarity, new_pity)` → `ValueError: too many values to unpack`.
- **Фикс:** `reward, rarity, _ = ...` (и учесть pity как в coin-ветке).

### B-16. Бесплатный VIP-промокод — один раз навсегда
- **Где:** `app/user_handlers.py:4047-4050` — `has_free_left = promo_created_this_month < VIP_FREE_PROMO_PER_MONTH`
  без сброса по месяцу; сброс (`promo_month != month_key → promo_created_this_month = 0`) есть только внутри
  `create_promocode` (`services.py:2522-2527`), куда хендлер при `has_free_left == False` уже не идёт (выставляет платный инвойс).
- **Фикс:** вынести сброс месяца в отдельную функцию и вызывать её в хендлере перед проверкой.

### B-17. Повторная награда за одну загрузку
- **Где:** `services.py:967` `reject_video` — нет проверки статуса (работает и для `approved`; используется
  кнопками «убрать из ленты»/жалобы); `:826` `restore_rejected_video` возвращает в `pending`;
  `:950` `approve_video` снова платит `upload_approved`. Также `approve_video`/`approve_all_pending` (`:4030`)
  читают статус и пишут неатомарно → два админа, нажавшие одновременно, платят дважды.
- **Фикс:** флаг `reward_paid_at` на видео / проверка `BalanceLog(source='upload_approved', source_id=video.id)`;
  `UPDATE ... WHERE status='pending'` с проверкой `rowcount`.

### B-18. HTML-инъекция имени в других экранах
- **Где (parse_mode="HTML", имя без экранирования):** подписи к видео `user_handlers.py:1287/1495`,
  топы `:3370/3398/3422/3446`, уведомление об обратной связи ~`:3925`; `admin_handlers.py:469, 1886`;
  профиль/карточки через `get_styled_display_name`. Регулярка ника (`services.py:422`) пропускает `\`.
  Обратная проблема: `cb_comments` (`:1676`) экранирует уже стилизованное имя дважды (`&amp;lt;`).
- **Эффект:** пользователь с `<`/`&` в имени ломает рендер чужих экранов (топы не открываются ни у кого);
  возможна подделка разметки (`<a href>`), ложные «👑».
- **Фикс:** единая точка экранирования в `get_display_name`/`get_styled_display_name` (+ запрет `<>&` в
  `set_display_name`), убрать двойное экранирование.

---

## 3. P2 — ограниченный эффект

### B-19. Лотерея: пул, атомарность, расхождение текста и выплат
- `buy_lottery_tickets` (`services.py:2774`): админские бесплатные билеты (`admin_free`) делают
  `prize_pool += total_cost`, хотя монеты не вносились, и участвуют в розыгрыше пула, оплаченного пользователями.
- `prize_pool += ...` — read-modify-write на ORM-объекте; параллельные покупки теряют инкременты.
- `notify_lottery_results` (`main.py:302+`) считает `per_ticket_3` без минимума `LOTTERY_MATCH3_REWARD`,
  который применяет `settle_lottery_round` (`:2981`) → сумма в сообщении ≠ начисленной.
- Чёт/нечет-ставки выплачиваются ×2 без комиссии — нулевое мат.ожидание для дома (дизайн, но вместе с B-05 даёт
  бесплатный «кран»).
- Обещанные «бочонки в реальном времени» не отправляются (промежуточные числа только в БД).

### B-20. Аудит подписок «голодает»
- **Где:** `services.py:2043` — выборка `limit=OFFER_SUBSCRIPTION_CHECK_BATCH` (200) с `ORDER BY checked_at NULLS FIRST`,
  но `checked_at` при успешной проверке не обновляется.
- **Эффект:** при >200 завершённых участий проверяются всегда одни и те же старейшие записи, новые никогда.
  Плюс участия по давно истёкшим офферам штрафуются бессрочно.
- **Фикс:** писать `checked_at = now()` после каждой проверки; ограничивать аудит сроком оффера.

### B-21. XP за просмотр и за игру не начисляются
- **Где:** экран «Уровень» (`user_handlers.py:1039`) обещает `+XP_PER_WATCH` (15) и `+XP_PER_GAME`;
  в коде `user.xp +=` есть только для рейтинга/комментария/реакции/загрузки (`:1648/1744/1804/1880-1950`).
- **Фикс:** начислять XP в `watch_video_content`/играх или убрать строки из текста.

### B-22. Поиск пользователей ломает `_`
- **Где:** `services.py:1496` `pattern = f"%{q.replace('%','').replace('_',' ')}%"`.
- **Эффект:** `john_doe` ищется как `john doe` — не находится; `_` в Telegram-юзернеймах повсеместен.
- **Фикс:** экранировать `\_`/`\%` и использовать `.like(pattern, escape="\\")`.

### B-23. Привилегии админов
- **Где:** `admin_handlers.py:1786` `cb_admin_user_toggle_ban` и корректировка баланса — нет проверки,
  что цель не супер-админ/админ. (Выдача/снятие админа — только супер, OK.)
- **Фикс:** запретить действия над `is_super_admin(target)` для обычных админов.

### B-24. Платежи Stars
- `successful_payment` (`user_handlers.py:2412`): если `create_promocode` вернул ошибку после оплаты —
  `rollback`, Stars списаны, промокод не создан, рефанда нет; аналогично ветка `lootbox_`.
  Нужен `refund_star_payment` или фиксация платежа + ручная очередь.
- `cb_buy_pack` (`:2136`): в инвойсе не показан вечерний ×1.5 и `FIRST_PURCHASE_DAILY_BONUS` — пользователь
  получает больше, чем видел (можно и ценить, но мешает сверке).

### B-25. Лутбоксы / стили
- Общий `lootbox_pity_counter` на все типы кейсов (common/elite/legendary/styles) — pity, накопленный
  на дешёвом кейсе, срабатывает на дорогом; обновляется неатомарно.
- `open_lootbox_for_stars` (`services.py:270`) всегда крутит таблицу `common`, независимо от купленного кейса.
- `lootbox_menu` (`user_handlers.py:2702`): admin-free ветка пропускает проверку уровня для elite/legendary.
- Кейс стилей вызывает `activate_perk("custom_nick", 7, style_id)` → **перезаписывает** `style_id`
  купленного постоянного стиля на 7-дневный.
- `styles_case_toggle_style` (`:2983`) пишет FSM-state **до** обращения к `STYLES[style_id]` → `KeyError`
  оставляет грязное состояние.

### B-26. Mini App API
- `api_cases_open` (`main.py:3146`): `case_id` не валидируется (неизвестный → `common`, в `BalanceLog`
  попадает сырая строка); в ответ уходит устаревший `float(user.balance)`.
- `api_lottery_place_bet` (`:2268`): нет верхней границы ставки; `api_lottery_buy_coins` (`:2212`):
  описание инвойса расходится с динамической ценой.
- `api_user_timezone` (`:2319`): строка пишется в БД без проверки `zoneinfo`.
- `localized_api` валидирует `initData` и ходит в БД дважды на каждый запрос (производительность).

### B-30. Две разные реализации `_chat_id_from_offer_url` — ссылка на пост не проверяется
- **Где:** `app/user_handlers.py:254` (пользовательская «✅ Проверить подписку») и `app/main.py:146` (аудит).
  Пользовательская версия не отрезает хвост пути: `https://t.me/channel/123` → `@channel/123`;
  `t.me/c/123/45` → `@c/123/45`. Версия в `main.py` берёт первый сегмент (`@channel`).
  `classify_offer_url` (`services.py:139`) такие ссылки считает `auto_verify=True`, админка их принимает.
- **Эффект:** оффер со ссылкой на пост канала невозможно завершить — проверка всегда «не подписан»,
  хотя `reward_preview` уже выдан при входе.
- **Фикс:** оставить одну реализацию (из `main.py`) в `services.py` и использовать в обоих местах.

### B-27. Фоновые задачи / жизненный цикл
- `main()` (`main.py:4109`): `onboarding_task` не отменяется в `finally` (остальные — отменяются).
- `retention_worker` (`:2397`) и `subscription_audit_worker` — полные сканы пользователей/участий
  с N+1 запросами каждые 15/30 мин; drip-сообщения учитываются как «активность» для comeback-бонуса.
- `process_referral_reward` (`services.py:1568`) на **каждый** просмотр реферала пересчитывает всех рефералов инвайтера.
- `admin_router` подключён первым: `cmd_cancel_admin` перехватывает `/cancel` у всех (сейчас безвредно).

---

## 4. P3 — мелочи и UX

### B-28. Тексты и кнопки
- `cb_buy_custom_stars` (`user_handlers.py:2300`): в тексте литеральные `\n\n` и `<b>` без `parse_mode="HTML"`.
- Опечатки: «Твойе обращение», «с тебеи».
- `donation_shop.py:569`: кнопка «назад» с `callback_data="btn_profile"` — такого обработчика нет
  (единственное упоминание), кнопка-пустышка.
- `retention_worker`: «посмотрит 5 видео», фактическое условие — 3.
- `user_offer_handlers.py` шаг оплаты: «Отмена» не чистит FSM-state — пользователь остаётся в сценарии.
- Свой оффер при открытии показывает «Оффер не найден» вместо «это ваш оффер».

### B-29. Код
- `process_comment` (`:1709`): стикер/фото → `Comment(text=None)` → `IntegrityError`; нет лимита длины.
- `handle_video_upload` (`:1836`): для фото проверка ника другая, уведомление модерации с типом `"video"`,
  XP выдаётся до модерации.
- `main.py:3218` `DeprecationWarning: invalid escape sequence '\.'` (станет `SyntaxError` в будущих Python).
- `_show_ad_or_event`: текст события/оффера подставляется без экранирования (админский контент).
- `cmd_start` с `promo_<code>` (`:152`) активирует промокод, минуя `ENABLE_PROMOCODES` и кулдаун.

---

## 5. Кандидаты (не проверялись до конца, стоит взглянуть)

- `check_daily_photo_limit` считает по `func.date(created_at)` (UTC), остальная «сутки» логика — через `_day_start()`;
  возможна рассинхронизация лимитов.
- `get_or_create_user` перезаписывает `username`/`first_name` значениями `None`, если Telegram их не прислал.
- `start_offer_participation`: гонка на `uq_user_offer` → необработанный `IntegrityError` при двойном тапе.
- `get_or_create_game_session` / `get_coin_multiplier`: `scalar_one_or_none()` → `MultipleResultsFound`
  при дублях строк (возможны после гонок).
- `get_current_prices`: флаги скидок берутся только от самого крупного события.
- `flush_mod_notifications`: уведомления только админам из env `ADMINS`, DB-админы не получают.
- `Offer.status` по умолчанию `"approved"` на уровне модели — любой новый путь создания оффера минует модерацию.
- DA OAuth: статический `state` в ссылке авторизации (CSRF при повторной привязке).
- `_validate_telegram_webapp_init_data`: окно 24 ч — replay `initData` в течение суток (приемлемо, но можно сузить).

Проверено и признано корректным (чтобы не тратить время повторно): `activate_promocode` (атомарный инкремент),
`auto_daily_return_bonus` (захват дня через `UPDATE ... WHERE`), `pre_checkout`/`mark_payment_paid_once`,
`cb_da_check_payment`, `welcome_lootbox_claim`, секрет `lottery_draw_next_handler`, движок арены
(серверный RNG), `selfcheck.py`, экономика кейсов (EV ниже цены), динамическое ценообразование.

---

## Рекомендуемый порядок исправления

1. **Сегодня:** B-01, B-02, B-03, B-04, B-15 (однострочные), B-08/B-18 (экранирование в одной точке).
2. **На этой неделе:** B-05 (guard в `change_balance_atomic`), B-06, B-07, B-09, B-13 (миграция + `CMD`), B-14.
3. **Затем:** B-10, B-11 (экономика офферов), B-12, B-16, B-17, B-30, B-19–B-29.

Для каждого фикса по `AGENTS.md`: запись в `CHANGELOG.md`, bump `CURRENT_VERSION` в `app/release_notes.py`,
`python -m py_compile` + `pytest`. Полезно добавить регрессионные тесты на B-01…B-05 (скрипты ниже легко превращаются в тесты).

---

## Приложение A — воспроизведение B-01 (дублирующий `lottery_buy`)

```python
# /tmp/test_lottery_buy_dup.py  (PYTHONPATH=<repo>, BOT_TOKEN=1:a, DATABASE_URL=sqlite+aiosqlite:////tmp/x.db)
import asyncio
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import CallbackQuery
from app.user_handlers import router

async def main():
    cb = MagicMock(spec=CallbackQuery); cb.data = "lottery_buy"
    cb.from_user = MagicMock(id=1); cb.answer = AsyncMock(); cb.message = MagicMock()
    state = MagicMock()
    await router.callback_query.trigger(cb, state=state, bot=MagicMock())

asyncio.run(main())
# -> TypeError: _format_lottery_purchase_summary() missing 2 required positional arguments
```

## Приложение B — воспроизведение B-05 (двойное списание)

```python
# /tmp/test_race.py  (PYTHONPATH=<repo>, BOT_TOKEN=1:a, DATABASE_URL=sqlite+aiosqlite:////tmp/race_test.db)
import asyncio
from decimal import Decimal
from app.db import async_session, init_db
from app.services import get_or_create_user, change_balance_atomic, open_lootbox_for_coins

async def main():
    await init_db()
    async with async_session() as s:
        user, _ = await get_or_create_user(s, 777, "u", "U", None)
        await change_balance_atomic(s, user.id, Decimal(5000) - user.balance, "test")
        await s.commit(); uid = user.id

    async def open_one():
        async with async_session() as s:
            return await open_lootbox_for_coins(s, uid, "legendary")  # цена 5000

    r = await asyncio.gather(open_one(), open_one())
    async with async_session() as s:
        from app.services import get_user_by_id
        print(r, (await get_user_by_id(s, uid)).balance)

asyncio.run(main())
# -> оба открытия успешны; баланс после = 7538 (ожидалось: второе — «недостаточно монет»)
```

## Приложение C — проверка B-04

```python
from app.keyboards import admin_db_keyboard
admin_db_keyboard([("users", "Users"), ("videos", "Videos")])
# -> TypeError: 'tuple' object is not callable
```

## Приложение D — проверка B-13 (дрейф схемы)

```bash
rm -f /tmp/a.db && DATABASE_URL=sqlite+aiosqlite:////tmp/a.db BOT_TOKEN=1:a alembic upgrade head
python - <<'EOF'
import sqlite3; from app.models import Base
con = sqlite3.connect("/tmp/a.db")
db = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
for name, tbl in Base.metadata.tables.items():
    if name not in db: print("MISSING TABLE", name); continue
    cols = {r[1] for r in con.execute(f'pragma table_info("{name}")')}
    miss = {c.name for c in tbl.columns} - cols
    if miss: print(name, "missing:", sorted(miss))
EOF
# events missing: ['image_file_id']
# MISSING TABLE promo_messages
# users missing: ['last_freebie_week','last_freebie_year','lootbox_pity_counter','promo_month','timezone']
```
