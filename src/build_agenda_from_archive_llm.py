import os
from typing import Dict, List, Tuple, Optional

from .sheets_repo import (
    get_latest_meeting,
    find_meeting_by_title_contains,
    read_rows,
    upsert_agenda,
    get_channel_for_meeting_key,
    get_previous_meeting,
)
from .llm import GeminiClient


def current_meeting() -> Optional[Dict[str, str]]:
    mk = os.getenv("MEETING_KEY")
    title = os.getenv("MEETING_TITLE_CONTAINS", "").strip()
    if title:
        return find_meeting_by_title_contains(title, mk)
    return get_latest_meeting(mk)


def get_archive_body(meeting_id: str) -> str:
    rows = read_rows("archives")
    for r in rows:
        if r.get("meeting_id") == meeting_id:
            return r.get("body_text", "")
    return ""


def latest_hearing(meeting_id: str) -> Tuple[List[str], List[Tuple[str, str]]]:
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
        hl_src = r.get("reports") or r.get("todo_status") or ""
        first_lines = [ln for ln in (hl_src or "").splitlines() if ln.strip()][:2]
        summary = " / ".join(first_lines) if first_lines else "(更新なし)"
        highlights.append(f"- {who}: {summary}")
        if r.get("blockers"):
            first = r["blockers"].splitlines()[0][:120]
            blockers.append((who, first))
    return highlights, blockers


def build_prompt(meeting_title: str, date_str: str, archive_text: str, hearing_highlights: List[str], hearing_blockers: List[Tuple[str, str]], label_archive: str = "議事録全文") -> str:
    hl_section = "\n".join(hearing_highlights) if hearing_highlights else "- (未収集)"
    bl_section = "\n".join(f"- {who}: {line}" for who, line in hearing_blockers) if hearing_blockers else "- なし"
    # Truncate archive if extremely long to control token usage
    max_chars = int(os.getenv("ARCHIVE_MAX_CHARS", "12000"))
    arch = archive_text[:max_chars]
    return f"""
会議名: {meeting_title}
基準日: {date_str}

以下の素材から「次回の会議で使う」読みやすい1枚アジェンダ(Markdown)を作ってください。

素材A: {label_archive}（必要箇所のみ要約し、次回に必要な論点/宿題を抽出）
-----
{arch}
-----

素材B: 今回Hearingの人別ハイライト（要約済み）
{hl_section}

素材C: 今回のブロッカー/依頼
{bl_section}

要件:
- 見出し: 「次回のサマリ / 前回からの持ち越し / 人別ハイライト / ブロッカー/依頼 / 次回の決定が必要な事項 / 次回Top3フォーカス / 準備物・宿題」
- Archiveは重複・冗長を統合し、次回に必要な論点に絞る。
- 人別ハイライトは1–2行/人で簡潔に再掲してよい。
- 「次回の決定が必要な事項」は質問形式や選択肢形式も可。
- 「準備物・宿題」は担当や期日を括弧で簡潔に（例: (担当: @U..., 期限: YYYY-MM-DD)）。
- 出力はMarkdownのみ（日本語）。
""".strip()


def main():
    mtg = current_meeting()
    if not mtg or not mtg.get("meeting_id"):
        raise SystemExit("No current meeting found")
    meeting_id = mtg["meeting_id"]
    title = mtg.get("title") or mtg.get("meeting_key") or "Agenda"
    date_str = mtg.get("date", "")
    channel = mtg.get("channel_id") or get_channel_for_meeting_key(mtg.get("meeting_key", "")) or ""

    # Choose archive source: current or previous (env USE_PREV_ARCHIVE=1 or flag --prev)
    use_prev = os.getenv("USE_PREV_ARCHIVE", "").strip().lower() in {"1", "true", "yes"}
    import sys
    if any(arg in ("--prev", "-P") for arg in sys.argv[1:]):
        use_prev = True

    if use_prev:
        prev = get_previous_meeting(mtg.get("meeting_key", ""), date_str)
        if prev:
            archive = get_archive_body(prev.get("meeting_id", ""))
            label_archive = "前回議事録全文"
        else:
            archive = get_archive_body(meeting_id)
            label_archive = "今回議事録全文"
            print("[build_agenda_from_archive_llm] No previous meeting; using current archive.")
    else:
        archive = get_archive_body(meeting_id)
        label_archive = "今回議事録全文"
    hl, bl = latest_hearing(meeting_id)

    prompt = build_prompt(title, date_str, archive, hl, bl, label_archive=label_archive)
    system = "あなたは日本語で簡潔な議事アジェンダを作る編集者です。フォーマットはMarkdownのみ。"

    client = GeminiClient()
    md = client.generate_markdown(prompt, system=system)
    if not md:
        print("[build_agenda_from_archive_llm] Empty output; aborting.")
        return

    # Ensure H1 title present, use "次回アジェンダ" 表記
    next_date = os.getenv("NEXT_MEETING_DATE", "").strip()
    h1 = f"# 次回アジェンダ — {title} ({next_date or date_str})\n\n"
    if not md.lstrip().startswith("# "):
        md = h1 + md

    upsert_agenda(meeting_id=meeting_id, channel_id=channel, thread_ts=mtg.get("parent_ts", ""), body_md=md, posted_ts="")
    print(f"[build_agenda_from_archive_llm] Built agenda from archive+hearing (chars={len(md)})")

    import sys
    if any(arg in ("--post", "-p") for arg in sys.argv[1:]):
        from .post_agenda import main as post
        post()


if __name__ == "__main__":
    main()
