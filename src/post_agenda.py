import os
from .sheets_repo import read_rows, get_latest_meeting, set_agenda_posted_ts, get_channel_for_meeting_key
from .slack_client import SlackClient

MEETING_KEY = os.getenv("MEETING_KEY")

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    meeting = get_latest_meeting(MEETING_KEY)
    if not meeting or not meeting.get("parent_ts"):
        print("[post_agenda] No parent thread; ensure post_retrospective done.")
        return
    meeting_id = meeting["meeting_id"]
    thread_ts = meeting["parent_ts"]
    rows = read_rows("agendas")
    agenda = None
    for r in rows:
        if r.get("meeting_id") == meeting_id and r.get("thread_ts") == thread_ts:
            agenda = r
            break
    if not agenda:
        print("[post_agenda] No agenda body found; run build_agenda first.")
        return
    if agenda.get("posted_ts"):
        print(f"[post_agenda] Agenda already posted at {agenda['posted_ts']}")
        return
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(MEETING_KEY)
    if not channel:
        print("[post_agenda] No channel configured; skipping Slack post.")
        return
    slack = SlackClient()
    ts = slack.post_message(channel=channel, text=agenda["body_md"], thread_ts=thread_ts)
    if ts:
        set_agenda_posted_ts(meeting_id, thread_ts, ts)

if __name__ == "__main__":
    main()

