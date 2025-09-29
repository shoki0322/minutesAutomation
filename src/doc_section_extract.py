import os
import re
import time
from typing import List, Dict, Optional
from datetime import datetime
from .google_clients import docs as docs_client
from .sheets_repo import (
    get_latest_meeting,
    upsert_item,
    upsert_hearing_response,
    get_slack_id_for_email,
    save_email_slack_mapping,
    resolve_contact_by_name,
    find_meeting_by_title_contains,
)
from .slack_client import SlackClient

MEETING_KEY = os.getenv("MEETING_KEY")

EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
DUE_LABEL_RE = re.compile(r"(?:期限|due)[:：]?\s*(\d{4}-\d{2}-\d{2})")
ASSIGNEE_HINT_RE = re.compile(r"(?:担当|assignee)\s*[:：]\s*(\S+@\S+)")
URL_RE = re.compile(r"(https?://\S+)")

SECTION_NEXT_RE = re.compile(r"(?i)(^|\s)(次アクション|next\s*action|action|todo)(\s|$)")
SECTION_RETRO_RE = re.compile(r"(?i)(^|\s)(振り返り|retrospective|まとめ)(\s|$)")
NAME_HEADING_RE = re.compile(r"^[A-Za-z一-龥ぁ-んァ-ヶー・\s]{2,40}$")


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
    return walk(document.get("body", {}).get("content", []))


def _split_sections(text: str) -> Dict[str, List[str]]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    current = None
    buckets: Dict[str, List[str]] = {"next": [], "retro": []}
    for ln in lines:
        clean = ln.strip()
        if not clean:
            # keep blank as separator but do not push
            continue
        if SECTION_NEXT_RE.search(clean):
            current = "next"; continue
        if SECTION_RETRO_RE.search(clean):
            current = "retro"; continue
        if current:
            # capture only list-like lines or checkboxes to avoid pulling the whole doc
            # accept list-like lines; otherwise accept any non-empty as a task/retro line
            if clean.startswith(('-', '*', '・')) or clean.startswith('[ ]') or clean.startswith('- ['):
                buckets[current].append(clean)
            else:
                buckets[current].append(clean)
    return buckets


def _parse_tasks(lines: List[str]) -> List[Dict[str, Optional[str]]]:
    tasks: List[Dict[str, Optional[str]]] = []
    for raw in lines:
        line = raw.strip()
        # remove checkbox markup
        line = re.sub(r"^[-*・]\s*\[(?: |x|X)?\]\s*", "", line)
        candidate = re.sub(r"^[-*・]\s*", "", line).strip()
        if not candidate:
            continue
        email = None
        m2 = ASSIGNEE_HINT_RE.search(raw) or EMAIL_RE.search(raw)
        if m2:
            email = m2.group(1)
        due = None
        m3 = DUE_LABEL_RE.search(raw) or DATE_RE.search(raw)
        if m3:
            due = m3.group(1)
        links = URL_RE.findall(raw)
        tasks.append({
            "task": candidate,
            "assignee_email": (email or "").lower(),
            "due": due or "",
            "links": ",".join(links) if links else "",
        })
    return tasks


def _parse_retro(lines: List[str]) -> Dict[str, str]:
    by_email: Dict[str, List[str]] = {}
    for raw in lines:
        email = None
        m = EMAIL_RE.search(raw)
        if m:
            email = m.group(1).lower()
        content = re.sub(EMAIL_RE, "", raw)
        content = re.sub(r"^[-*・]\s*", "", content).strip()
        if not content:
            continue
        key = email or ""
        by_email.setdefault(key, []).append(content)
    return {k: " ".join(v)[:500] for k, v in by_email.items()}

def _parse_by_names(text: str) -> Dict[str, Dict[str, List[str]]]:
    """Return {name: {retro: [...], next: [...]}} capturing lines under person headings."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    current_name: Optional[str] = None
    current_section: Optional[str] = None
    out: Dict[str, Dict[str, List[str]]] = {}
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if NAME_HEADING_RE.match(s) and not SECTION_NEXT_RE.search(s) and not SECTION_RETRO_RE.search(s):
            current_name = s
            out.setdefault(current_name, {"retro": [], "next": []})
            current_section = None
            continue
        if SECTION_RETRO_RE.search(s):
            current_section = "retro"; continue
        if SECTION_NEXT_RE.search(s):
            current_section = "next"; continue
        if current_name and current_section:
            out[current_name][current_section].append(s)
    return out


def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    title_contains = os.getenv("MEETING_TITLE_CONTAINS", "").strip()
    meeting = None
    if title_contains:
        meeting = find_meeting_by_title_contains(title_contains, MEETING_KEY)
    if not meeting:
        meeting = get_latest_meeting(MEETING_KEY)
    if not meeting:
        raise RuntimeError("No meeting found. Run docs_ingest first.")
    meeting_id = meeting["meeting_id"]
    date_str = meeting["date"]
    doc_id = meeting["doc_id"]

    text = _extract_text(doc_id)
    # First, try name-structured parsing
    by_names = _parse_by_names(text)
    next_tasks: List[Dict[str, Optional[str]]] = []
    retro_map: Dict[str, str] = {}
    if by_names:
        for name, parts in by_names.items():
            # resolve contact
            email_guess, slack_guess = resolve_contact_by_name(name)
            # retro
            retro_text = " ".join(parts.get("retro", []))[:500].strip()
            if retro_text:
                key = (email_guess or name).lower()
                retro_map[key] = retro_text
            # next actions
            nxt = _parse_tasks(parts.get("next", []))
            # fill missing assignee with name-resolved email if absent
            for t in nxt:
                if not t.get("assignee_email") and email_guess:
                    t["assignee_email"] = email_guess
            next_tasks.extend(nxt)
    else:
        # fallback to section-only parsing
        buckets = _split_sections(text)
        next_tasks = _parse_tasks(buckets.get("next", []))
        retro_map = _parse_retro(buckets.get("retro", []))

    slack = SlackClient()

    # Upsert tasks (items)
    for t in next_tasks:
        email = t["assignee_email"] or ""
        slack_id = ""
        if email:
            sid = get_slack_id_for_email(email)
            if not sid:
                sid = slack.lookup_user_id_by_email(email)
                if sid:
                    save_email_slack_mapping(email, sid, "")
            slack_id = sid or ""
        upsert_item(
            date_str=date_str,
            meeting_id=meeting_id,
            task=t["task"] or "",
            assignee_email=email,
            assignee_slack_id=slack_id,
            due=t["due"] or "",
            links=t["links"] or "",
            status="pending",
        )

    # Upsert retrospectives into hearing_responses as 'reports'
    ts = str(time.time())
    for email, report in retro_map.items():
        slack_id = ""
        if email:
            sid = get_slack_id_for_email(email)
            if not sid:
                sid = slack.lookup_user_id_by_email(email)
                if sid:
                    save_email_slack_mapping(email, sid, "")
            slack_id = sid or ""
        upsert_hearing_response(
            meeting_id=meeting_id,
            assignee_slack_id=slack_id,
            reply_ts=ts,
            todo_status="",
            reports=report,
            blockers="",
            links="",
            raw_text=report,
        )

    print(f"[doc_section_extract] tasks={len(next_tasks)} retro_users={len(retro_map)}")

if __name__ == "__main__":
    main()
