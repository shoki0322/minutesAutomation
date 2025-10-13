# Minutes Automation System

議事録管理を自動化するシステム。Google Drive、Google Sheets、Slack を連携して、会議準備から議事録投稿までを自動化します。

## 機能概要

### 1. Drive 監視 → シート更新

- **実行頻度**: 2 時間に 1 回
- **処理内容**:
  - 指定フォルダ内の新規 Google Docs を検知
  - ドキュメントの本文をテキスト化してシートに追加
  - `next_meeting_date`（検知日+7 日）を自動設定

### 2. 議事録投稿

- **トリガー**: `formatted_minutes`列が埋まったら自動実行（会議当日のみ）
- **処理内容**:
  - Calendar API から参加者を取得
    - 検索条件: `date`（会議日）+ `title`（会議タイトル）で特定
    - フォールバック: `meeting_key`、または当日最初のイベント
  - 参加者メールアドレスを`participants`列に保存
  - Slack ID に変換してメンション付きで投稿
  - `formatted_minutes`の内容をそのまま投稿

### 3. ヒアリング依頼リマインダー

- **実行タイミング**: `next_meeting_date`の 2 日前 09:00 JST
- **処理内容**:
  - 事業部チャンネルにヒアリング依頼を投稿
  - テンプレートに沿ったフォーマットで投稿
  - スレッドで回答を受け付け

### 4. 議題共有リマインダー

- **実行タイミング**: `next_meeting_date`の前日 18:00 JST
- **処理内容**:
  - `next_agenda`が入力されている場合に投稿
  - 明日の会議議題を事前共有

### 5. ヒアリング回答収集

- **実行タイミング**: `next_meeting_date`の 1 日前 09:00 JST
- **処理内容**:
  - Slack スレッドから回答を収集
  - 時間が早い順に最大 4 件をシートに格納（`hearing_responses01`-`04`）

## セットアップ

### 必要な環境変数

以下の Secrets を GitHub Actions に設定してください：

```
GOOGLE_CLIENT_ID          # Google OAuth2 クライアントID
GOOGLE_CLIENT_SECRET      # Google OAuth2 クライアントシークレット
GOOGLE_REFRESH_TOKEN      # Google OAuth2 リフレッシュトークン
SLACK_BOT_TOKEN          # Slack Bot Token (xoxb-...)
PRIMARY_SHEET_ID         # スプレッドシートID
DRIVE_FOLDER_ID          # 監視対象のDriveフォルダID
DEFAULT_TIMEZONE         # タイムゾーン（デフォルト: Asia/Tokyo）
```

### リフレッシュトークンの取得

```bash
python get_refresh_token.py
```

### ローカル実行

```bash
# 依存関係のインストール
pip install -r requirements.txt

# 各スクリプトの実行
python -m src.drive_monitor              # Drive監視
python -m src.check_and_post_minutes     # 議事録投稿チェック
python -m src.send_hearing_reminder      # ヒアリング依頼
python -m src.send_agenda_reminder       # 議題共有
python -m src.collect_hearing_responses  # ヒアリング回答収集
```

## スプレッドシート構造

各事業部ごとにシートを作成します。以下の列を含めてください：

| 列  | 列名                  | 説明                                 |
| --- | --------------------- | ------------------------------------ |
| A   | `meeting_key`         | 会議識別キー（Calendar API 用）      |
| B   | `title`               | ドキュメントタイトル                 |
| C   | `date`                | 検知日                               |
| D   | `next_meeting_date`   | 次回会議日（date + 7 日が初期値）    |
| E   | `participants`        | 会議参加者メールアドレス（自動取得） |
| F   | `doc_url`             | Google Docs の URL                   |
| G   | `summary`             | Docs の本文テキスト                  |
| H   | `formatted_minutes`   | 整形済み議事録（自動入力）           |
| I   | `decisions`           | 決定事項                             |
| J   | `open_issues`         | 残論点                               |
| K   | `hearing_responses01` | ヒアリング回答 1（自動格納）         |
| L   | `hearing_responses02` | ヒアリング回答 2（自動格納）         |
| M   | `hearing_responses03` | ヒアリング回答 3（自動格納）         |
| N   | `hearing_responses04` | ヒアリング回答 4（自動格納）         |
| O   | `next_agenda`         | 次回議題（自動入力）                 |
| P   | `channel_id`          | Slack 投稿先チャンネル ID            |
| Q   | `minutes_posted`      | 議事録投稿済みフラグ                 |
| R   | `minutes_thread_ts`   | 議事録投稿のスレッドタイムスタンプ   |
| S   | `hearing_thread_ts`   | ヒアリングスレッドのタイムスタンプ   |
| T   | `updated_at`          | 最終更新日時                         |
| U   | `status`              | ステータス                           |
| V   | `remarks`             | 備考                                 |

## GitHub Actions ワークフロー

### drive_monitor.yml

- **スケジュール**: 2 時間に 1 回（`0 */2 * * *`）
- **処理**: Drive 監視と新規 Docs 検知

### hourly_tasks.yml

- **スケジュール**: 1 時間に 1 回（`0 * * * *`）
- **処理**:
  - 議事録投稿チェック
  - ヒアリング依頼送信
  - 議題共有送信
  - ヒアリング回答収集

## プロジェクト構成

```
.
├── .github/
│   └── workflows/
│       ├── drive_monitor.yml      # Drive監視ワークフロー
│       └── hourly_tasks.yml       # 定期実行タスク
├── src/
│   ├── auth.py                    # Google認証
│   ├── google_clients.py          # Google APIクライアント
│   ├── slack_client.py            # Slackクライアント
│   ├── minutes_repo.py            # シート管理
│   ├── drive_monitor.py           # Drive監視
│   ├── check_and_post_minutes.py  # 議事録投稿
│   ├── send_hearing_reminder.py   # ヒアリング依頼
│   ├── send_agenda_reminder.py    # 議題共有
│   └── collect_hearing_responses.py # 回答収集
├── requirements.txt
├── get_refresh_token.py
└── README.md
```

## 運用フロー

1. **会議後**: Google Drive にドキュメントを作成 → 自動検知してシート追加
2. **議事録作成**: `formatted_minutes`列に議事録を手動入力
3. **議事録投稿**: 自動的に Slack に投稿される
4. **2 日前**: ヒアリング依頼が自動送信
5. **1 日前 09 時**: ヒアリング回答を自動収集
6. **1 日前 18 時**: 議題共有が自動送信

## トラブルシューティング

### Google API 認証エラー

```bash
# リフレッシュトークンを再取得
python get_refresh_token.py
```

### Slack 投稿が失敗する

- `SLACK_BOT_TOKEN`が正しいか確認
- Bot が該当チャンネルに参加しているか確認
- Bot の権限スコープを確認（`chat:write`, `users:read.email`など）

### シート更新が反映されない

- `PRIMARY_SHEET_ID`が正しいか確認
- スプレッドシートの共有設定を確認
- サービスアカウントに編集権限があるか確認

## ライセンス

MIT
