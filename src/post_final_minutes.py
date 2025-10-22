"""
最終議事録の自動投稿

トリガー条件（行ごと）:
- remarks に「✅ レビュー反映済み」を含む
- final_minutes が非空
- final_minutes_thread_ts が未設定（未投稿）

動作:
- SLACK_BOT_TOKEN_REVIEW を用いてチャンネルにトップ投稿
- 成功時、final_minutes_thread_ts と updated_at を保存
"""
import os
from .slack_client import SlackClient
from .minutes_repo import (
    get_all_sheet_names,
    read_sheet_rows,
    update_row,
    now_jst_str,
)

DEFAULT_CHANNEL_ID = os.getenv("DEFAULT_CHANNEL_ID", "").strip()


def should_post_final(row: dict) -> bool:
    remarks = (row.get("remarks") or "").strip()
    has_flag = "✅ レビュー反映済み" in remarks
    has_text = bool((row.get("final_minutes") or "").strip())
    not_posted = not (row.get("final_minutes_thread_ts") or "").strip()
    return has_flag and has_text and not_posted


def post_for_sheet(sheet_name: str, slack_client: SlackClient):
    print(f"[post_final_minutes] Checking sheet: {sheet_name}")
    rows = read_sheet_rows(sheet_name)

    for row in rows:
        if not should_post_final(row):
            continue

        channel_id = (row.get("channel_id") or DEFAULT_CHANNEL_ID).strip()
        if not channel_id:
            print(f"[post_final_minutes] No channel_id for: {row.get('title')}")
            continue

        text = (row.get("final_minutes") or "").strip()
        if not text:
            continue

        title = row.get("title", "無題")
        print(f"[post_final_minutes] Posting final minutes for: {title}")
        ts = slack_client.post_message(channel_id, text)
        if ts and row.get("_row_number"):
            update_row(sheet_name, row["_row_number"], {
                "final_minutes_thread_ts": ts,
                "updated_at": now_jst_str(),
            })
            print(f"[post_final_minutes] Posted ts={ts} and updated row {row['_row_number']}")


def main():
    slack_client = SlackClient(token=os.getenv("SLACK_BOT_TOKEN_REVIEW", "").strip() or None)
    for sheet_name in get_all_sheet_names():
        if sheet_name.lower() in [
            "mappings", "meetings", "items", "agendas", "archives", "hearing_prompts", "hearing_responses"
        ]:
            continue
        try:
            post_for_sheet(sheet_name, slack_client)
        except Exception as e:
            print(f"[post_final_minutes] Error processing sheet {sheet_name}: {e}")
            continue


if __name__ == "__main__":
    main()


