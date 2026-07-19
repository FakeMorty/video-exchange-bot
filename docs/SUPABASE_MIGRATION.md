# Переезд базы данных: Neon → Supabase (Free, $0)

> **Зачем:** на Neon free tier весь лимит — 100 CU-часов compute в месяц на проект.
> Бот с фоновыми воркерами (запросы к БД каждые 30–60 сек, 24/7) не даёт compute
> «засыпать», поэтому квота сгорает за ~17 дней, и база замирает до конца месяца.
> На Supabase free **почасовых квот compute нет вообще** — для 24/7-поллинга это
> подходит лучше. Цена вопроса: 500 МБ лимит на размер БД.

---

## Шаг 1. Создать проект Supabase

1. Зайти на https://supabase.com → **Start your project** (можно через GitHub, карта не нужна).
2. **New organization** (если нет) → **New project**:
   - Name: любое, например `video-exchange-bot`
   - Region: **Central EU (Frankfurt)** — ближе к Render
   - Database Password: сгенерировать и **сохранить** (понадобится в строке подключения)
   - Plan: **Free**
3. Подождать ~2 минуты, пока поднимается база.

## Шаг 2. Взять строку подключения (ВАЖНО: pooler, а не direct!)

Project → кнопка **Connect** (сверху) → **Connection String**:

- ❌ **Direct connection** (`db.<ref>.supabase.co:5432`) — **НЕ брать**: она работает
  только по IPv6, а Render free не умеет исходящий IPv6.
- ✅ **Transaction pooler** (порт **6543**), выглядит примерно так:

```
postgresql://postgres.<ref>:<ВАШ_ПАРОЛЬ>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
```

Код бота уже умеет с ней работать: `app/db.py` сам определяет Supabase pooler
и отключает кэш prepared statements (`statement_cache_size=0`), иначе Supavisor
в transaction mode ронял бы запросы с `DuplicatePreparedStatementError`.

## Шаг 3. Подключить бота

1. Render → ваш сервис → **Environment** → поменять `DATABASE_URL` на строку из шага 2
   (можно прямо в формате `postgresql://...` — код сам превратит в `postgresql+asyncpg://`).
2. **Save Changes** → Render передеплоит сервис.
3. При старте бот сам создаст схему (`init_db()` + `alembic upgrade head`) —
   база будет **чистой** (пользователи и балансы начнутся с нуля).
4. Проверить в логах Render: `Polling started`, без ошибок подключения.

## Шаг 4. Вернуть старые данные (после ~1 августа)

Старая Neon-база не удалена — она просто спит до сброса квоты
(начало следующего биллинг-периода Neon, обычно 1-е число месяца UTC).
Когда она оживёт, локально (где есть `postgresql-client` ≥ 14):

```bash
# 1) Снять дамп из ожившего Neon (своя схема public, без владельцев/прав)
pg_dump "postgresql://<user>:<pass>@<host>.neon.tech/<db>?sslmode=require" \
  -n public --no-owner --no-privileges -Fc -f neon_backup.dump

# 2) Залить поверх живой Supabase. --on-conflict-do-nothing нужен, чтобы
#    НЕ затереть пользователей, которые успели зарегистрироваться за время
#    простоя на новой базе: дубликаты PK будут пропущены.
pg_dump "postgresql://<user>:<pass>@<host>.neon.tech/<db>?sslmode=require" \
  -n public --no-owner --no-privileges --data-only --inserts \
  --on-conflict-do-nothing | \
psql "postgresql://postgres.<ref>:<pass>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
```

Нюансы:
- Команда №2 только **доливает** старые строки. Пользователь, который существовал
  и в старой, и в новой базе, останется с **новым** балансом (старая строка пропустится).
  Если нужно наоборот «старые важнее» — скажите, дам вариант с `UPSERT`.
- После переноса старый проект Neon можно удалить из дашборда.

## Лимиты Supabase Free — за чем следить

| Лимит | Значение | Комментарий |
|---|---|---|
| Размер БД | **500 МБ** | Единственный реально важный. Монитор: Project → Database → Database Size. Для метаданных видео/балансов хватит на годы |
| Пауза | после 7 дней **полной** неактивности | Бот ходит в БД постоянно — не грозит |
| Egress | 5 ГБ/мес | Запросы бота мизерные — не грозит |
| Бэкапы | только manual (через `pg_dump`) | Периодически снимайте дамп командой №1 из шага 4 |

## Откат

Если что-то пошло не так — вернуть в Render переменную `DATABASE_URL`
старого Neon. До конца месяца она всё равно спит, а после сброса квоты
снова заработает (но проблема сгорания квоты вернётся — см. ниже).

## P.S. Профилактика

Изменения в `app/middlewares.py` и `app/main.py` (коммит «graceful handling of
Neon compute-quota exhaustion») остаются полезными и на Supabase: при любой
недоступности БД бот вежливо отвечает пользователям и не засоряет логи
пятикилобайтными трейсбеками.
