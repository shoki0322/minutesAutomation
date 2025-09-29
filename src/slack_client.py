import os
from typing import Optional, List, Dict, Any
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")

class SlackClient:
    def __init__(self) -> None:
        if not SLACK_BOT_TOKEN:
            self.client = None
            print("[slack] SLACK_BOT_TOKEN not set; Slack actions will be skipped.")
        else:
            self.client = WebClient(token=SLACK_BOT_TOKEN)

    def lookup_user_id_by_email(self, email: str) -> Optional[str]:
        if not self.client:
            return None
        try:
            res = self.client.users_lookupByEmail(email=email)
            return res["user"]["id"]
        except SlackApiError as e:
            print(f"[slack] lookupByEmail failed for {email}: {e}")
            return None

    def post_message(self, channel: str, text: str, thread_ts: Optional[str] = None) -> Optional[str]:
        if not self.client:
            print("[slack] post_message skipped (no token).")
            return None
        try:
            res = self.client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
            ts = res["ts"]
            print(f"[slack] posted message ts={ts} channel={channel} thread_ts={thread_ts or '-'}")
            return ts
        except SlackApiError as e:
            print(f"[slack] post_message error: {e}")
            return None

    def fetch_thread_replies(self, channel: str, thread_ts: str) -> List[Dict[str, Any]]:
        if not self.client:
            print("[slack] fetch_thread_replies skipped (no token).")
            return []
        try:
            replies = []
            cursor = None
            while True:
                res = self.client.conversations_replies(channel=channel, ts=thread_ts, cursor=cursor, limit=200)
                replies.extend(res.get("messages", []))
                cursor = res.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            print(f"[slack] fetched {len(replies)} messages in thread {thread_ts}")
            return replies
        except SlackApiError as e:
            print(f"[slack] conversations_replies error: {e}")
            return []

