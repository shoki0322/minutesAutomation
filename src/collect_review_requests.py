"""
議事録修正依頼の収集
- 対象: 議事録スレッドの返信のうち、指定メンション/キーワードを含むもの全件
- 出力: シートに新規列 review_requests に JSON 文字列で保存（将来のGAS統合を想定）
"""
import os
import json
from typing import List, Dict
from .slack_client import SlackClient
from .minutes_repo import (
    get_all_sheet_names,
    read_sheet_rows,
    update_row,
    now_jst_str,
)

DEFAULT_CHANNEL_ID = os.getenv("DEFAULT_CHANNEL_ID", "").strip()
REVIEW_USER_ID = os.getenv("REVIEW_USER_ID", "").strip()  # 例: U0123456789
REVIEW_TRIGGER_KEYWORDS = [k.strip() for k in os.getenv("REVIEW_TRIGGER_KEYWORDS", "DR.ベガパンク").split(",") if k.strip()]


def reply_matches(text: str) -> bool:
    if not text:
        return False
    # メンション（<@UXXXX>）
    if REVIEW_USER_ID and f"<@{REVIEW_USER_ID}>" in text:
        return True
    # 日本語名キーワード
    for kw in REVIEW_TRIGGER_KEYWORDS:
        if kw and kw in text:
            return True
    return False


def collect_for_sheet(sheet_name: str, slack_client: SlackClient):
    print(f"[collect_review_requests] Checking sheet: {sheet_name}")
    rows = read_sheet_rows(sheet_name)

    for row in rows:
        channel_id = row.get("channel_id", "").strip() or DEFAULT_CHANNEL_ID
        thread_ts = row.get("minutes_thread_ts", "").strip()
        if not channel_id or not thread_ts:
            continue

        replies = slack_client.fetch_thread_replies(channel_id, thread_ts)
        if not replies:
            continue

        # 親とボット案内を除外しつつ、トリガーを含むものを抽出
        matches: List[Dict[str, str]] = []
        for r in replies:
            ts = r.get("ts"); text = r.get("text", ""); user = r.get("user") or r.get("bot_id")
            if ts == thread_ts:
                continue
            if reply_matches(text):
                matches.append({"ts": ts, "user": user, "text": text})

        if not matches:
            continue

        # JSONにして review_requests 列へ格納（将来GASでマージするための原本）
        row_number = row.get("_row_number")
        if row_number:
            update_row(sheet_name, row_number, {
                "review_requests": json.dumps(matches, ensure_ascii=False),
                "updated_at": now_jst_str(),
            })
            print(f"[collect_review_requests] Saved {len(matches)} requests to row {row_number}")


def main():
    slack_client = SlackClient()
    for sheet_name in get_all_sheet_names():
        if sheet_name.lower() in [
            "mappings", "meetings", "items", "agendas", "archives", "hearing_prompts", "hearing_responses"
        ]:
            continue
        try:
            collect_for_sheet(sheet_name, slack_client)
        except Exception as e:
            print(f"[collect_review_requests] Error on {sheet_name}: {e}")
            continue


if __name__ == "__main__":
    main()


