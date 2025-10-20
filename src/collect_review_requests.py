"""
議事録修正依頼の収集
- 対象: 議事録スレッドの返信のうち、指定メンション/キーワードを含むもの
- 出力: シート列 review_requests01〜04 に時系列で最大4件を書き込み
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
REVIEW_USER_ID = os.getenv("REVIEW_USER_ID", "").strip()  # 例: U0123456789（必須。実メンションのみ対象）


def reply_matches(text: str) -> bool:
    """実メンション <@REVIEW_USER_ID> を含む投稿のみを対象とする。"""
    if not text or not REVIEW_USER_ID:
        return False
    return f"<@{REVIEW_USER_ID}>" in text


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

        # ts昇順に並べ、先頭から最大4件を各列へ格納
        try:
            matches.sort(key=lambda m: float(m.get("ts", "0")))
        except Exception:
            pass
        texts = [m["text"] for m in matches][:4]
        # 4つに揃える
        while len(texts) < 4:
            texts.append("")

        row_number = row.get("_row_number")
        if row_number:
            update_row(sheet_name, row_number, {
                "review_requests01": texts[0],
                "review_requests02": texts[1],
                "review_requests03": texts[2],
                "review_requests04": texts[3],
                "updated_at": now_jst_str(),
            })
            print(f"[collect_review_requests] Saved {min(4, len(matches))} requests to row {row_number}")


def main():
    # 収集と完成版投稿はレビュー用ボットで実行
    slack_client = SlackClient(token=os.getenv("SLACK_BOT_TOKEN_REVIEW", "").strip() or None)
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


