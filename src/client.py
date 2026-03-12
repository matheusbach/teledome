from pyrogram import Client
from .config import API_ID, API_HASH, DATA_DIR, SESSION_NAME

def get_client():
    if not API_ID or not API_HASH:
        raise ValueError("API_ID and API_HASH must be set in .env file")
        
    return Client(
        name=SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=str(DATA_DIR)
    )
