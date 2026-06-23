# Bot Lab — терминальная лаборатория бота

Это место для текущего и будущих ИИ-агентов: можно гонять реальные `aiogram`-роутеры бота без Telegram, webhook и внешнего Bot API.

## Запуск

```bash
python bot_lab/terminal_bot.py
```

По умолчанию используется отдельная SQLite БД:

```text
.bot_lab.sqlite3
```

Она игнорируется `.gitignore` как `*.sqlite3`.

Для полностью чистого запуска в памяти:

```bash
python bot_lab/terminal_bot.py --memory-db
```

## Как пользоваться

Внутри REPL пиши сообщения как пользователь Telegram:

```text
/start
/cancel
/katya
МойНик
💋 Катя
```

Последние кнопки показываются под ответом бота. Их можно нажимать номером:

```text
1
2
3
```

Служебные команды лаборатории:

```text
!buttons                    показать последние кнопки
!seed-demo                  создать демо-видео и демо-оффер
!user 200002 other_user Анна переключить Telegram-пользователя
!reset                      пересоздать FSM/session storage
!quit                       выйти
```

## Демо-данные для просмотра и офферов

Чтобы разделы «Смотреть» и «Офферы» были непустыми, выполни в REPL:

```text
!seed-demo
```

Команда создаёт одного demo-uploader, одно approved-видео и один активный rentable-оффер.

## Проверка сценария Кати

Пример ручного smoke-теста:

```text
/start
1                # принять правила, если появилась inline-кнопка
1                # установить ник, если появилась кнопка
TestNick
/katya           # открыть Катю даже если ReplyKeyboard не видна
2                # например создать новый чат / выбрать пункт
```

В Bot Lab ответы Кати по умолчанию фейковые: внешний AI API не вызывается. Это сделано, чтобы агенты могли тестировать FSM, кнопки, списание баланса и БД без секретов и сети.

Если специально нужно проверить реальный AI API:

```bash
AI_ASSISTANT_API_KEY=... python bot_lab/terminal_bot.py --real-ai
```

## Что именно эмулируется

- реальные роутеры `admin_router`, `user_router`, `user_offer_router`, `donation_router`, `ai_router`;
- реальные `Message` и `CallbackQuery` updates через `Dispatcher.feed_update()`;
- реальные FSM-состояния aiogram через `MemoryStorage`;
- реальные модели и сервисы БД через `app.db.init_db()`;
- фейковая Telegram Bot API session: `sendMessage`, `editMessageText`, `answerCallbackQuery`, `sendPhoto`, `sendSticker`, `getChatMember` и т.д. не уходят в сеть, а печатаются в терминал.

## Важно

Не запускай с `--use-env`, если в окружении настроена production `DATABASE_URL`: этот режим нужен только для осознанной диагностики.
