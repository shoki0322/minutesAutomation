"""
議事録投稿チェックスクリプト
formatted_minutesが埋まったら、参加者メンション付きでSlackに投稿
"""
import os
from datetime import datetime
from typing import List, Optional
from dateutil import tz
from .google_clients import calendar as calendar_client
from .slack_client import SlackClient
from .minutes_repo import (
    get_all_sheet_names,
    read_sheet_rows,
    update_row,
    now_jst_str,
)

# Slackの投稿先はシートの channel_id のみを使用する（環境変数は使わない）


def get_calendar_participants(date: str, title: str = "", meeting_key: str = "", require_exact_title: bool = False) -> List[str]:
    """
    Calendar APIから該当会議の参加者メールアドレスを取得
    date: 会議日（YYYY-MM-DD形式）
    title: 会議タイトル（優先的に使用）
    meeting_key: 会議識別キー（タイトルが一致しない場合のフォールバック）
    """
    if not date:
        print("[check_and_post_minutes] date is empty, skipping participant lookup")
        return []
    
    try:
        cal_service = calendar_client()
        
        # 該当日の00:00 - 23:59の範囲でイベントを検索
        from datetime import datetime, timedelta
        import pytz
        
        tz = pytz.timezone(os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo"))
        date_dt = datetime.strptime(date, "%Y-%m-%d")
        date_dt = tz.localize(date_dt)
        
        time_min = date_dt.isoformat()
        time_max = (date_dt + timedelta(days=1)).isoformat()
        
        events_result = cal_service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        
        events = events_result.get("items", [])
        
        if not events:
            print(f"[check_and_post_minutes] No calendar events found on {date}")
            return []
        
        # イベントを検索（優先順位: title > meeting_key）
        target_event = None
        
        # 1. タイトルで完全一致または部分一致を探す
        if title:
            # "-"の前までをベースタイトルとして扱う（例: "[weekly] AI基盤MTG - 2025/..." -> "[weekly] AI基盤MTG")
            def normalize(s: str) -> str:
                return (s or "").replace("\u3000", " ").strip()
            splitchars = ["-", "－", "–", "—"]
            base_title = None
            for ch in splitchars:
                if ch in title:
                    base_title = title.split(ch, 1)[0]
                    break
            if base_title is None:
                base_title = title
            base_title = normalize(base_title)

            for event in events:
                summary = normalize(event.get("summary", ""))
                # 完全一致
                if summary == base_title:
                    target_event = event
                    print(f"[check_and_post_minutes] Found event by exact title match: {summary}")
                    break

            # 厳密一致のみ要求の場合はここで終了
            if require_exact_title and not target_event:
                print("[check_and_post_minutes] No exact title match found; skipping attendees update")
                return []

            # 厳密一致でない場合は部分一致も許容
            if not require_exact_title and not target_event:
                for event in events:
                    summary = normalize(event.get("summary", ""))
                    if base_title in summary or summary in base_title:
                        target_event = event
                        print(f"[check_and_post_minutes] Found event by partial title match: {summary}")
                        break
        
        # 2. meeting_keyで検索（タイトルで見つからない場合）
        if not target_event and meeting_key:
            for event in events:
                summary = event.get("summary", "")
                description = event.get("description", "")
                if meeting_key in summary or meeting_key in description:
                    target_event = event
                    print(f"[check_and_post_minutes] Found event by meeting_key: {summary}")
                    break
        
        # 3. フォールバック（厳密一致要求時は使わない）
        if not target_event and not require_exact_title:
            target_event = events[0]
            print(f"[check_and_post_minutes] Using first event of the day: {target_event.get('summary', '')}")
        if not target_event:
            return []
        
        # 参加者を取得
        attendees = target_event.get("attendees", [])
        emails = [a["email"] for a in attendees if "email" in a]
        # ワークスペースドメインで限定（任意）
        workspace_domains = [d.strip() for d in os.getenv("WORKSPACE_DOMAINS", "").split(",") if d.strip()]
        if workspace_domains:
            emails = [e for e in emails if any(e.endswith(f"@{dom}") for dom in workspace_domains)]
        
        print(f"[check_and_post_minutes] Found {len(emails)} participants")
        return emails
        
    except Exception as e:
        print(f"[check_and_post_minutes] Error getting calendar participants: {e}")
        return []


def email_to_slack_id(slack_client: SlackClient, email: str) -> Optional[str]:
    """メールアドレスからSlack IDに変換（ドメイン変換対応）"""
    # まず元のメールで試す
    slack_id = slack_client.lookup_user_id_by_email(email)
    if slack_id:
        return slack_id
    
    # 見つからない場合、ドメインを変換して再試行
    if "@initialbrain.jp" in email:
        converted_email = email.replace("@initialbrain.jp", "@nexx-inc.jp")
        print(f"[check_and_post_minutes] Trying converted email: {email} -> {converted_email}")
        slack_id = slack_client.lookup_user_id_by_email(converted_email)
        if slack_id:
            return slack_id
    
    return None


def check_and_post_for_sheet(sheet_name: str, slack_client: SlackClient):
    """1つのシートに対して議事録投稿チェックを実行"""
    print(f"[check_and_post_minutes] Checking sheet: {sheet_name}")
    
    rows = read_sheet_rows(sheet_name)
    
    # 現在の日付（JST）
    tz_info = tz.gettz(os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo"))
    today = datetime.now(tz_info).strftime("%Y-%m-%d")
    
    print(f"[check_and_post_minutes] Today's date (JST): {today}")
    print(f"[check_and_post_minutes] Found {len(rows)} rows in sheet: {sheet_name}")
    
    for row in rows:
        formatted_minutes = row.get("formatted_minutes", "").strip()
        remarks = row.get("remarks", "").strip()
        minutes_posted = row.get("minutes_posted", "").strip()
        minutes_thread_ts = row.get("minutes_thread_ts", "").strip()
        date_raw = row.get("date", "").strip()
        date_day = date_raw[:10] if date_raw else ""
        title = row.get("title", "無題")
        meeting_key = row.get("meeting_key", "")
        channel_id = row.get("channel_id", "").strip()
        
        print(f"[check_and_post_minutes] Checking row: {title}")
        print(f"  - date: '{date_raw}' (today: '{today}', match: {date_day == today})")
        print(f"  - formatted_minutes: {'YES' if formatted_minutes else 'NO'} (length: {len(formatted_minutes)})")
        print(f"  - minutes_posted: '{minutes_posted}'")
        print(f"  - minutes_thread_ts: '{minutes_thread_ts}'")
        print(f"  - remarks_has_gpt: {'✅ GPT整形済み' in remarks}")
        
        # まずカレンダーAPIを最初に実行（当日分のみ）。参加者をシートに保存。
        participant_emails: List[str] = []
        if date_day == today:
            participant_emails = get_calendar_participants(date_day, title, meeting_key, require_exact_title=True)
            participants_str_existing = row.get("participants", "").strip()
            participants_str_new = ", ".join(participant_emails) if participant_emails else ""
            if participants_str_new and participants_str_new != participants_str_existing:
                row_number = row.get("_row_number")
                if row_number:
                    update_row(sheet_name, row_number, {
                        "participants": participants_str_new,
                        "updated_at": now_jst_str(),
                    })
                    print(f"[check_and_post_minutes] Participants updated for row {row_number}")

        # 条件1: 会議当日のみ投稿
        if date_day != today:
            print(f"  → SKIP: date mismatch")
            continue
        
        # 条件2: formatted_minutesが非空
        if not formatted_minutes:
            print(f"  → SKIP: no formatted_minutes")
            continue

        # 条件3: remarks に ✅ GPT整形済み を含む
        if "✅ GPT整形済み" not in remarks:
            print(f"  → SKIP: remarks does not include '✅ GPT整形済み'")
            continue

        # 既にスレッドTSがあれば投稿済みとみなしてスキップ（minutes_postedは参照しない）
        if minutes_thread_ts:
            print(f"  → SKIP: minutes_thread_ts already set ({minutes_thread_ts})")
            continue
        
        # 投稿処理
        print(f"  → PROCESSING: will post minutes")
        # meeting_key, channel_id は先頭で取得済み
        
        if not channel_id:
            print(f"[check_and_post_minutes] No channel_id for row: {title} (skipping)")
            continue
        
        # 参加者は既に取得済み（安全のため未取得なら再取得）
        if not participant_emails:
            participant_emails = get_calendar_participants(date_day, title, meeting_key, require_exact_title=True)
        mentions = []
        
        for email in participant_emails:
            slack_id = email_to_slack_id(slack_client, email)
            if slack_id:
                mentions.append(f"<@{slack_id}>")
        
        mentions_text = " ".join(mentions) if mentions else ""
        
        # 参加者メールをカンマ区切りで保存用に整形
        participants_str = ", ".join(participant_emails) if participant_emails else ""
        
        # 投稿本文（formatted_minutesをそのまま投稿）
        message_parts = []
        
        if mentions_text:
            message_parts.append(mentions_text)
            message_parts.append("")
        
        message_parts.append(formatted_minutes)
        
        message = "\n".join(message_parts)
        
        # Slack投稿（親メッセージ）
        print(f"[check_and_post_minutes] Posting minutes for: {title}")
        ts = slack_client.post_message(channel_id, message)
        
        if ts:
            # 成功: updated_at、participants、minutes_thread_tsを更新（minutes_postedは不使用）
            row_number = row.get("_row_number")
            if row_number:
                update_row(sheet_name, row_number, {
                    "updated_at": now_jst_str(),
                    "participants": participants_str,
                    "minutes_thread_ts": ts,
                })
                print(f"[check_and_post_minutes] Successfully posted and updated row {row_number}")

            # 追記: 修正依頼の案内をスレッドに投稿
            try:
                review_user_id = os.getenv("REVIEW_USER_ID", "").strip()  # 例: U0123456789
                trigger_name = os.getenv("REVIEW_TRIGGER_KEYWORDS", "DR.ベガパンク").split(",")[0].strip()
                # 参加者メンション（必要に応じて）
                notify_mentions = []
                for email in participant_emails:
                    sid = email_to_slack_id(slack_client, email)
                    if sid:
                        notify_mentions.append(f"<@{sid}>")
                notify_text = (" ".join(notify_mentions) + "\n\n") if notify_mentions else ""
                review_target_text = f"<@{review_user_id}>" if review_user_id else f"@{trigger_name}"
                guidance = (
                    f"{notify_text}翌朝9:00(JST)までに、必要な修正依頼をこのスレッドへ返信してください。\n"
                    f"参加者間で合意した修正依頼は {review_target_text} をメンションすると、AIが議事録に反映します。\n"
                    f"フォーマット例: 修正依頼：該当箇所／修正文"
                )
                slack_client.post_message(channel_id, guidance, thread_ts=ts)
                print("[check_and_post_minutes] Posted review guidance in thread")
            except Exception as e:
                print(f"[check_and_post_minutes] Failed to post review guidance: {e}")
        else:
            print(f"[check_and_post_minutes] Failed to post minutes for: {title}")


def main():
    """メイン処理"""
    # 初回議事録（formatted_minutes）投稿は MINUTES ボット
    slack_client = SlackClient(token=os.getenv("SLACK_BOT_TOKEN_MINUTES", "").strip() or None)
    
    # 全シートをチェック
    sheet_names = get_all_sheet_names()
    
    for sheet_name in sheet_names:
        # システムシートはスキップ
        if sheet_name.lower() in ["mappings", "meetings", "items", "agendas", "archives", "hearing_prompts", "hearing_responses"]:
            continue
        
        try:
            check_and_post_for_sheet(sheet_name, slack_client)
        except Exception as e:
            print(f"[check_and_post_minutes] Error processing sheet {sheet_name}: {e}")
            continue


if __name__ == "__main__":
    main()

