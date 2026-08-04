import os

# Общая тестовая БД — ОБЯЗАТЕЛЬНО файл (не :memory:):
# ":memory:"-движок создаёт ОТДЕЛЬНУЮ БД на каждое соединение пула, и любой
# тест, работающий через общий app.db.async_session, внезапно видел
# "no such table" на соседних соединениях. Файл даёт нормальную семантику
# пула. Файл удаляется на старте прогона, чтобы каждый запуск был чистым.
_PYTEST_DB = "/tmp/pytest_bot_full.db"

if not os.environ.get("DATABASE_URL"):
    if os.path.exists(_PYTEST_DB):
        os.remove(_PYTEST_DB)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_PYTEST_DB}"
