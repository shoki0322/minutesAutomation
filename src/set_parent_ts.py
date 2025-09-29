import os
import sys
from .sheets_repo import set_meeting_parent_ts, get_latest_meeting, find_meeting_by_title_contains

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.set_parent_ts <thread_ts>")
        return
    ts = sys.argv[1].strip()
    meeting_key = os.getenv("MEETING_KEY")
    title_contains = os.getenv("MEETING_TITLE_CONTAINS", "").strip()
    meeting = None
    if title_contains:
        meeting = find_meeting_by_title_contains(title_contains, meeting_key)
    if not meeting:
        meeting = get_latest_meeting(meeting_key)
    if not meeting:
        print("[set_parent_ts] No meeting found.")
        return
    set_meeting_parent_ts(meeting["meeting_id"], ts)
    print(f"[set_parent_ts] Updated parent_ts for meeting_id={meeting['meeting_id']} to {ts}")

if __name__ == "__main__":
    main()

