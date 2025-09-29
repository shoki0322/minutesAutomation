import os
from typing import List, Dict, Tuple
from datetime import datetime
from dateutil import parser as dateparser
from .sheets_repo import get_latest_meeting, list_items_for_meeting, upsert_agenda, read_rows, get_channel_for_meeting_key

MEETING_KEY = os.getenv("MEETING_KEY")

def _score_item(item: Dict) -> int:
    score = 0
    due = item.get("due")
    if due:
        try:
            delta = (dateparser.isoparse(due).date() - datetime.utcnow().date()).days
            score += max(0, 30 - min(30, max(0, delta)))  # sooner due -> higher
        except Exception:
            score += 5
    if (item.get("status") or "pending") != "done":
        score += 10
    return score

def _summarize_responses(meeting_id: str) -> Dict[str, str]:
    rows = read_rows("hearing_responses")
    latest_by_user: Dict[str, Dict] = {}
    for r in rows:
        if r.get("meeting_id") != meeting_id:
            continue
        uid = r.get("assignee_slack_id")
        ts = r.get("reply_ts", "0")
        if (uid not in latest_by_user) or (float(ts) > float(latest_by_user[uid]["reply_ts"])):
            latest_by_user[uid] = r
    summaries = {}
    for uid, r in latest_by_user.items():
        highlight = []
        if r.get("reports"):
            highlight.append(r["reports"].splitlines()[0][:80])
        if r.get("blockers"):
            highlight.append(f"ブロッカー: {r['blockers'].splitlines()[0][:80]}")
        summaries[uid] = " / ".join(highlight) if highlight else "(更新なし)"
    return summaries

def _collect_blockers(meeting_id: str) -> List[Tuple[str, str]]:
    rows = read_rows("hearing_responses")
    out = []
    for r in rows:
        if r.get("meeting_id") == meeting_id and r.get("blockers"):
            out.append((r.get("assignee_slack_id", ""), r["blockers"]))
    return out

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    meeting = get_latest_meeting(MEETING_KEY)
    if not meeting or not meeting.get("parent_ts"):
        print("[build_agenda] No parent thread; ensure post_retrospective done.")
        return
    meeting_id = meeting["meeting_id"]
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(MEETING_KEY)
    items = [i for i in list_items_for_meeting(meeting_id) if (i.get("status") or "pending") != "done"]
    items_scored = sorted(items, key=_score_item, reverse=True)
    top3 = items_scored[:3]
    resp = _summarize_responses(meeting_id)
    blockers = _collect_blockers(meeting_id)

    lines = [f"# 合体アジェンダ ({meeting.get('date')})", "", "## Top3",]
    for it in top3:
        assignee = it.get("assignee_slack_id") or it.get("assignee_email") or "Unassigned"
        if assignee.startswith("U"):
            assignee = f"<@{assignee}>"
        due = f"(due: {it['due']})" if it.get("due") else ""
        lines.append(f"- {assignee} : {it['task']} {due}".rstrip())

    lines.append("")
    lines.append("## 人別ハイライト")
    for uid, summary in resp.items():
        who = f"<@{uid}>" if uid else "Unknown"
        lines.append(f"- {who}: {summary}")

    lines.append("")
    lines.append("## ブロッカー/依頼")
    if blockers:
        for uid, bl in blockers:
            who = f"<@{uid}>" if uid else "Unknown"
            first = bl.splitlines()[0][:120]
            lines.append(f"- {who}: {first}")
    else:
        lines.append("- なし")

    body_md = "\n".join(lines)
    upsert_agenda(meeting_id=meeting_id, channel_id=channel or "", thread_ts=meeting["parent_ts"], body_md=body_md, posted_ts="")
    print(f"[build_agenda] Built agenda for meeting {meeting_id} (chars={len(body_md)})")

if __name__ == "__main__":
    main()

