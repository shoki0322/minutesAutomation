import os
from typing import Optional, Dict
from .sheets_repo import (
    get_latest_meeting,
    find_meeting_by_title_contains,
    read_rows,
    get_channel_for_meeting_key,
)
from .slack_client import SlackClient


def find_meeting_current() -> Optional[Dict[str, str]]:
    mk = os.getenv("MEETING_KEY")
    title = os.getenv("MEETING_TITLE_CONTAINS", "").strip()
    if title:
        return find_meeting_by_title_contains(title, mk)
    return get_latest_meeting(mk)


def main():
    cur = find_meeting_current()
    if not cur:
        print("[post_agenda_new_thread] No current meeting found")
        return
    # Find agenda body for current meeting
    body = None
    rows = read_rows("agendas")
    for r in rows:
        if r.get("meeting_id") == cur.get("meeting_id") and (r.get("body_md") or "").strip():
            body = r.get("body_md")
            break
    if not body:
        print("[post_agenda_new_thread] No agenda body found; build it first (LLM or docs_only).")
        return

    channel = cur.get("channel_id") or get_channel_for_meeting_key(cur.get("meeting_key", ""))
    if not channel:
        print("[post_agenda_new_thread] No Slack channel configured.")
        return

    slack = SlackClient()
    ts = slack.post_message(channel=channel, text=body, thread_ts=None)
    print(f"[post_agenda_new_thread] Posted agenda as new parent: {ts}")


if __name__ == "__main__":
    main()

