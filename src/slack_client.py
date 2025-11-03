import os
from typing import Optional, List, Dict, Any
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "").strip()
try:
    from .text_normalize import normalize_slack_shortcodes
except Exception:
    # フォールバック: 正規化なし
    def normalize_slack_shortcodes(text: str) -> str:
        return text

class SlackClient:
    def __init__(self, token: str | None = None) -> None:
        tok = (token or SLACK_BOT_TOKEN).strip()
        if not tok:
            self.client = None
            print("[slack] SLACK_BOT_TOKEN not set; Slack actions will be skipped.")
        else:
            self.client = WebClient(token=tok)

    def lookup_user_id_by_email(self, email: str) -> Optional[str]:
        if not self.client:
            return None
        try:
            res = self.client.users_lookupByEmail(email=email)
            return res["user"]["id"]
        except SlackApiError as e:
            print(f"[slack] lookupByEmail failed for {email}: {e}")
            return None

    def _try_join_channel(self, channel: str) -> bool:
        if not self.client:
            return False
        try:
            # conversations_join は既に参加済みでも成功する
            self.client.conversations_join(channel=channel)
            print(f"[slack] joined channel {channel}")
            return True
        except SlackApiError as e:
            print(f"[slack] conversations_join error for {channel}: {e}")
            return False

    def post_message(self, channel: str, text: str, thread_ts: Optional[str] = None, blocks: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
        if not self.client:
            print("[slack] post_message skipped (no token).")
            return None
        try:
            # 日本語エイリアスの絵文字短縮系をUnicodeに正規化
            safe_text = normalize_slack_shortcodes(text)
            res = self.client.chat_postMessage(channel=channel, text=safe_text, thread_ts=thread_ts, blocks=blocks)
            ts = res["ts"]
            print(f"[slack] posted message ts={ts} channel={channel} thread_ts={thread_ts or '-'}")
            return ts
        except SlackApiError as e:
            err = getattr(e, 'response', {}).get('data', {}).get('error') if hasattr(e, 'response') else None
            print(f"[slack] post_message error (first attempt): {e}")
            # チャンネル未参加時は参加して再試行
            if err == "not_in_channel":
                if self._try_join_channel(channel):
                    try:
                        res = self.client.chat_postMessage(channel=channel, text=safe_text, thread_ts=thread_ts, blocks=blocks)
                        ts = res["ts"]
                        print(f"[slack] posted message after join ts={ts} channel={channel}")
                        return ts
                    except SlackApiError as e2:
                        print(f"[slack] post_message error after join: {e2}")
                        return None
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

