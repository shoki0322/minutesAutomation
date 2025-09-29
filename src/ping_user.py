import os
import sys
from .sheets_repo import get_latest_meeting, get_channel_for_meeting_key, find_meeting_by_title_contains
from .slack_client import SlackClient

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.ping_user <email> [message]")
        return
    email = sys.argv[1].strip()
    extra = sys.argv[2] if len(sys.argv) >= 3 else "スプレッドシートの記入ありがとうございます。他の方もご記入お願いします。"
    meeting_key = os.getenv("MEETING_KEY")
    title_contains = os.getenv("MEETING_TITLE_CONTAINS", "").strip()
    meeting = None
    if title_contains:
        meeting = find_meeting_by_title_contains(title_contains, meeting_key)
    if not meeting:
        meeting = get_latest_meeting(meeting_key)
    if not meeting or not meeting.get("parent_ts"):
        print("[ping_user] No parent thread to reply to.")
        return
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(meeting.get("meeting_key", ""))
    if not channel:
        print("[ping_user] No channel configured.")
        return
    slack = SlackClient()
    sid = slack.lookup_user_id_by_email(email) or ""
    mention = f"<@{sid}>" if sid else email
    text = f"{mention} {extra}"
    ts = slack.post_message(channel=channel, text=text, thread_ts=meeting.get("parent_ts"))
    print(f"[ping_user] posted ts={ts}")

if __name__ == "__main__":
    main()

