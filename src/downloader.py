import os
import asyncio
from pathlib import Path
from pyrogram import Client
from pyrogram import errors
from pyrogram.types import Message
from tqdm import tqdm
from .config import DOWNLOADS_DIR, CACHE_DIR
from .db import Database


def _looks_like_expired_file_reference_error(exc: Exception) -> bool:
    msg = str(exc)
    upper = msg.upper()
    return (
        "FILE_REFERENCE_EXPIRED" in upper
        or "FILE_REFERENCE" in upper
        or "FILE_ID_INVALID" in upper
        or "MEDIA_EMPTY" in upper
    )


def _is_transient_download_error(exc: Exception) -> bool:
    if isinstance(exc, (errors.Timeout, errors.InternalServerError, errors.ServiceUnavailable)):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    return False


def _expected_size(message: Message) -> int | None:
    media = None
    if message.photo:
        media = message.photo
    elif message.video:
        media = message.video
    elif message.document:
        media = message.document
    elif message.audio:
        media = message.audio
    elif message.voice:
        media = message.voice
    size = getattr(media, "file_size", None)
    return int(size) if isinstance(size, int) and size > 0 else None

class Downloader:
    def __init__(self, client: Client, db: Database):
        self.client = client
        self.db = db

    async def download_media(self, message: Message, chat_id: int, topic_id: int = 0):
        if not message.media:
            return

        # Always fetch a fresh copy to avoid expired file references/file_ids.
        try:
            fresh = await self.client.get_messages(chat_id, message.id)
            if fresh is not None and not getattr(fresh, "empty", False) and getattr(fresh, "media", None):
                message = fresh
            else:
                # If we can't refresh, proceed with the original; retries below may still work.
                pass
        except Exception:
            # If refresh fails (network/transient), proceed; retries below may still recover.
            pass

        # Determine file name
        target_filename = self.get_target_filename(message)

        # Use the message's chat as the storage identity, not the caller's context.
        message_chat_id = getattr(getattr(message, "chat", None), "id", None)
        storage_chat_id = message_chat_id if isinstance(message_chat_id, int) else chat_id

        # Path structure: downloads/id_cha/[id_topico]/filename
        topic_part = str(topic_id) if topic_id else "no_topic"
        save_path = DOWNLOADS_DIR / str(storage_chat_id) / topic_part
        save_path.mkdir(parents=True, exist_ok=True)
        
        final_path = save_path / target_filename
        
        # Check DB
        if await self.db.is_processed(message.id, storage_chat_id, topic_id):
            print(f"Skipping {target_filename}, already processed.")
            return

        # print(f"Downloading {target_filename}...") # Removed to avoid clutter with tqdm
        
        # Use CACHE_DIR for temporary file
        temp_filename = f"temp_{storage_chat_id}_{topic_id}_{message.id}_{target_filename}"
        temp_path = CACHE_DIR / temp_filename

        # Progress bar
        desc = target_filename
        if len(desc) > 30:
            desc = desc[:27] + "..."

        max_attempts = 4
        backoff_seconds = 1.0

        for attempt in range(1, max_attempts + 1):
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

            pbar = tqdm(total=0, unit="B", unit_scale=True, desc=desc, leave=True)

            def progress(current, total):
                if pbar.total != total:
                    pbar.total = total
                pbar.update(current - pbar.n)

            try:
                # Refresh message every attempt to get a fresh file reference.
                try:
                    fresh = await self.client.get_messages(chat_id, message.id)
                    if fresh is not None and not getattr(fresh, "empty", False) and getattr(fresh, "media", None):
                        message = fresh
                except Exception:
                    # If refresh fails, proceed with the current message; retries may still work.
                    pass

                downloaded_path = await self.client.download_media(
                    message,
                    file_name=str(temp_path),
                    progress=progress,
                )

                if downloaded_path:
                    Path(downloaded_path).rename(final_path)

                    expected = _expected_size(message)
                    actual = final_path.stat().st_size
                    if expected is not None and actual != expected:
                        print(
                            f"Size mismatch for {target_filename}: expected {expected} bytes, got {actual} bytes"
                        )
                        try:
                            final_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                        if attempt < max_attempts:
                            # retry entire download
                            continue
                        else:
                            print(f"Giving up on {target_filename} after size mismatch.")
                            return

                    await self.db.mark_processed(message.id, storage_chat_id, topic_id, str(final_path))
                    return

                print(f"Failed to download {target_filename} - download_media returned None")
                if attempt < max_attempts:
                    continue
                return

            except Exception as e:
                # File reference / file id expired: re-fetch the message and retry.
                if _looks_like_expired_file_reference_error(e):
                    try:
                        fresh = await self.client.get_messages(chat_id, message.id)
                        if fresh is not None and not getattr(fresh, "empty", False) and getattr(fresh, "media", None):
                            message = fresh
                        else:
                            print(f"Error downloading {target_filename}: unable to refresh message media")
                            return
                    except Exception as refresh_exc:
                        print(f"Error downloading {target_filename} (refresh failed): {refresh_exc}")
                        return

                    if attempt < max_attempts:
                        if temp_path.exists():
                            try:
                                temp_path.unlink()
                            except Exception:
                                pass
                        continue
                    print(f"Error downloading {target_filename}: file reference expired and retries exhausted")
                    return

                # Flood wait: respect Telegram's wait time.
                if isinstance(e, errors.FloodWait):
                    wait_s = int(getattr(e, "value", 0) or 0)
                    if attempt >= max_attempts:
                        print(f"Error downloading {target_filename}: {e}")
                        return
                    await asyncio.sleep(max(wait_s, 1))
                    continue

                # Transient issues: exponential backoff.
                if _is_transient_download_error(e):
                    if attempt >= max_attempts:
                        print(f"Error downloading {target_filename}: {e}")
                        return
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 30)
                    continue

                # Non-retryable.
                print(f"Error downloading {target_filename}: {e}")
                return

            finally:
                pbar.close()

    def get_target_filename(self, message: Message) -> str:
        base_name = ""
        extension = ""
        
        # 1. Try to get original filename and extension
        original_filename = None
        if message.document: original_filename = message.document.file_name
        elif message.video: original_filename = message.video.file_name
        elif message.audio: original_filename = message.audio.file_name
        
        if original_filename:
            path = Path(original_filename)
            base_name = path.stem
            extension = path.suffix
        
        # 2. If no base_name (or no original filename), try caption/description
        if not base_name and message.caption:
            base_name = message.caption.split('\n')[0]
            
        # 3. Fallback if still no base_name
        if not base_name:
            if message.photo: base_name = "photo"
            elif message.video: base_name = "video"
            elif message.document: base_name = "document"
            elif message.audio: base_name = "audio"
            elif message.voice: base_name = "voice"
            else: base_name = "unknown"

        # 4. Ensure extension
        if not extension:
            if message.photo: extension = ".jpg"
            elif message.video: extension = ".mp4"
            elif message.audio: extension = ".mp3"
            elif message.voice: extension = ".ogg"
        
        # Sanitize base_name
        base_name = "".join(c for c in base_name if c.isalnum() or c in (' ', '.', '_', '-')).strip()
        
        # Truncate to 120 chars
        if len(base_name) > 120:
            base_name = base_name[:120]
            
        return f"[{message.id}] {base_name}{extension}"
