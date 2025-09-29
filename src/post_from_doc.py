import os
import re
from typing import Dict, List, Optional
from .sheets_repo import (
    get_latest_meeting,
    get_channel_for_meeting_key,
    set_meeting_parent_ts,
    resolve_contact_by_name,
    find_meeting_by_title_contains,
)
from .slack_client import SlackClient
from .google_clients import docs as docs_client

MEETING_KEY = os.getenv("MEETING_KEY")

SECTION_NEXT_RE = re.compile(r"(?i)(^|\s)(次アクション|next\s*action|action|todo)(\s|$)")
SECTION_RETRO_RE = re.compile(r"(?i)(^|\s)(振り返り|retrospective|まとめ)(\s|$)")
# Person heading must have at least one space (first last) to avoid matching generic headings
NAME_HEADING_RE = re.compile(r"^(?=.{3,50}$)(?=.*\s)[A-Za-z一-龥ぁ-んァ-ヶー\s・]+$")
GENERIC_HEADINGS = {"招待済み", "添付ファイル", "会議の録画", "詳細", "まとめ"}
STOP_HEADINGS = {"推奨される次のステップ", "Recommended next steps"}

def _extract_text(doc_id: str) -> str:
    document = docs_client().documents().get(documentId=doc_id).execute()
    def walk(elements):
        text = ""
        for e in elements:
            if "paragraph" in e:
                for el in e["paragraph"].get("elements", []):
                    text += el.get("textRun", {}).get("content", "")
            if "table" in e:
                for row in e["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        text += walk(cell.get("content", []))
            if "tableOfContents" in e:
                text += walk(e["tableOfContents"].get("content", []))
        return text
    raw = walk(document.get("body", {}).get("content", []))
    # Normalize: remove private-use and control glyphs seen in pasted Docs
    raw = raw.replace("\u000b", "\n")  # vertical tab -> newline
    # strip private-use glyphs often appearing from pasted Docs content
    raw = re.sub(r"[\ue000-\uf8ff]", "", raw)
    # Collapse Windows-style newlines and stray spaces
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = "\n".join(ln.rstrip() for ln in raw.splitlines())
    return raw

def _parse_by_names(text: str) -> Dict[str, Dict[str, List[str]]]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    current_name: Optional[str] = None
    current_section: Optional[str] = None
    out: Dict[str, Dict[str, List[str]]] = {}
    stopped = False
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s in STOP_HEADINGS:
            stopped = True
            break
        if (
            NAME_HEADING_RE.match(s)
            and s not in GENERIC_HEADINGS
            and not SECTION_NEXT_RE.search(s)
            and not SECTION_RETRO_RE.search(s)
        ):
            current_name = s
            out.setdefault(current_name, {"retro": [], "next": []})
            current_section = None
            continue
        # exact headings like "振り返り" / "Next Action" are common
        if s in ("振り返り",) or SECTION_RETRO_RE.search(s):
            current_section = "retro"; continue
        if SECTION_NEXT_RE.search(s) or s in ("Next Action", "NextAction", "次アクション"):
            current_section = "next"; continue
        if current_name and current_section:
            # ignore purely decorative bullets
            line = s.strip("-•・ ")
            if line:
                out[current_name][current_section].append(line)
    return out

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    # Prefer title-based match if provided
    title_contains = os.getenv("MEETING_TITLE_CONTAINS", "").strip()
    meeting = None
    if title_contains:
        meeting = find_meeting_by_title_contains(title_contains, MEETING_KEY)
    if not meeting:
        meeting = get_latest_meeting(MEETING_KEY)
    if not meeting:
        raise RuntimeError("No meeting found. Run docs_ingest first.")
    meeting_id = meeting["meeting_id"]
    doc_id = meeting["doc_id"]
    channel = meeting.get("channel_id") or get_channel_for_meeting_key(MEETING_KEY)
    if not channel:
        print("[post_from_doc] No channel configured; skipping Slack post.")
        return
    text = _extract_text(doc_id)
    by_names = _parse_by_names(text)
    if not by_names:
        print("[post_from_doc] No person-structured sections detected; nothing to post.")
        return

    lines: List[str] = []
    lines.append("[weekly] AI基盤MTG")
    for name, parts in by_names.items():
        email_guess, sid_guess = resolve_contact_by_name(name)
        mention = f"<@{sid_guess}>" if sid_guess else (name)
        retro = [ln.strip() for ln in parts.get("retro", []) if ln.strip()]
        nxt = [ln.strip() for ln in parts.get("next", []) if ln.strip()]
        # One block per person
        lines.append(f"- {mention}")
        if retro:
            lines.append(f"  - 振り返り:")
            for r in retro:
                lines.append(f"    - {r}")
        if nxt:
            lines.append("  - NextAction:")
            for t in nxt:
                lines.append(f"    - {t}")

    body = "\n".join(lines)
    slack = SlackClient()
    # Support new top-level post via env FORCE_NEW_THREAD=1
    force_new = os.getenv("FORCE_NEW_THREAD", "").strip().lower() in {"1","true","yes"}
    thread_ts = None if force_new else (meeting.get("parent_ts") or None)
    ts = slack.post_message(channel=channel, text=body, thread_ts=thread_ts)
    # Only set parent_ts if we posted as a new parent implicitly (no prior parent) and not forcing a new separate post
    if ts and (not meeting.get("parent_ts")) and (not force_new):
        set_meeting_parent_ts(meeting_id, ts)

if __name__ == "__main__":
    main()
