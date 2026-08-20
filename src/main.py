import sys
import asyncio
import time

# Windows async compatibility
#
# Pyrogram/PyroFork + some async networking stacks can hang or misbehave on
# Windows when running under the default ProactorEventLoop (Python 3.8+).
# Setting the selector loop policy early (module import time) mirrors common
# community patterns and ensures any loop created later uses the selector.
if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import click

from .client import get_client
from .db import Database
from .config import DATA_DIR
from .utils import get_channels, get_topics, get_topic_message_ids, clean_cache
from .downloader import Downloader
from . import __version__

from pyrogram import Client


def parse_chat_choices(
    raw: str, channels: list[tuple[int, str, str]]
) -> list[tuple[int, str]]:
    raw = (raw or "").strip()
    if not raw:
        return []

    by_index: dict[int, tuple[int, str, str]] = {i + 1: c for i, c in enumerate(channels)}
    by_id: dict[int, tuple[int, str, str]] = {
        cid: (cid, title, ctype) for cid, title, ctype in channels
    }

    selected: list[tuple[int, str]] = []
    seen: set[int] = set()
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    for token in tokens:
        try:
            n = int(token)
        except ValueError:
            continue

        if 1 <= n <= len(channels):
            cid, title, _ = by_index[n]
        else:
            entry = by_id.get(n)
            if entry is None:
                # Keep the old behavior: allow manual IDs even if not present in the list.
                cid, title = n, "Unknown"
            else:
                cid, title, _ = entry

        if cid in seen:
            continue
        seen.add(cid)
        selected.append((cid, title))

    return selected


async def run_async(app: Client):
    # Clean Cache
    clean_cache()
    
    # Init DB
    db = Database(DATA_DIR / "history.db")
    await db.init()

    await app.start()
    try:
        user = await app.get_me()
        click.echo(f"Logged in as {user.first_name}")

        # 1. Select Channel
        channels = await get_channels(app)
        if not channels:
            click.echo("No channels found.")
            return

        click.echo("\nAvailable Chats:")
        for idx, (cid, title, ctype) in enumerate(channels):
            click.echo(f"{idx + 1}. [{ctype}] {title} (ID: {cid})")
        
        choice = click.prompt(
            "\nSelect chat(s) (number(s) or ID(s); comma separated)",
            type=str,
        )

        selected_chats = parse_chat_choices(choice, channels)
        if not selected_chats:
            click.echo("Invalid selection.")
            return

        multi_chat_mode = len(selected_chats) > 1
        if multi_chat_mode:
            click.echo(
                f"Selected {len(selected_chats)} chats. Skipping message range selection (full download)."
            )
        else:
            cid, title = selected_chats[0]
            click.echo(f"Selected Chat: {title} (ID: {cid})")

        # 2/3. Topics + Range selection
        chat_jobs: list[dict] = []

        async def latest_message_id(chat_id: int) -> int:
            latest = None
            async for msg in app.get_chat_history(chat_id, limit=1):
                latest = msg
                break
            return int(latest.id) if latest else 0

        def pick_topics(topics: list[tuple[int, str, int]]):
            selected_topic_ids: set[int] | None = None
            selected_topic_titles_by_id: dict[int, str] = {}
            selected_topic_top_message_by_id: dict[int, int] = {}

            click.echo("\nAvailable Topics:")
            for idx, (tid, title, top_msg) in enumerate(topics):
                click.echo(f"{idx + 1}. {title} (ID: {tid})")
                selected_topic_top_message_by_id[tid] = top_msg

            t_choice = click.prompt(
                "\nSelect topics (comma separated numbers/IDs, e.g. 1,3,34316; or 0 for All)",
                type=str,
                default="0",
            )

            t_choice = (t_choice or "0").strip()
            if t_choice != "0":
                by_index: dict[int, tuple[int, str, int]] = {i + 1: t for i, t in enumerate(topics)}
                by_id: dict[int, str] = {tid: title for tid, title, _ in topics}

                chosen_ids: set[int] = set()
                for raw_token in t_choice.split(","):
                    token = raw_token.strip()
                    if not token:
                        continue
                    if not token.isdigit():
                        continue

                    n = int(token)
                    if 1 <= n <= len(topics):
                        tid, title, _ = by_index[n]
                        chosen_ids.add(tid)
                        selected_topic_titles_by_id[tid] = title
                    else:
                        tid = n
                        title = by_id.get(tid)
                        if title is None:
                            click.echo(f"Warning: topic ID {tid} not found in list; ignored.")
                            continue
                        chosen_ids.add(tid)
                        selected_topic_titles_by_id[tid] = title

                if chosen_ids:
                    selected_topic_ids = chosen_ids

            if selected_topic_ids is None:
                click.echo("Selected Topics: All")
            else:
                summary = ", ".join(
                    f"{selected_topic_titles_by_id.get(tid, 'Unknown')} (ID: {tid})"
                    for tid in sorted(selected_topic_ids)
                )
                click.echo(f"Selected Topics: {summary}")

            return selected_topic_ids, selected_topic_titles_by_id, selected_topic_top_message_by_id

        if multi_chat_mode:
            # Multi-chat: no message range prompt; full download per chat.
            # If a chat is a forum, we implicitly select ALL topics (no filtering).
            for selected_chat_id, selected_chat_title in selected_chats:
                max_id = await latest_message_id(selected_chat_id)
                if max_id == 0:
                    click.echo(f"Chat '{selected_chat_title}' appears to be empty. Skipping.")
                    continue
                chat_jobs.append(
                    {
                        "chat_id": selected_chat_id,
                        "chat_title": selected_chat_title,
                        "selected_topic_ids": None,
                        "selected_topic_titles_by_id": {},
                        "start_id": 1,
                        "end_id": max_id,
                    }
                )
        else:
            # Single chat: if forum, show topic selection.
            selected_chat_id, selected_chat_title = selected_chats[0]

            topics = await get_topics(app, selected_chat_id)
            forum_has_topics = bool(topics)

            selected_topic_ids: set[int] | None = None
            selected_topic_titles_by_id: dict[int, str] = {}
            selected_topic_top_message_by_id: dict[int, int] = {}

            if forum_has_topics:
                (
                    selected_topic_ids,
                    selected_topic_titles_by_id,
                    selected_topic_top_message_by_id,
                ) = pick_topics(topics)
            else:
                click.echo("No topics found for this chat (Standard Group/Channel).")

            # Determine upper bound.
            max_id = 0
            if selected_topic_ids is not None and selected_topic_ids:
                for tid in selected_topic_ids:
                    top_msg = selected_topic_top_message_by_id.get(tid)
                    if isinstance(top_msg, int) and top_msg > max_id:
                        max_id = top_msg
            else:
                max_id = await latest_message_id(selected_chat_id)

            if max_id == 0:
                click.echo("Chat appears to be empty.")
                return

            # Range selection rules:
            # - If exactly 1 topic is selected: show range prompt
            # - If multiple topics OR ALL topics: skip range (full)
            # - Non-forum chats: show range prompt
            should_prompt_range = True
            if forum_has_topics:
                if selected_topic_ids is not None and len(selected_topic_ids) == 1:
                    should_prompt_range = True
                else:
                    should_prompt_range = False

            if should_prompt_range:
                click.echo("\nDownload Options:")
                click.echo("1. All messages")
                click.echo("2. From specific ID (to newest)")
                click.echo("3. Range (Start-End)")

                range_choice = click.prompt("Select option", type=int, default=1)

                start_id = 1
                end_id = max_id

                if range_choice == 2:
                    start_id = click.prompt("Enter start message ID", type=int, default=start_id)
                elif range_choice == 3:
                    start_id = click.prompt("Enter start message ID", type=int, default=start_id)
                    end_id = click.prompt("Enter end message ID", type=int, default=max_id)
            else:
                start_id = 1
                end_id = max_id

            chat_jobs.append(
                {
                    "chat_id": selected_chat_id,
                    "chat_title": selected_chat_title,
                    "selected_topic_ids": selected_topic_ids,
                    "selected_topic_titles_by_id": selected_topic_titles_by_id,
                    "start_id": start_id,
                    "end_id": end_id,
                }
            )

        if not chat_jobs:
            click.echo("Nothing to download.")
            return

        # 4. Media Types (global)
        media_map = {
            1: "photo",
            2: "video",
            3: "document",
            4: "audio",
            5: "voice",
        }
        click.echo("\nMedia Types:")
        for key, value in media_map.items():
            click.echo(f"{key}. {value}")

        media_input = click.prompt(
            "Select media types (comma separated numbers, e.g. 1,2)",
            type=str,
            default="1,2,3,4,5",
        )

        media_types: list[str] = []
        try:
            selected_indices = [int(x.strip()) for x in media_input.split(",")]
            for idx in selected_indices:
                if idx in media_map:
                    media_types.append(media_map[idx])
        except ValueError:
            click.echo("Invalid input. Defaulting to all.")
            media_types = list(media_map.values())

        if not media_types:
            media_types = list(media_map.values())

        click.echo(f"Selected: {', '.join(media_types)}")

        # Start Download
        downloader = Downloader(app, db)

        processed_count = 0
        batch_size = 200
        
        def should_download_message(message) -> bool:
            if "photo" in media_types and message.photo:
                return True
            if "video" in media_types and message.video:
                return True
            if "document" in media_types and message.document:
                return True
            if "audio" in media_types and message.audio:
                return True
            if "voice" in media_types and message.voice:
                return True
            return False

        async def process_message_ids(chat_id: int, selected_topic_ids: set[int] | None, ids_to_fetch: list[int]):
            nonlocal processed_count
            messages = await app.get_messages(chat_id, ids_to_fetch)
            if not isinstance(messages, list):
                messages = [messages]

            for message in messages:
                if message is None or message.empty:
                    continue

                message_topic_id = getattr(message, "message_thread_id", None) or 0
                if selected_topic_ids is not None and message_topic_id not in selected_topic_ids:
                    continue

                if should_download_message(message):
                    processed_count += 1
                    await downloader.download_media(message, chat_id, message_topic_id)

        for job in chat_jobs:
            selected_chat_id = job["chat_id"]
            selected_chat_title = job["chat_title"]
            selected_topic_ids = job["selected_topic_ids"]
            selected_topic_titles_by_id = job["selected_topic_titles_by_id"]
            start_id = job["start_id"]
            end_id = job["end_id"]

            if selected_topic_ids is None:
                click.echo(
                    f"\nStarting download for '{selected_chat_title}' from ID {start_id} to {end_id} (Chronological)..."
                )
            else:
                click.echo(
                    f"\nStarting download for '{selected_chat_title}' from ID {start_id} to {end_id} (Selected topic(s))..."
                )

            current_id = start_id

            if selected_topic_ids is None:
                # No topic filtering: scan message IDs in the whole chat range.
                while current_id <= end_id:
                    next_id = min(current_id + batch_size, end_id + 1)
                    ids_to_fetch = list(range(current_id, next_id))
                    if not ids_to_fetch:
                        break

                    try:
                        await process_message_ids(selected_chat_id, None, ids_to_fetch)
                    except Exception as e:
                        click.echo(f"Error fetching batch {current_id}-{next_id}: {e}")

                    current_id = next_id
                    click.echo(f"Scanned up to ID {current_id-1}...", nl=False)
                    click.echo("\r", nl=False)
            else:
                # Topic filtering: fetch only message IDs that belong to the selected topic threads.
                click.echo("Fetching message IDs from selected topic(s)...")

                total_ids = 0
                for tid in sorted(selected_topic_ids):
                    try:
                        topic_ids = await get_topic_message_ids(
                            app,
                            selected_chat_id,
                            topic_id=tid,
                            min_id=start_id,
                            max_id=end_id,
                        )
                    except Exception as e:
                        click.echo(f"Error fetching topic {tid} messages: {e}")
                        continue

                    topic_ids = sorted(set(topic_ids))
                    total_ids += len(topic_ids)
                    topic_title = selected_topic_titles_by_id.get(tid, "(unknown title)")
                    click.echo(f"Topic {tid}: {len(topic_ids)} messages in range")
                    click.echo(f"Downloading topic {tid} - {topic_title}...")

                    for i in range(0, len(topic_ids), batch_size):
                        chunk = topic_ids[i : i + batch_size]
                        try:
                            # Avoid extra API calls: skip messages already downloaded for this (chat, topic).
                            chunk = await db.filter_unprocessed_ids(selected_chat_id, tid, chunk)
                            if not chunk:
                                continue
                            await process_message_ids(selected_chat_id, selected_topic_ids, chunk)
                        except Exception as e:
                            click.echo(f"Error fetching topic {tid} chunk starting at index {i}: {e}")

                    click.echo(f"Finished topic {tid} - {topic_title}")

                click.echo(f"Total messages to scan (topics only): {total_ids}")
        
        click.echo(f"\nFinished. Processed {processed_count} downloads.")
    finally:
        await app.stop()

@click.command()
def main():
    """Teledome: Telegram Download Media CLI"""
    title = "Teledome: Telegram Download Media"
    repo = "https://github.com/matheusbach/teledome"
    version = f"v{__version__}"

    lines = [title, version, repo]
    inner_width = max(len(s) for s in lines)
    top = "┌" + ("─" * (inner_width + 2)) + "┐"
    bottom = "└" + ("─" * (inner_width + 2)) + "┘"

    click.secho(top, bold=True)
    click.secho(f"│ {title.ljust(inner_width)} │", bold=True)
    click.echo(f"│ {version.ljust(inner_width)} │")
    click.echo(f"│ {repo.ljust(inner_width)} │")
    click.secho(bottom, bold=True)
    click.echo("")
    time.sleep(1)
    try:
        app = get_client()
    except ValueError as e:
        click.echo(f"Error: {e}")
        return

    try:
        # Use Pyrogram's built-in loop runner; this matches how many Pyrogram/
        # PyroFork projects bootstrap on Windows and avoids asyncio.run()
        # creating a fresh loop with a different policy.
        app.run(run_async(app))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
