import os
import re
from typing import List, Dict, Optional
from .google_clients import docs as docs_client
from .sheets_repo import get_latest_meeting, upsert_item, get_slack_id_for_email, save_email_slack_mapping
from .slack_client import SlackClient

MEETING_KEY = os.getenv("MEETING_KEY")

# Accept checkbox tasks, or bullet lines that include an assignee hint/email
TASK_CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[(?: |x|X)?\]\s*(.+)$")
TASK_BULLET_WITH_OWNER_RE = re.compile(r"^\s*[-*]\s*(.+?)(?:\s+(?:担当|assignee)\s*[:：]\s*\S+@\S+|\s+\S+@\S+)\s*$")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
DUE_LABEL_RE = re.compile(r"(?:期限|due)[:：]?\s*(\d{4}-\d{2}-\d{2})")
URL_RE = re.compile(r"(https?://\S+)")
ASSIGNEE_HINT_RE = re.compile(r"(?:担当|assignee)\s*[:：]\s*(\S+@\S+)")
HEADING_HINT_RE = re.compile(r"(?i)\b(todo|to\s*do|next\s*action|次アクション|アクション)\b")

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

def _parse_actions(text: str) -> List[Dict[str, Optional[str]]]:
    actions: List[Dict[str, Optional[str]]] = []
    heading_mode = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # detect action sections to relax parsing for a few lines after headings
        if HEADING_HINT_RE.search(line):
            heading_mode = True
            continue
        m = TASK_CHECKBOX_RE.match(line)
        if not m:
            # if in heading mode, accept bullets as tasks
            if heading_mode and line.startswith(('-', '*', '・')):
                candidate = line.lstrip('-*・').strip()
            else:
                mb = TASK_BULLET_WITH_OWNER_RE.match(line)
                if not mb:
                    # reset heading mode upon unrelated content
                    heading_mode = False
                    continue
                candidate = mb.group(1).strip()
        else:
            candidate = m.group(1).strip()

        email = None
        m2 = ASSIGNEE_HINT_RE.search(raw) or EMAIL_RE.search(raw)
        if m2:
            email = m2.group(1)
        due = None
        m3 = DUE_LABEL_RE.search(raw) or DATE_RE.search(raw)
        if m3:
            due = m3.group(1)
        links = URL_RE.findall(raw)
        if not candidate:
            continue
        # Heuristic: if not checkbox, require either email/assignee hint present to avoid noise
        if not TASK_CHECKBOX_RE.match(raw) and not (email):
            continue
        actions.append({
            "task": candidate,
            "assignee_email": email or "",
            "due": due or "",
            "links": ",".join(links) if links else "",
        })
    return actions

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    meeting = get_latest_meeting(MEETING_KEY)
    if not meeting:
        raise RuntimeError("No meeting found. Run docs_ingest first.")
    meeting_id = meeting["meeting_id"]
    date_str = meeting["date"]
    doc_id = meeting["doc_id"]
    text = _extract_text(doc_id)
    actions = _parse_actions(text)
    slack = SlackClient()
    for a in actions:
        email = a["assignee_email"] or ""
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
            task=a["task"],
            assignee_email=email,
            assignee_slack_id=slack_id,
            due=a["due"],
            links=a["links"],
            status="pending",
        )
    print(f"[action_extract] Extracted {len(actions)} actions from doc {doc_id}")

if __name__ == "__main__":
    main()
