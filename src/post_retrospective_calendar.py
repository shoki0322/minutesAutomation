import os
from collections import defaultdict
from typing import List, Dict
import re
from .sheets_repo import (
    get_latest_meeting,
    list_items_for_meeting,
    get_channel_for_meeting_key,
    set_meeting_parent_ts,
    read_rows,
    get_slack_id_for_email,
)
from .slack_client import SlackClient
from .calendar_participants import fetch_attendees_for_date

MEETING_KEY = os.getenv("MEETING_KEY")

def _latest_hearing_summary_by_slack(meeting_id: str) -> Dict[str, str]:
    rows = read_rows("hearing_responses")
    latest: Dict[str, Dict] = {}
    for r in rows:
        if r.get("meeting_id") != meeting_id:
            continue
        uid = r.get("assignee_slack_id") or ""
        ts = r.get("reply_ts") or "0"
        if (uid not in latest) or (float(ts) > float(latest[uid]["reply_ts"])):
            latest[uid] = r
    out: Dict[str, str] = {}
    for uid, r in latest.items():
        line = r.get("todo_status") or r.get("reports") or r.get("blockers") or "(更新なし)"
        out[uid] = (line.splitlines()[0] if line else "(更新なし)")[:120]
    return out

_ASSIGNEE_HINT_RE = re.compile(r"(?:担当|assignee)\s*[:：]\s*\S+@\S+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DUE_LABEL_RE = re.compile(r"(?:期限|due)[:：]?\s*\d{4}-\d{2}-\d{2}")

def _clean_task(text: str) -> str:
    # Remove inline assignee/due/email artifacts to avoid duplication in Slack text
    t = _ASSIGNEE_HINT_RE.sub("", text)
    t = _DUE_LABEL_RE.sub("", t)
    t = _EMAIL_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" -•")

def _format_per_person(attendees: List[str], items: List[Dict], email_to_slack: Dict[str, str], meeting_id: str) -> str:
    # Group items by email
    items_by_email: Dict[str, List[Dict]] = defaultdict(list)
    for it in items:
        em = (it.get("assignee_email") or "").strip().lower()
        if em:
            items_by_email[em].append(it)

    lines = ["人別の振り返り & NextAction（Calendar参加者ベース）"]
    hearing_latest = _latest_hearing_summary_by_slack(meeting_id)
    for email in attendees:
        sid = email_to_slack.get(email)
        mention = f"<@{sid}>" if sid else email
        person_items = items_by_email.get(email, [])
        if not person_items:
            # fallback: show latest hearing summary if available
            fallback = hearing_latest.get(sid or "", "(タスクなし)")
            lines.append(f"- {mention} : {fallback}")
            continue
        for t in person_items:
            due = f"(due: {t['due']})" if t.get("due") else ""
            clean = _clean_task(t.get('task',''))
            lines.append(f"- {mention} : {clean} {due}".rstrip())
    return "\n".join(lines)

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    meeting = get_latest_meeting(MEETING_KEY)
    if not meeting:
        raise RuntimeError("No meeting found.")
    meeting_id = meeting["meeting_id"]
    date_str = meeting["date"]
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(MEETING_KEY)
    if not channel:
        print("[post_retrospective_calendar] No channel configured; skipping Slack post.")
        return

    attendees = fetch_attendees_for_date(date_str, MEETING_KEY)
    if not attendees:
        print("[post_retrospective_calendar] No attendees found from Calendar; falling back to items only.")
    items = [i for i in list_items_for_meeting(meeting_id) if (i.get("status") or "pending") != "done"]

    slack = SlackClient()
    # build email->slack map
    email_to_slack: Dict[str, str] = {}
    for em in attendees:
        sid = get_slack_id_for_email(em) or slack.lookup_user_id_by_email(em) or ""
        if sid:
            email_to_slack[em] = sid

    text = _format_per_person(attendees or [it.get("assignee_email") for it in items if it.get("assignee_email")], items, email_to_slack, meeting_id)

    # Post as a reply in existing thread if present; else as parent
    parent_ts = meeting.get("parent_ts")
    ts = slack.post_message(channel=channel, text=text, thread_ts=parent_ts)
    if ts and not parent_ts:
        set_meeting_parent_ts(meeting_id, ts)

if __name__ == "__main__":
    main()
