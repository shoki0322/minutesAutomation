import os
import hashlib
from typing import Dict, List, Tuple

from .sheets_repo import (
    get_latest_meeting,
    find_meeting_by_title_contains,
    get_previous_meeting,
    read_rows,
    upsert_agenda,
    get_channel_for_meeting_key,
)
from .doc_section_extract import _extract_text as doc_text, _parse_by_names
from .llm import GeminiClient


def summarize_hearing(meeting_id: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    rows = read_rows("hearing_responses")
    latest_by_user: Dict[str, Dict] = {}
    for r in rows:
        if r.get("meeting_id") != meeting_id:
            continue
        uid = r.get("assignee_slack_id") or ""
        ts = r.get("reply_ts") or "0"
        if (uid not in latest_by_user) or (float(ts) > float(latest_by_user[uid]["reply_ts"])):
            latest_by_user[uid] = r
    highlights: List[str] = []
    blockers: List[Tuple[str, str]] = []
    for uid, r in latest_by_user.items():
        who = f"<@{uid}>" if uid else "Unknown"
        # Prefer reports, fallback to todo_status
        hl_src = r.get("reports") or r.get("todo_status") or ""
        first_lines = [ln for ln in (hl_src or "").splitlines() if ln.strip()][:2]
        summary = " / ".join(first_lines) if first_lines else "(更新なし)"
        highlights.append(f"- {who}: {summary}")
        if r.get("blockers"):
            bl_first = r["blockers"].splitlines()[0][:120]
            blockers.append((who, bl_first))
    return highlights, blockers


def extract_prev_next_actions(prev_doc_id: str) -> List[str]:
    txt = doc_text(prev_doc_id)
    by = _parse_by_names(txt)
    bullets: List[str] = []
    for _, parts in by.items():
        for ln in parts.get("next", []) or []:
            if ln:
                bullets.append(ln.strip())
    seen, out = set(), []
    for b in bullets:
        k = b.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(b)
    return out


def build_prompt(meeting_title: str, date_str: str, prev_next: List[str], hearing_highlights: List[str], hearing_blockers: List[Tuple[str, str]]) -> str:
    prev_section = "\n".join(f"- {b}" for b in prev_next) if prev_next else "- なし"
    hl_section = "\n".join(hearing_highlights) if hearing_highlights else "- (未収集)"
    bl_section = "\n".join(f"- {who}: {line}" for who, line in hearing_blockers) if hearing_blockers else "- なし"
    return f"""
会議名: {meeting_title}
対象日: {date_str}

あなたは議事進行のための編集者です。以下の入力をもとに、意思決定が速くなる1枚のMarkdownアジェンダを作成してください。

要件:
- 前回NextActionを冒頭に再掲（重複や表記ゆれは自然に統合）。
- 今回のHearing（人別ハイライト）は1–2行で簡潔に。
- ブロッカー/依頼は別章で明確化。
- 最後に今週のTop3（理由も一言: 期限の近さ/ブロッカー有無/件数など）。
- 箇条書きは短く、冗長表現は避ける。見出しは日本語で。

入力1: 前回NextAction（再掲素材）
{prev_section}

入力2: 今回Hearing（人別ハイライト）
{hl_section}

入力3: 今回ブロッカー/依頼
{bl_section}

出力仕様（Markdownのみ）:
- 見出し順: 「前回NextAction（再掲）」→「人別ハイライト」→「ブロッカー/依頼」→「今週Top3」
- 箇条書きは1行80文字程度、重複は統合。
- 具体的かつ簡潔に。
""".strip()


def input_hash(prev_next: List[str], hearing_highlights: List[str], hearing_blockers: List[Tuple[str, str]]) -> str:
    h = hashlib.sha1()
    for s in prev_next:
        h.update(s.strip().lower().encode("utf-8"))
    for s in hearing_highlights:
        h.update(s.strip().lower().encode("utf-8"))
    for who, line in hearing_blockers:
        h.update((who + "|" + line).strip().lower().encode("utf-8"))
    return h.hexdigest()[:16]


def main():
    meeting_key = os.getenv("MEETING_KEY")
    if not meeting_key:
        raise RuntimeError("MEETING_KEY required.")
    title_contains = os.getenv("MEETING_TITLE_CONTAINS", "").strip()
    meeting = find_meeting_by_title_contains(title_contains, meeting_key) if title_contains else get_latest_meeting(meeting_key)
    if not meeting or not meeting.get("parent_ts"):
        print("[build_agenda_llm] No parent thread; ensure retrospective was posted.")
        return

    meeting_id = meeting["meeting_id"]
    date_str = meeting.get("date", "")
    title = meeting.get("title", meeting_key)
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(meeting_key) or ""

    # Collect inputs
    prev = get_previous_meeting(meeting_key, date_str)
    prev_next = extract_prev_next_actions(prev["doc_id"]) if prev and prev.get("doc_id") else []
    highlights, blockers = summarize_hearing(meeting_id)

    # Idempotency: skip if same input produced an agenda already
    ih = input_hash(prev_next, highlights, blockers)

    prompt = build_prompt(title, date_str, prev_next, highlights, blockers)
    system = "あなたは日本語で簡潔な議事アジェンダを作る編集者です。フォーマットはMarkdownのみ。"
    client = GeminiClient()
    md = client.generate_markdown(prompt, system=system)
    if not md:
        print("[build_agenda_llm] Empty output; aborting.")
        return

    # Save agenda body
    # Prepend a clear H1 title if missing
    title_h1 = f"# アジェンダ — {title} ({date_str})\n\n"
    body_md = md
    if not body_md.lstrip().startswith("# "):
        body_md = title_h1 + body_md
    # Embed input hash as invisible hint (HTML comment) to help idempotency checks downstream if needed
    if "<!-- input_hash:" not in body_md:
        body_md += f"\n\n<!-- input_hash:{ih} -->\n"
    upsert_agenda(meeting_id=meeting_id, channel_id=channel, thread_ts=meeting["parent_ts"], body_md=body_md, posted_ts="")
    print(f"[build_agenda_llm] Built agenda via LLM (chars={len(body_md)})")

    # Optional: --post to immediately post
    import sys
    if any(arg in ("--post", "-p") for arg in sys.argv[1:]):
        from .post_agenda import main as post
        post()


if __name__ == "__main__":
    main()
