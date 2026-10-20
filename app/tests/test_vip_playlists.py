from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import BlockedUser, Base, User, UserPlaylistItem, Video, VideoView, utc_now
from app.playlists import (
    PlaylistError,
    add_video_to_playlist,
    create_user_playlist,
    get_playlist_page,
    get_playlist_video,
    get_user_playlists,
    remove_video_from_playlist,
)


@pytest.mark.asyncio
async def test_vip_playlist_is_hidden_after_expiry_and_restored_after_renewal():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        owner = User(
            telegram_id=710001,
            display_name="Playlist owner",
            balance=Decimal("10"),
            vip_until=utc_now() + timedelta(days=1),
        )
        author = User(
            telegram_id=710002,
            display_name="Video author",
            balance=Decimal("0"),
        )
        session.add_all([owner, author])
        await session.commit()

        video = Video(
            uploader_user_id=author.id,
            content_type="video",
            telegram_file_id="playlist-file",
            telegram_file_unique_id="playlist-file-unique",
            status="approved",
        )
        session.add(video)
        await session.commit()
        session.add(VideoView(user_id=owner.id, video_id=video.id))
        await session.commit()

        playlist = await create_user_playlist(session, owner.id, "Favorites")
        await session.commit()
        await add_video_to_playlist(session, owner.id, playlist.id, video.id)
        await session.commit()

        overview = await get_user_playlists(session, owner.id)
        assert [(entry.name, count) for entry, count in overview] == [("Favorites", 1)]

        # VIP expiry locks every read operation, but does not remove playlist rows.
        owner.vip_until = utc_now() - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(PlaylistError, match="vip_required"):
            await get_user_playlists(session, owner.id)
        with pytest.raises(PlaylistError, match="vip_required"):
            await get_playlist_page(session, owner.id, playlist.id)

        saved_items = await session.scalar(
            select(func.count(UserPlaylistItem.id)).where(
                UserPlaylistItem.playlist_id == playlist.id
            )
        )
        assert saved_items == 1

        # A later VIP renewal unlocks the same playlist and the same saved video.
        owner.vip_until = utc_now() + timedelta(days=30)
        await session.commit()
        playlist, total, page = await get_playlist_page(session, owner.id, playlist.id)
        assert playlist.name == "Favorites"
        assert total == 1
        assert len(page) == 1
        assert page[0][1].id == video.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_playlist_cannot_save_unwatched_content_or_be_read_by_another_user():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        owner = User(
            telegram_id=710011,
            display_name="Playlist owner",
            vip_until=utc_now() + timedelta(days=1),
        )
        stranger = User(
            telegram_id=710012,
            display_name="Another VIP",
            vip_until=utc_now() + timedelta(days=1),
        )
        author = User(telegram_id=710013, display_name="Author")
        session.add_all([owner, stranger, author])
        await session.commit()

        video = Video(
            uploader_user_id=author.id,
            content_type="video",
            telegram_file_id="unwatched-file",
            telegram_file_unique_id="unwatched-file-unique",
            status="approved",
        )
        session.add(video)
        await session.commit()
        playlist = await create_user_playlist(session, owner.id, "Watch later")
        await session.commit()

        with pytest.raises(PlaylistError, match="video_not_watched"):
            await add_video_to_playlist(session, owner.id, playlist.id, video.id)
        with pytest.raises(PlaylistError, match="playlist_not_found"):
            await get_playlist_page(session, stranger.id, playlist.id)

    await engine.dispose()


@pytest.mark.asyncio
async def test_blocked_video_author_cannot_be_added_or_replayed_from_playlist():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        owner = User(
            telegram_id=710021,
            display_name="Playlist owner",
            vip_until=utc_now() + timedelta(days=1),
        )
        author = User(telegram_id=710022, display_name="Blocked author")
        session.add_all([owner, author])
        await session.commit()

        video = Video(
            uploader_user_id=author.id,
            content_type="video",
            telegram_file_id="blocked-file",
            telegram_file_unique_id="blocked-file-unique",
            status="approved",
        )
        session.add(video)
        await session.commit()
        session.add(VideoView(user_id=owner.id, video_id=video.id))
        await session.commit()
        playlist = await create_user_playlist(session, owner.id, "Saved")
        await session.commit()
        await add_video_to_playlist(session, owner.id, playlist.id, video.id)
        await session.commit()

        session.add(BlockedUser(user_id=owner.id, blocked_user_id=author.id))
        await session.commit()
        with pytest.raises(PlaylistError, match="author_blocked"):
            await get_playlist_video(session, owner.id, playlist.id, video.id)

        assert await remove_video_from_playlist(session, owner.id, playlist.id, video.id)
        with pytest.raises(PlaylistError, match="author_blocked"):
            await add_video_to_playlist(session, owner.id, playlist.id, video.id)

    await engine.dispose()


def test_playlist_menu_and_video_save_button_are_present():
    from app.i18n import t
    from app.keyboards import BTN_PLAYLISTS, main_menu, menu_button_variants, video_rating_keyboard

    ru_buttons = [button.text for row in main_menu().keyboard for button in row]
    en_buttons = [button.text for row in main_menu(lang="en").keyboard for button in row]
    video_callbacks = [
        button.callback_data
        for row in video_rating_keyboard(42).inline_keyboard
        for button in row
    ]

    assert BTN_PLAYLISTS in ru_buttons
    assert "🎵 Playlists" in en_buttons
    assert {"🎵 Плейлисты", "🎵 Playlists"} <= menu_button_variants("playlists")
    assert t("en", "menu.playlists") == "🎵 Playlists"
    assert "playlist_add:42" in video_callbacks


@pytest.mark.asyncio
async def test_vercel_webhook_bootstraps_only_playlist_tables(monkeypatch):
    from sqlalchemy import inspect

    import app.db as app_db
    import api.index as vercel_entry

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(app_db, "engine", engine)
    monkeypatch.setattr(vercel_entry, "_playlist_schema_ready", False)

    await vercel_entry._ensure_playlist_schema()
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))

    assert {"user_playlists", "user_playlist_items"} <= tables
    assert "users" not in tables
    await engine.dispose()
