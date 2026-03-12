import aiosqlite
from pathlib import Path

class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    message_id INTEGER,
                    chat_id INTEGER,
                    topic_id INTEGER,
                    file_name TEXT,
                    status TEXT,
                    PRIMARY KEY (message_id, chat_id, topic_id)
                )
            """)
            await db.commit()

    async def is_processed(self, message_id, chat_id, topic_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM downloads WHERE message_id = ? AND chat_id = ? AND topic_id = ?",
                (message_id, chat_id, topic_id)
            )
            return await cursor.fetchone() is not None

    async def mark_processed(self, message_id, chat_id, topic_id, file_name):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO downloads (message_id, chat_id, topic_id, file_name, status) VALUES (?, ?, ?, ?, ?)",
                (message_id, chat_id, topic_id, file_name, "completed")
            )
            await db.commit()

    async def filter_unprocessed_ids(self, chat_id: int, topic_id: int, message_ids: list[int]) -> list[int]:
        """Return only IDs that are NOT already in the downloads table for (chat_id, topic_id)."""
        if not message_ids:
            return []

        # Keep ordering stable and avoid huge SQL queries.
        # (Our callers already chunk to small batches.)
        placeholders = ",".join(["?"] * len(message_ids))
        query = (
            "SELECT message_id FROM downloads "
            "WHERE chat_id = ? AND topic_id = ? AND message_id IN (" + placeholders + ")"
        )
        params = [chat_id, topic_id, *message_ids]

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

        processed = {row[0] for row in rows or []}
        return [mid for mid in message_ids if mid not in processed]
