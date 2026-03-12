from pyrogram import Client
from pyrogram.enums import ChatType
from typing import List, Tuple
import shutil
import re
from pyrogram.raw.functions.messages import (
    GetDialogs,
    GetDialogFilters,
    GetForumTopics as RawGetForumTopics,
    GetReplies as RawGetReplies,
)
from pyrogram.raw.types import InputPeerEmpty
from .config import CACHE_DIR

def clean_cache():
    """Removes all files in the cache directory."""
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        CACHE_DIR.mkdir(exist_ok=True)

def sanitize_sort_key(text: str) -> str:
    """Removes non-alphanumeric characters for sorting."""
    # Keep only alphanumeric chars (including accents) and convert to lower
    return re.sub(r'[^\w]', '', text).lower()


def _raw_chat_to_entry(raw_chat) -> Tuple[int, str, str] | None:
    raw_type = type(raw_chat).__name__
    raw_id = getattr(raw_chat, "id", None)
    if raw_id is None:
        return None

    title = getattr(raw_chat, "title", None) or "No Title"

    if raw_type == "Channel":
        pyrogram_id = int(f"-100{raw_id}")
        if getattr(raw_chat, "megagroup", False):
            chat_type = "Forum" if getattr(raw_chat, "forum", False) else "Supergroup"
        else:
            chat_type = "Channel"
        return (pyrogram_id, title, chat_type)

    if raw_type == "Chat":
        pyrogram_id = -int(raw_id)
        return (pyrogram_id, title, "Group")

    return None


async def _get_dialog_folder_ids(app: Client) -> set[int]:
    """Return IDs of user-defined dialog folders (chat filters)."""
    folder_ids: set[int] = set()
    try:
        filters_obj = await app.invoke(GetDialogFilters())
    except Exception:
        return folder_ids

    # pyrofork returns messages.DialogFilters with a `.filters` attribute
    filters = getattr(filters_obj, "filters", None)
    if filters is None:
        # Fallback if the lib returns a bare list
        filters = filters_obj

    for f in filters or []:
        fid = getattr(f, "id", None)
        if isinstance(fid, int):
            folder_ids.add(fid)

    return folder_ids


async def _get_chats_from_folder(app: Client, folder_id: int | None) -> List[Tuple[int, str, str]]:
    """Fetch chats from a Telegram dialog folder.

    Note: Telegram uses folder_id=1 for Archive; other IDs can be user folders.
    """
    results: dict[int, Tuple[int, str, str]] = {}

    offset_date = 0
    offset_id = 0
    offset_peer = InputPeerEmpty()
    limit = 100

    while True:
        dialogs = await app.invoke(
            GetDialogs(
                offset_date=offset_date,
                offset_id=offset_id,
                offset_peer=offset_peer,
                limit=limit,
                hash=0,
                folder_id=folder_id,
            )
        )

        raw_chats = {getattr(c, "id", None): c for c in getattr(dialogs, "chats", [])}
        raw_messages = {getattr(m, "id", None): m for m in getattr(dialogs, "messages", [])}

        raw_dialogs = getattr(dialogs, "dialogs", [])
        if not raw_dialogs:
            break

        for d in raw_dialogs:
            peer = getattr(d, "peer", None)
            if peer is None:
                continue

            peer_chat_id = getattr(peer, "chat_id", None)
            peer_channel_id = getattr(peer, "channel_id", None)

            raw_chat = None
            if peer_channel_id is not None:
                raw_chat = raw_chats.get(peer_channel_id)
            elif peer_chat_id is not None:
                raw_chat = raw_chats.get(peer_chat_id)

            if raw_chat is None:
                continue

            entry = _raw_chat_to_entry(raw_chat)
            if entry is None:
                continue

            # Keep only group/channel/supergroup/forum
            results[entry[0]] = entry

        # Pagination: use last dialog
        last = raw_dialogs[-1]
        last_peer = last.peer
        last_peer_chat_id = getattr(last_peer, "chat_id", None)
        last_peer_channel_id = getattr(last_peer, "channel_id", None)

        if last_peer_channel_id is not None:
            offset_peer = await app.resolve_peer(int(f"-100{last_peer_channel_id}"))
        elif last_peer_chat_id is not None:
            offset_peer = await app.resolve_peer(-int(last_peer_chat_id))
        else:
            break

        offset_id = getattr(last, "top_message", 0) or 0
        last_msg = raw_messages.get(offset_id)
        offset_date = getattr(last_msg, "date", 0) or 0

        if len(raw_dialogs) < limit:
            break

    return list(results.values())

async def get_channels(app: Client) -> List[Tuple[int, str, str]]:
    print("Scanning chats (Main + Archive + Folders)...")

    by_id: dict[int, Tuple[int, str, str]] = {}

    folder_ids = await _get_dialog_folder_ids(app)
    # main dialogs: folder_id=None; archive: 1; user folders: their IDs
    folder_ids_to_scan: list[int | None] = [None, 1, *sorted(folder_ids)]

    scanned_total = 0
    for folder_id in folder_ids_to_scan:
        try:
            folder_chats = await _get_chats_from_folder(app, folder_id)
        except Exception as e:
            # Some accounts may have dialog filters that can't be queried via getDialogs(folder_id=...)
            # Keep output clean: silently skip invalid/unavailable folders.
            continue
        scanned_total += len(folder_chats)
        for chat_id, title, chat_type in folder_chats:
            by_id[chat_id] = (chat_id, title, chat_type)

    channels = list(by_id.values())
    channels.sort(key=lambda x: sanitize_sort_key(x[1]))

    print(
        f"Folders scanned: {folder_ids_to_scan} | "
        f"Chats scanned: {scanned_total} | "
        f"Chats listed: {len(channels)}"
    )
    return channels

async def get_topics(app: Client, chat_id: int) -> List[Tuple[int, str, int]]:
    topics: List[Tuple[int, str, int]] = []
    try:
        peer = await app.resolve_peer(chat_id)
        res = await app.invoke(
            RawGetForumTopics(
                peer=peer,
                offset_date=0,
                offset_id=0,
                offset_topic=0,
                limit=100,
                q=None,
            )
        )

        for t in getattr(res, "topics", []) or []:
            tid = getattr(t, "id", None)
            title = getattr(t, "title", None)
            top_message = getattr(t, "top_message", None)
            if isinstance(tid, int) and isinstance(title, str) and isinstance(top_message, int):
                topics.append((tid, title, top_message))

    except Exception as e:
        # If the chat is not a forum, treat it as a normal no-topics case.
        msg = str(e)
        if "CHAT_NOT_FORUM" in msg or "not a forum" in msg.lower():
            return []
        print(f"Error getting topics: {e}")
        return []

    return topics


async def get_topic_message_ids(
    app: Client,
    chat_id: int,
    topic_id: int,
    min_id: int,
    max_id: int,
    *,
    batch_size: int = 100,
) -> List[int]:
    """Return message IDs belonging to a forum topic thread.

    On this pyrofork/pyrogram version, raw `messages.GetReplies` expects
    `msg_id` to be the forum `topic_id` (not the topic's top_message).
    """
    peer = await app.resolve_peer(chat_id)

    ids: List[int] = []
    seen: set[int] = set()
    offset_id = 0

    while True:
        res = await app.invoke(
            RawGetReplies(
                peer=peer,
                msg_id=topic_id,
                offset_id=offset_id,
                offset_date=0,
                add_offset=0,
                limit=batch_size,
                max_id=max_id,
                min_id=min_id,
                hash=0,
            )
        )

        batch = []
        for m in getattr(res, "messages", []) or []:
            mid = getattr(m, "id", None)
            if not isinstance(mid, int):
                continue
            if mid in seen:
                continue
            seen.add(mid)
            batch.append(mid)

        if not batch:
            break

        ids.extend(batch)

        if len(batch) < batch_size:
            break

        # Continue pagination from the smallest id we received.
        offset_id = min(batch)

    return ids
