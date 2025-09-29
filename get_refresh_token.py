# get_refresh_token.py（最小・安全版）
import os, sys
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or input("GOOGLE_CLIENT_ID: ").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET") or input("GOOGLE_CLIENT_SECRET: ").strip()

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.readonly",
]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],  # 余計なURIは置かない
    }
}

def main():
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        authorization_prompt_message="\nOpen this URL in your browser to authorize:\n{url}\n",
        success_message="Authorization complete. You can close this tab.",
        access_type="offline",   # ← refresh_token を得るために必要
        prompt="consent",        # ← 初回強制同意
    )
    rt = getattr(creds, "refresh_token", None)
    at = getattr(creds, "token", None)
    if not rt:
        print("refresh_token が返りませんでした。以前の承認を削除して再実行してください。")
        print("https://myaccount.google.com/permissions から該当アプリを削除 → 再実行")
        sys.exit(2)
    print(f"Access Token (preview): {at[:12]}..." if at else "Access Token: <none>")
    print(f"Refresh Token: {rt}")

if __name__ == "__main__":
    main()
