import os
from typing import Optional, Dict
from .sheets_repo import (
    get_latest_meeting,
    find_meeting_by_title_contains,
    get_previous_meeting,
    read_rows,
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
        print("[post_agenda_prev_thread] No current meeting found")
        return
    prev = get_previous_meeting(cur.get("meeting_key", ""), cur.get("date", ""))
    if not prev or not prev.get("parent_ts"):
        print("[post_agenda_prev_thread] No previous meeting with parent_ts found")
        return

    # Try to get agenda body for current meeting
    body = None
    rows = read_rows("agendas")
    for r in rows:
        if r.get("meeting_id") == cur.get("meeting_id") and (r.get("body_md") or "").strip():
            body = r.get("body_md")
            break
    if not body:
        print("[post_agenda_prev_thread] No agenda body found for current meeting; build it first (LLM or docs_only).")
        return

    channel = cur.get("channel_id") or prev.get("channel_id")
    if not channel:
        print("[post_agenda_prev_thread] No Slack channel configured.")
        return

    slack = SlackClient()
    ts = slack.post_message(channel=channel, text=body, thread_ts=prev.get("parent_ts"))
    print(f"[post_agenda_prev_thread] Posted agenda to previous thread: {ts}")


if __name__ == "__main__":
    main()

