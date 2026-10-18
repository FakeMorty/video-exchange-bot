"""VIP-only personal video playlists.

Playlist rows are deliberately independent of ``User.vip_until``: expiry only
locks the read/write operations below; it never deletes a user's saved data.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BlockedUser, User, UserPlaylist, UserPlaylistItem, Video, VideoView
from app.services import is_vip

MAX_PLAYLISTS_PER_USER = 10
MAX_PLAYLIST_NAME_LENGTH = 50
MAX_PLAYLIST_ITEMS = 100
PLAYLIST_PAGE_SIZE = 10


class PlaylistError(Exception):
    """Expected playlist policy/validation error, identified by a stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def _require_active_vip(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if not user:
        raise PlaylistError("user_not_found")
    if not is_vip(user):
        raise PlaylistError("vip_required")
    return user


async def get_user_playlists(
    session: AsyncSession,
    user_id: int,
) -> list[tuple[UserPlaylist, int]]:
    """Return owned playlists with item counts; expired VIPs cannot read them."""
    await _require_active_vip(session, user_id)
    result = await session.execute(
        select(UserPlaylist, func.count(UserPlaylistItem.id))
        .outerjoin(UserPlaylistItem, UserPlaylistItem.playlist_id == UserPlaylist.id)
        .where(UserPlaylist.user_id == user_id)
        .group_by(UserPlaylist.id)
        .order_by(UserPlaylist.created_at.desc(), UserPlaylist.id.desc())
    )
    return [(playlist, int(item_count)) for playlist, item_count in result.all()]


async def create_user_playlist(
    session: AsyncSession,
    user_id: int,
    name: str,
) -> UserPlaylist:
    """Create one private playlist, only while the owner has active VIP."""
    await _require_active_vip(session, user_id)
    clean_name = " ".join((name or "").split())
    if not clean_name or len(clean_name) > MAX_PLAYLIST_NAME_LENGTH:
        raise PlaylistError("invalid_name")

    count = await session.scalar(
        select(func.count(UserPlaylist.id)).where(UserPlaylist.user_id == user_id)
    )
    if int(count or 0) >= MAX_PLAYLISTS_PER_USER:
        raise PlaylistError("playlist_limit")

    duplicate = await session.scalar(
        select(UserPlaylist.id).where(
            UserPlaylist.user_id == user_id,
            func.lower(UserPlaylist.name) == clean_name.lower(),
        ).limit(1)
    )
    if duplicate:
        raise PlaylistError("duplicate_name")

    playlist = UserPlaylist(user_id=user_id, name=clean_name)
    session.add(playlist)
    try:
        await session.flush()
    except IntegrityError as exc:
        # A concurrent create can race the duplicate-name check. The DB
        # constraint remains the final authority.
        await session.rollback()
        raise PlaylistError("duplicate_name") from exc
    return playlist


async def _get_owned_playlist(
    session: AsyncSession,
    user_id: int,
    playlist_id: int,
) -> UserPlaylist | None:
    return await session.scalar(
        select(UserPlaylist).where(
            UserPlaylist.id == playlist_id,
            UserPlaylist.user_id == user_id,
        )
    )


async def add_video_to_playlist(
    session: AsyncSession,
    user_id: int,
    playlist_id: int,
    video_id: int,
) -> UserPlaylist:
    """Save a previously watched, currently approved video to an owned list."""
    await _require_active_vip(session, user_id)
    playlist = await _get_owned_playlist(session, user_id, playlist_id)
    if not playlist:
        raise PlaylistError("playlist_not_found")

    video = await session.get(Video, video_id)
    if not video or video.status != "approved" or video.content_type != "video":
        raise PlaylistError("video_unavailable")
    author_is_blocked = await session.scalar(
        select(BlockedUser.id).where(
            BlockedUser.user_id == user_id,
            BlockedUser.blocked_user_id == video.uploader_user_id,
        ).limit(1)
    )
    if author_is_blocked:
        raise PlaylistError("author_blocked")

    watched = await session.scalar(
        select(VideoView.id).where(
            VideoView.user_id == user_id,
            VideoView.video_id == video_id,
        ).limit(1)
    )
    if not watched:
        raise PlaylistError("video_not_watched")

    existing = await session.scalar(
        select(UserPlaylistItem.id).where(
            UserPlaylistItem.playlist_id == playlist_id,
            UserPlaylistItem.video_id == video_id,
        ).limit(1)
    )
    if existing:
        raise PlaylistError("already_added")

    item_count = await session.scalar(
        select(func.count(UserPlaylistItem.id)).where(
            UserPlaylistItem.playlist_id == playlist_id
        )
    )
    if int(item_count or 0) >= MAX_PLAYLIST_ITEMS:
        raise PlaylistError("playlist_full")

    session.add(UserPlaylistItem(playlist_id=playlist_id, video_id=video_id))
    try:
        await session.flush()
    except IntegrityError as exc:
        # Concurrent duplicate taps are idempotent from the user's point of view.
        await session.rollback()
        raise PlaylistError("already_added") from exc
    return playlist


async def get_playlist_page(
    session: AsyncSession,
    user_id: int,
    playlist_id: int,
    *,
    offset: int = 0,
    limit: int = PLAYLIST_PAGE_SIZE,
) -> tuple[UserPlaylist, int, list[tuple[UserPlaylistItem, Video]]]:
    """Return an owned playlist and one ordered page of its videos."""
    await _require_active_vip(session, user_id)
    playlist = await _get_owned_playlist(session, user_id, playlist_id)
    if not playlist:
        raise PlaylistError("playlist_not_found")

    total = int(await session.scalar(
        select(func.count(UserPlaylistItem.id)).where(
            UserPlaylistItem.playlist_id == playlist_id
        )
    ) or 0)
    safe_offset = max(0, min(int(offset), MAX_PLAYLIST_ITEMS))
    result = await session.execute(
        select(UserPlaylistItem, Video)
        .join(Video, Video.id == UserPlaylistItem.video_id)
        .where(UserPlaylistItem.playlist_id == playlist_id)
        .order_by(UserPlaylistItem.id.asc())
        .offset(safe_offset)
        .limit(max(1, min(limit, 50)))
    )
    return playlist, total, list(result.all())


async def get_playlist_video(
    session: AsyncSession,
    user_id: int,
    playlist_id: int,
    video_id: int,
) -> tuple[UserPlaylist, Video]:
    """Verify VIP, ownership, and playlist membership before re-playing a video."""
    await _require_active_vip(session, user_id)
    playlist = await _get_owned_playlist(session, user_id, playlist_id)
    if not playlist:
        raise PlaylistError("playlist_not_found")

    video = await session.scalar(
        select(Video)
        .join(UserPlaylistItem, UserPlaylistItem.video_id == Video.id)
        .where(
            UserPlaylistItem.playlist_id == playlist_id,
            UserPlaylistItem.video_id == video_id,
        )
    )
    if not video:
        raise PlaylistError("item_not_found")
    author_is_blocked = await session.scalar(
        select(BlockedUser.id).where(
            BlockedUser.user_id == user_id,
            BlockedUser.blocked_user_id == video.uploader_user_id,
        ).limit(1)
    )
    if author_is_blocked:
        raise PlaylistError("author_blocked")
    return playlist, video


async def remove_video_from_playlist(
    session: AsyncSession,
    user_id: int,
    playlist_id: int,
    video_id: int,
) -> bool:
    """Remove one item from an owned playlist while VIP is active."""
    await _require_active_vip(session, user_id)
    playlist = await _get_owned_playlist(session, user_id, playlist_id)
    if not playlist:
        raise PlaylistError("playlist_not_found")

    item_id = await session.scalar(
        select(UserPlaylistItem.id).where(
            UserPlaylistItem.playlist_id == playlist_id,
            UserPlaylistItem.video_id == video_id,
        ).limit(1)
    )
    if not item_id:
        return False
    await session.execute(delete(UserPlaylistItem).where(UserPlaylistItem.id == item_id))
    return True


async def delete_user_playlist(
    session: AsyncSession,
    user_id: int,
    playlist_id: int,
) -> bool:
    """Delete an owned playlist and its items; this is separate from VIP expiry."""
    await _require_active_vip(session, user_id)
    playlist = await _get_owned_playlist(session, user_id, playlist_id)
    if not playlist:
        return False
    await session.execute(
        delete(UserPlaylistItem).where(UserPlaylistItem.playlist_id == playlist_id)
    )
    await session.execute(delete(UserPlaylist).where(UserPlaylist.id == playlist_id))
    return True
