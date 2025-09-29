import os
import time
from typing import Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
DEFAULT_SCOPES = [
    # Align with get_refresh_token.py for consistency
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.readonly",
]

def get_google_credentials(scopes: Optional[list] = None) -> Credentials:
    scopes = scopes or DEFAULT_SCOPES
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN):
        raise RuntimeError("Missing Google OAuth secrets: GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN")
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=scopes,
    )
    # Force refresh to obtain access token
    request = Request()
    creds.refresh(request)
    # Log expiry
    expires_in = int(creds.expiry.timestamp() - time.time()) if creds.expiry else -1
    print(f"[auth] Google access token refreshed. Expires in ~{expires_in}s")
    return creds
