import os
from datetime import datetime, timedelta
from dateutil import tz
from typing import Set, List
from .sheets_repo import (
    get_latest_meeting,
    list_items_for_meeting,
    get_channel_for_meeting_key,
    upsert_hearing_prompt,
    find_meeting_by_title_contains,
)
from .slack_client import SlackClient
from .calendar_participants import fetch_attendees_for_date

DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo")
MEETING_KEY = os.getenv("MEETING_KEY")
MEETING_TITLE_CONTAINS = os.getenv("MEETING_TITLE_CONTAINS", "").strip()

TEMPLATE_BODY = (
    "ヒアリングのご協力をお願いします\n"
    "1. 前回ToDoの状況\n"
    "2. 今回の報告（1〜3点）\n"
    "3. ブロッカー/依頼\n"
    "4. リンク\n\n"
    "このメッセージに返信でOKです（番号付き/箇条書きどちらでも可）。"
)

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    meeting = None
    if MEETING_TITLE_CONTAINS:
        meeting = find_meeting_by_title_contains(MEETING_TITLE_CONTAINS, MEETING_KEY)
    if not meeting:
        meeting = get_latest_meeting(MEETING_KEY)
    if not meeting or not meeting.get("parent_ts"):
        print("[post_hearing] No parent thread found; run post_retrospective first.")
        return
    meeting_id = meeting["meeting_id"]
    parent_ts = os.getenv("PARENT_TS_OVERRIDE", "").strip() or meeting["parent_ts"]
    tzinfo = tz.gettz(DEFAULT_TIMEZONE)
    due_to_reply = (datetime.now(tzinfo) + timedelta(days=1)).strftime("%Y-%m-%d")
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(MEETING_KEY)
    if not channel:
        print("[post_hearing] No channel configured; skipping Slack posts.")
        return
    items = list_items_for_meeting(meeting_id)
    emails: Set[str] = set()
    if (meeting.get("participant_emails") or "").strip():
        emails.update([e.strip() for e in meeting["participant_emails"].split(",") if e.strip()])
    # Prefer Calendar attendees for this meeting date
    att = fetch_attendees_for_date(meeting.get("date", ""), MEETING_KEY)
    emails.update(att)
    # Fallback from action items
    emails.update([i.get("assignee_email") for i in items if i.get("assignee_email")])
    slack = SlackClient()
    if not emails:
        print("[post_hearing] No participant emails found; skipping.")
        return
    # Build a single consolidated message with all mentions at the top
    mentions = []
    email_sid_pairs = []
    for email in sorted(emails):
        sid = slack.lookup_user_id_by_email(email) or ""
        email_sid_pairs.append((email, sid))
        mentions.append(f"<@{sid}>" if sid else email)
    header_line = " ".join(mentions)
    text = header_line + "\n" + TEMPLATE_BODY
    ts = slack.post_message(channel=channel, text=text, thread_ts=parent_ts)
    if ts:
        for _, sid in email_sid_pairs:
            upsert_hearing_prompt(
                meeting_id=meeting_id,
                channel_id=channel,
                parent_ts=parent_ts,
                assignee_slack_id=sid,
                prompt_ts=ts,
                due_to_reply=due_to_reply,
                status="sent",
            )
    print(f"[post_hearing] Posted consolidated prompt for {len(emails)} participants")

if __name__ == "__main__":
    main()
