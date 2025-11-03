"""
ヒアリング依頼リマインダー
next_meeting_dateの2日前09:00（JST）にSlackへヒアリング依頼を投稿
"""
import os
from datetime import datetime, timedelta
from .slack_client import SlackClient
from .minutes_repo import (
    get_all_sheet_names,
    read_sheet_rows,
    update_row,
    now_jst,
    now_jst_str,
)

DEFAULT_CHANNEL_ID = os.getenv("DEFAULT_CHANNEL_ID", "").strip()


def should_send_hearing_reminder(next_meeting_date_str: str) -> bool:
    """
    ヒアリング依頼を送信すべきかどうか判定
    next_meeting_dateの2日前09:00に実行される想定
    現在時刻が2日前の09:00~10:00の範囲内ならTrue
    """
    if not next_meeting_date_str:
        return False
    
    try:
        # next_meeting_dateをパース
        meeting_date = datetime.strptime(next_meeting_date_str, "%Y-%m-%d")
        
        # 2日前
        target_date = meeting_date - timedelta(days=2)
        
        # 現在のJST時刻
        now = now_jst()
        
        # 同じ日付で、09:00以降
        # GitHub Actionsは毎時00分実行なので、09:00以降ならOK
        # hearing_thread_tsで重複防止されているので何度実行しても安全
        if now.date() == target_date.date() and now.hour >= 9:
            return True
        
        return False
    
    except Exception as e:
        print(f"[send_hearing_reminder] Error parsing date {next_meeting_date_str}: {e}")
        return False


def create_hearing_message(next_meeting_date: str, participants: list = None, previous_responses: list = None, mentions: str = "") -> str:
    """ヒアリング依頼メッセージを生成（メンション対応）"""
    header_parts = []
    if mentions:
        header_parts.append(mentions)
    header_parts.append(f"*次回会議のヒアリング項目*")
    header = "\n\n".join(header_parts)

    template_body = (
        "\n\n"
        "*1. 担当者名：*\n"
        "*2. 今回報告するタスク* \n"
        "・タスク①：\n"
        "--ステータス：完了／進行中／未着手／保留\n"
        "--期限：\n"
        "--進捗内容：\n"
        "--課題・懸念点：\n"
        "タスク②：\n"
        "--ステータス：完了／進行中／未着手／保留\n"
        "--期限：\n"
        "--進捗内容：\n"
        "--課題・懸念点：\n"
        "*3. 新しく議題として取り上げたい内容(複数可)：*\n"
        "・ \n\n"
        "このスレッドで回答してください 👇\n\n"
        "*翌日9:00までに本スレッドで返信ください。返信がない場合は次回アジェンダに追加されません。*"
    )

    return header + template_body
    


def send_hearing_for_sheet(sheet_name: str, slack_client: SlackClient):
    """1つのシートに対してヒアリング依頼送信チェック"""
    print(f"[send_hearing_reminder] Checking sheet: {sheet_name}")
    
    rows = read_sheet_rows(sheet_name)
    
    for row in rows:
        next_meeting_date = row.get("next_meeting_date", "").strip()
        hearing_thread_ts = row.get("hearing_thread_ts", "").strip()
        minutes_thread_ts = row.get("minutes_thread_ts", "").strip()
        final_minutes_thread_ts = row.get("final_minutes_thread_ts", "").strip()
        row_date = row.get("date", "").strip()
        today_str = now_jst().strftime("%Y-%m-%d")
        
        # 既に送信済み（hearing_thread_tsが存在）ならスキップ
        # ※同じ会議に対して複数回送らないための制御
        # 運用に応じて、毎回新しいスレッドを作る場合はこのチェックを調整
        if hearing_thread_ts:
            continue
        
        # 同日連投防止: 議事録を投稿した当日にはヒアリングを送らない
        if row_date == today_str:
            print(f"[send_hearing_reminder] Skip (same-day as meeting): {row.get('title')}")
            continue

        # 送信すべきか判定
        if not should_send_hearing_reminder(next_meeting_date):
            continue
        
        # チャンネルID取得
        channel_id = row.get("channel_id", "").strip() or DEFAULT_CHANNEL_ID
        if not channel_id:
            print(f"[send_hearing_reminder] No channel_id for: {row.get('title')}")
            continue
        
        # 投稿先スレッドの決定ロジック
        # - final_minutes_thread_ts が存在し、かつ返信がある場合は final を優先
        # - final に返信が無い（= 親のみ）場合は minutes_thread_ts を優先（修正なしとみなす）
        # - どちらも無ければスキップ
        target_thread_ts = None
        if final_minutes_thread_ts:
            try:
                replies = slack_client.fetch_thread_replies(channel_id, final_minutes_thread_ts)
                # Slack APIは親メッセージも含む返却のため、2件以上で「返信あり」とみなす
                if len(replies) >= 2:
                    target_thread_ts = final_minutes_thread_ts
                else:
                    target_thread_ts = minutes_thread_ts or final_minutes_thread_ts
            except Exception as e:
                print(f"[send_hearing_reminder] Failed to check final thread replies: {e}")
                target_thread_ts = minutes_thread_ts or final_minutes_thread_ts
        else:
            target_thread_ts = minutes_thread_ts

        # スレッドTSがない場合はスキップ
        if not target_thread_ts:
            print(f"[send_hearing_reminder] No minutes_thread_ts for: {row.get('title')}")
            print(f"[send_hearing_reminder] Please post minutes first")
            continue
        
        title = row.get("title", "無題")
        
        # 参加者リストを取得
        participants_str = row.get("participants", "").strip()
        participants = [p.strip() for p in participants_str.split(',') if p.strip()] if participants_str else []
        
        # 前回のヒアリング回答を取得
        previous_responses = [
            row.get("hearing_responses01", ""),
            row.get("hearing_responses02", ""),
            row.get("hearing_responses03", ""),
            row.get("hearing_responses04", ""),
        ]
        
        # メンション生成（participantsのメールをSlack IDに変換。ドメイン変換フォールバック含む）
        mentions = ""
        if participants:
            slack_ids = []
            for email in participants:
                slack_id = slack_client.lookup_user_id_by_email(email)
                if not slack_id and "@initialbrain.jp" in email:
                    converted_email = email.replace("@initialbrain.jp", "@nexx-inc.jp")
                    slack_id = slack_client.lookup_user_id_by_email(converted_email)
                if slack_id:
                    slack_ids.append(f"<@{slack_id}>")
            if slack_ids:
                mentions = " ".join(slack_ids)

        # メッセージ生成（メンション付与）
        message = create_hearing_message(next_meeting_date, participants, previous_responses, mentions)
        
        # Slack投稿（議事録のスレッド＝最終があれば最終）
        print(f"[send_hearing_reminder] Sending hearing reminder for: {title}")
        print(f"[send_hearing_reminder] Posting to thread: {target_thread_ts}")
        thread_ts = slack_client.post_message(channel_id, message, thread_ts=target_thread_ts)
        
        if thread_ts:
            # 送信成功: hearing_thread_tsを記録（議事録と同じスレッド）
            row_number = row.get("_row_number")
            if row_number:
                update_row(sheet_name, row_number, {
                    "hearing_thread_ts": target_thread_ts,  # 実際に投下したスレッドを保存
                    "updated_at": now_jst_str(),
                })
                print(f"[send_hearing_reminder] Successfully sent and updated row {row_number}")
        else:
            print(f"[send_hearing_reminder] Failed to send reminder for: {title}")


def main():
    """メイン処理"""
    slack_client = SlackClient()
    
    # 全シートをチェック
    sheet_names = get_all_sheet_names()
    
    for sheet_name in sheet_names:
        # システムシートはスキップ
        if sheet_name.lower() in ["mappings", "meetings", "items", "agendas", "archives", "hearing_prompts", "hearing_responses"]:
            continue
        
        try:
            send_hearing_for_sheet(sheet_name, slack_client)
        except Exception as e:
            print(f"[send_hearing_reminder] Error processing sheet {sheet_name}: {e}")
            continue


if __name__ == "__main__":
    main()

