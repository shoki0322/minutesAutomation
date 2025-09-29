from typing import Dict
import re
from .sheets_repo import latest_parent_thread, upsert_hearing_response, get_latest_meeting, get_channel_for_meeting_key
from .slack_client import SlackClient

FULLWIDTH = str.maketrans({
    "１": "1", "２": "2", "３": "3", "４": "4",
    "：": ":", "（": "(", "）": ")",
})

# Expanded label patterns (numbers, Japanese labels, and synonyms)
LABEL_MAP = {
    re.compile(r"(?i)^\s*((?:1|１)[\.).]|todo|to\s*do|前回\s*todo|todo状況|前回.*状況|やったこと|進捗|完了|done|実績)\b"): 1,
    re.compile(r"(?i)^\s*((?:2|２)[\.).]|report|reports|今回.*報告|報告|アップデート|更新|今週の報告|今週やったこと)\b"): 2,
    re.compile(r"(?i)^\s*((?:3|３)[\.).]|blocker|blockers|ブロッカー|課題|懸念|困っていること|依頼|ボトルネック|help)\b"): 3,
    re.compile(r"(?i)^\s*((?:4|４)[\.).]|link|links|リンク|url|refs|参考|共有資料)\b"): 4,
}

def _parse_four_fields(text: str) -> Dict[str, str]:
    # Robust mapping for numbering or label headings
    buckets = {1: [], 2: [], 3: [], 4: []}
    current = None
    for raw in text.splitlines():
        # Normalize fullwidth digits and punctuation, strip slack artifacts
        line = raw.translate(FULLWIDTH).strip()
        if not line:
            continue
        switched = False
        for rx, idx in LABEL_MAP.items():
            if rx.search(line):
                current = idx
                # trim the matched label prefix
                line = rx.sub("", line).strip(" ：:.-")
                if line:
                    buckets[current].append(line)
                switched = True
                break
        if not switched:
            if current:
                buckets[current].append(line)
    return {
        "todo_status": "\n".join(buckets[1]).strip(),
        "reports": "\n".join(buckets[2]).strip(),
        "blockers": "\n".join(buckets[3]).strip(),
        "links": "\n".join(buckets[4]).strip(),
        "raw_text": text.strip(),
    }

def main():
    thread = latest_parent_thread()
    if not thread:
        print("[collect_replies] No parent thread found.")
        return
    meeting_id, parent_ts = thread
    meeting = get_latest_meeting() or {}
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(meeting.get("meeting_key", ""))
    if not channel:
        print("[collect_replies] No channel configured; skipping.")
        return
    slack = SlackClient()
    msgs = slack.fetch_thread_replies(channel, parent_ts)
    # index latest per user
    latest_per_user: Dict[str, Dict] = {}
    for m in msgs:
        user = m.get("user")
        ts = m.get("ts")
        text = m.get("text", "")
        if not user or not text or ts == parent_ts:
            continue
        if (user not in latest_per_user) or (float(ts) > float(latest_per_user[user]["ts"])):
            latest_per_user[user] = {"ts": ts, "text": text}
    for user, data in latest_per_user.items():
        fields = _parse_four_fields(data["text"])
        upsert_hearing_response(
            meeting_id=meeting_id,
            assignee_slack_id=user,
            reply_ts=data["ts"],
            todo_status=fields["todo_status"],
            reports=fields["reports"],
            blockers=fields["blockers"],
            links=fields["links"],
            raw_text=fields["raw_text"],
        )
    print(f"[collect_replies] Collected replies from {len(latest_per_user)} users")

if __name__ == "__main__":
    main()
