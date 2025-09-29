import os
from collections import defaultdict
from typing import List, Dict
from .sheets_repo import get_latest_meeting, list_items_for_meeting, get_channel_for_meeting_key, set_meeting_parent_ts
from .slack_client import SlackClient

MEETING_KEY = os.getenv("MEETING_KEY")

def _format_post(items: List[Dict]) -> str:
    groups = defaultdict(list)
    for it in items:
        key = it.get("assignee_slack_id") or it.get("assignee_email") or "Unassigned"
        groups[key].append(it)
    lines = ["今週の振り返り & NextAction"]
    for assignee, tasks in groups.items():
        if assignee.startswith("U") and not assignee.startswith("Unassigned"):
            name = f"<@{assignee}>"
        elif "@" in assignee:
            name = assignee
        else:
            name = "Unassigned"
        for t in tasks:
            due = f"(due: {t['due']})" if t.get("due") else ""
            lines.append(f"- {name} : {t['task']} {due}".rstrip())
    return "\n".join(lines)

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    meeting = get_latest_meeting(MEETING_KEY)
    if not meeting:
        raise RuntimeError("No meeting found.")
    if meeting.get("parent_ts"):
        print(f"[post_retrospective] Already posted. parent_ts={meeting['parent_ts']}")
        return
    meeting_id = meeting["meeting_id"]
    items = [i for i in list_items_for_meeting(meeting_id) if (i.get("status") or "pending") != "done"]
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(MEETING_KEY)
    if not channel:
        print("[post_retrospective] No channel configured; skipping Slack post.")
        return
    text = _format_post(items)
    slack = SlackClient()
    ts = slack.post_message(channel=channel, text=text)
    if ts:
        set_meeting_parent_ts(meeting_id, ts)

if __name__ == "__main__":
    main()

