from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_on_startup_only_runs_initialization_steps():
    import app.main as main

    app = {"bot": object()}

    with (
        patch.object(main, "init_db", AsyncMock()) as init_db,
        patch("app.utils.db_fix.fix_database", AsyncMock()) as fix_database,
        patch.object(main, "_notify_admins_started", AsyncMock()) as notify_admins,
        patch("app.ai_assistant.load_sticker_set", AsyncMock()) as load_sticker_set,
        patch.object(main.web, "AppRunner") as app_runner_cls,
        patch.object(main.asyncio, "create_task") as create_task,
    ):
        await main.on_startup(app)

    init_db.assert_awaited_once()
    fix_database.assert_awaited_once()
    notify_admins.assert_awaited_once_with(app["bot"])
    load_sticker_set.assert_awaited_once_with(app["bot"])
    app_runner_cls.assert_not_called()
    create_task.assert_not_called()
