# AI Meeting Autopilot v1

Google Docs 議事録 → Sheets 保存 → アクション抽出 → Slack 投稿 → ヒアリング収集 → 合体アジェンダ投稿を GitHub Actions + OAuth（ユーザー認証） + Python で自動化する最小構成です。

## セットアップ

1) リポジトリに以下の Secrets を登録してください
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN
- SLACK_BOT_TOKEN
- PRIMARY_SHEET_ID
- DEFAULT_CHANNEL_ID
- DRIVE_FOLDER_ID
- MEETING_KEY
- DEFAULT_TIMEZONE（例: Asia/Tokyo、未指定時は Asia/Tokyo）

2) Python 環境
- Python 3.11
- `pip install -r requirements.txt`

3) 手動実行例
- 会議当日フロー: `python -m src.docs_ingest && python -m src.action_extract && python -m src.post_retrospective`
- 2日前ヒアリング: `python -m src.post_hearing`
- 毎朝収集: `python -m src.collect_replies`
- 前日アジェンダ: `python -m src.build_agenda && python -m src.post_agenda`

## データモデル（Google Sheets タブ）
- mappings(meeting_key, slack_channel_id, email, slack_user_id, display_name)
- meetings(meeting_id, meeting_key, date, title, doc_id, participant_emails, channel_id, parent_ts)
- items(date, meeting_id, task, assignee_email, assignee_slack_id, due, links, status, dedupe_key)
- hearing_prompts(meeting_id, channel_id, parent_ts, assignee_slack_id, prompt_ts, due_to_reply, status)
- hearing_responses(meeting_id, assignee_slack_id, reply_ts, todo_status, reports, blockers, links, raw_text)
- agendas(meeting_id, channel_id, thread_ts, body_md, posted_ts)

初回実行時、各タブが存在しない場合は自動作成され、ヘッダ行が挿入されます。

## 冪等性と実行の安全性
- items.dedupe_key（{date}:{assignee_email}:{sha1(task)}）で重複登録防止
- meetings.parent_ts が既に存在する場合、重複投稿を抑止
- hearing_responses は (meeting_id + assignee_slack_id + reply_ts) で upsert
- Slack 投稿はチャンネル未設定時にスキップ（警告出力）
- 主要処理は print ログ。例外は投げて Actions が失敗を検知

## タイムゾーン
- DEFAULT_TIMEZONE（例: Asia/Tokyo）を参照。Actions の cron は UTC

