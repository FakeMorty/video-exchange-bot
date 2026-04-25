# Исправления багов — перевод print в logger

## Прогресс
- [x] Проанализировать кодовую базу и найти проблемы (print, отсутствие logger)
- [x] Составить план правок и получить подтверждение

## Задачи
- [x] Изменить `app/make_project_pdf.py`: заменить все `print()` на вызовы logger, добавить `setup_logging()`, обернуть `main()` в `try/except`
- [x] Изменить `app/user_handlers.py`: заменить `print("START COMMAND RECEIVED")`
- [x] Изменить `app/migrate.py`: заменить `print("Migrations applied successfully")`
- [x] Тест: запустить `python app/make_project_pdf.py` (проверка PDF + логов без print) — УСПЕХ: PDF создан, JSON-логи есть, print нет
- [x] Тест: `python app/migrate.py` (логи) — УСПЕХ: logger инициализируется, запуск есть (ошибка миграции ожидаема при отсутствии таблиц)
- [ ] Запустить бота, `/start` (без print)
- [ ] attempt_completion

**Оценка: 3 файла, очистка для состояния prod-ready**
