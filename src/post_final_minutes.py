"""
最終議事録の自動投稿

トリガー条件（行ごと）:
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
from .text_split import split_main_and_thread

DEFAULT_CHANNEL_ID = os.getenv("DEFAULT_CHANNEL_ID", "").strip()


def should_post_final(row: dict) -> bool:
    has_text = bool((row.get("final_minutes") or "").strip())
    not_posted = not (row.get("final_minutes_thread_ts") or "").strip()
    return has_text and not_posted


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
        # 本文とスレッドに分割（決定事項の詳細 以下はスレッドへ）。
        main_text, thread_text = split_main_and_thread(text)
        # 万一、親側が空になった場合は従来通り全文を親に投稿（重複回避）
        if not (main_text or "").strip():
            main_text, thread_text = text, ""

        print(f"[post_final_minutes] Posting final minutes for: {title}")
        ts = slack_client.post_message(channel_id, main_text)
        if ts and row.get("_row_number"):
            update_row(sheet_name, row["_row_number"], {
                "final_minutes_thread_ts": ts,
                "updated_at": now_jst_str(),
            })
            print(f"[post_final_minutes] Posted ts={ts} and updated row {row['_row_number']}")

            # 決定事項の詳細 以降があればスレッドに投稿
            try:
                if thread_text:
                    slack_client.post_message(channel_id, thread_text, thread_ts=ts)
                    print("[post_final_minutes] Posted detail section in thread")
            except Exception as e:
                print(f"[post_final_minutes] Failed to post detail thread: {e}")


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


