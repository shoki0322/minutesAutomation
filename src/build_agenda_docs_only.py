import os
from typing import Dict, List
from .sheets_repo import (
    get_latest_meeting,
    find_meeting_by_title_contains,
    get_previous_meeting,
    read_rows,
    upsert_agenda,
    get_channel_for_meeting_key,
)
from .google_clients import docs as docs_client

# Reuse parsers from doc_section_extract
from .doc_section_extract import _extract_text as doc_text, _parse_by_names

MEETING_KEY = os.getenv("MEETING_KEY")

def latest_hearing_highlights(meeting_id: str) -> Dict[str, Dict[str, str]]:
    rows = read_rows("hearing_responses")
    latest: Dict[str, Dict[str, str]] = {}
    for r in rows:
        if r.get("meeting_id") != meeting_id:
            continue
        uid = r.get("assignee_slack_id") or ""
        ts = r.get("reply_ts") or "0"
        if (uid not in latest) or (float(ts) > float(latest[uid]["reply_ts"])):
            latest[uid] = r
    return latest

def prev_meeting_next_actions(prev_doc_id: str) -> List[str]:
    txt = doc_text(prev_doc_id)
    by_names = _parse_by_names(txt)
    bullets: List[str] = []
    # Collect all persons' next actions raw lines
    for _, parts in by_names.items():
        for ln in parts.get("next", []) or []:
            if ln:
                bullets.append(ln.strip())
    # Deduplicate while preserving order
    seen = set()
    out = []
    for b in bullets:
        key = b.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    title = os.getenv("MEETING_TITLE_CONTAINS", "").strip()
    meeting = find_meeting_by_title_contains(title, MEETING_KEY) if title else get_latest_meeting(MEETING_KEY)
    if not meeting or not meeting.get("parent_ts"):
        print("[build_agenda_docs_only] No parent thread; ensure retrospective post is done.")
        return
    meeting_id = meeting["meeting_id"]
    date_str = meeting.get("date", "")
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(MEETING_KEY) or ""

    # Current hearing highlights
    latest = latest_hearing_highlights(meeting_id)

    # Previous meeting next actions (raw from Docs)
    prev = get_previous_meeting(MEETING_KEY, date_str)
    prev_actions: List[str] = []
    if prev and prev.get("doc_id"):
        prev_actions = prev_meeting_next_actions(prev["doc_id"])[:10]

    lines: List[str] = []
    lines.append(f"# 合体アジェンダ (Docs原文 x Hearing) {date_str}")
    lines.append("")
    lines.append("## 前回NextAction（再掲）")
    if prev_actions:
        for a in prev_actions:
            lines.append(f"- {a}")
    else:
        lines.append("- なし")

    lines.append("")
    lines.append("## 人別ハイライト（Hearing）")
    if latest:
        for uid, r in latest.items():
            who = f"<@{uid}>" if uid else "Unknown"
            highlight = r.get("reports") or r.get("todo_status") or "(更新なし)"
            # Show first 2 lines
            parts = [ln for ln in (highlight or "").splitlines() if ln.strip()][:2]
            summary = " / ".join(parts) if parts else "(更新なし)"
            lines.append(f"- {who}: {summary}")
    else:
        lines.append("- (未収集)")

    lines.append("")
    lines.append("## ブロッカー/依頼（Hearing）")
    blockers = [ (uid, r.get("blockers","")) for uid, r in latest.items() if r.get("blockers") ] if latest else []
    if blockers:
        for uid, bl in blockers:
            who = f"<@{uid}>" if uid else "Unknown"
            first = bl.splitlines()[0][:120]
            lines.append(f"- {who}: {first}")
    else:
        lines.append("- なし")

    body_md = "\n".join(lines)
    upsert_agenda(meeting_id=meeting_id, channel_id=channel, thread_ts=meeting["parent_ts"], body_md=body_md, posted_ts="")
    print(f"[build_agenda_docs_only] Built agenda without items (chars={len(body_md)})")

if __name__ == "__main__":
    main()

