# kintai-check

インターン生のバクラク申請自動承認 → Slack打刻との突合レポートを行うスクリプト群。

## 全体フロー

```
Step1: /kintai-daily    → 日次申請を自動承認（approve_daily.py）
Step2: 上妻・柳原が手動でW承認（バクラク上で実施。自動化対象外）
Step3: /kintai-monthly  → バクラク × Slack 突合 → 月次承認（reconcile.py + approve_monthly.py）
```

## コマンド

| コマンド | タイミング | スクリプト |
|---|---|---|
| `/kintai-daily` | インターン生が日次申請を提出した後 | `approve_daily.py` |
| `/kintai-monthly` | インターン生が月次申請を提出した後（W承認完了後） | `reconcile.py` → `approve_monthly.py` |

⚠️ `/kintai-daily` と `/kintai-monthly` は別コマンド。誤作動防止のため意図的に分離。

## ファイル構成

```
approve_daily.py       - Step1: 日次申請のみ承認（実装済み）
approve_monthly.py     - Step3: 月次申請のみ承認（実装済み）
reconcile.py           - Step3前半: バクラク × Slack 突合（実装済み）
intern_config.py       - インターン生 Slack UID・打刻キーワード定義
approve.py             - 旧スクリプト（互換性維持のため残存）
.claude/commands/
  kintai-daily.md      - /kintai-daily スラッシュコマンド定義
  kintai-monthly.md    - /kintai-monthly スラッシュコマンド定義
browser_profile/       - Playwright永続プロファイル（.gitignore対象）
out/                   - スクリーンショット・HTMLレポート（.gitignore対象）
```

## 実行方法

```bash
# 仮想環境は customer-dashboard の .venv を共用
../customer-dashboard/.venv/bin/python3 approve_daily.py
../customer-dashboard/.venv/bin/python3 reconcile.py [--month 2026-06]
../customer-dashboard/.venv/bin/python3 approve_monthly.py
```

## バクラク技術仕様（実機調査済み）

| 項目 | 値 |
|---|---|
| 日次承認URL | `/workflow_instances/assigned/daily` |
| 月次承認URL | `/workflow_instances/assigned/monthly` |
| メンバー一覧URL | `/manager/daily_works` |
| メンバー月次出退勤URL | `/manager/daily_works/{bakuraku_id}?yearMonth=YYYY-MM` |
| ログイン検知方法 | body内テキストに「出勤簿」「承認する」「打刻」が出現したら完了 |
| 承認フロー | ヘッダーCBで全選択 → 「一括承認する」ボタン → ダイアログ「一括承認」（完全一致） |
| セッション形式 | `launch_persistent_context`（ブラウザプロファイル丸ごと保存）。Googleログイン状態を長期維持 |
| メンバーID形式 | ULID 26文字英数字（例: `01KMY7ED0MPX8061HPT2GV6D4E`） |

## reconcile.py 設計

- バクラクデータ: メンバー名クリック→URL取得でID自動発見 → 月次テーブルをスクレイプ
- Slackデータ: `#team-美容マーケ` から該当月のメッセージを取得・解析
- 突合判定: ±10分以内=✅ OK / 11分以上ずれ=❌ mismatch / 片方なし=⚠️ 要確認
- 出力: `out/reconcile_YYYY-MM.html`
- 終了コード: 0=全一致（自動承認OK）、1=不一致あり（HTML確認後に手動トリガー）

## 担当者情報

- 日次・月次承認者: 森島・佐草・国広・石原（各自のClaudeCodeから実行）
- W承認者: 上妻 史佳・柳原 千春（手動。経理側）
- 対象インターン: 福田・上野（森島担当）、御園・兵庫（佐草担当）、廣嶋（国広担当）、西口（石原担当）
- Slack打刻チャンネル: `#team-美容マーケ`

---

## GitHub PR 手順（準備完了状態）

### 前提確認チェックリスト

- [ ] `reconcile.py` 実機テスト完了（月次申請が来たタイミングで実施）
- [ ] `test_members.py` を削除（テスト用・PR不要）
- [ ] `approve.md`（旧コマンド）を削除: `rm .claude/commands/approve.md`

### Step 1: GitHub CLI ログイン（未ログインの場合のみ）

```bash
gh auth login
# → GitHub.com → SSH → Authenticate Git with credentials → ブラウザで認証
```

### Step 2: git 初期化・初回コミット

```bash
cd /Users/info/Documents/projects/kintai-check
git init
git add intern_config.py approve_daily.py approve_monthly.py approve.py reconcile.py
git add requirements.txt .gitignore .env.example README.md CLAUDE.md
git add .claude/commands/kintai-daily.md .claude/commands/kintai-monthly.md
git commit -m "feat: バクラク×Slack勤怠突合システム 初期実装

- approve_daily.py: 日次申請自動承認（/kintai-daily）
- approve_monthly.py: 月次申請自動承認
- reconcile.py: バクラク×Slack突合 → HTMLレポート → 月次承認
- intern_config.py: インターン生Slack IDマッピング
- .claude/commands/: /kintai-daily / /kintai-monthly スラッシュコマンド"
```

### Step 3: GitHub private リポジトリ作成・push

```bash
gh repo create kintai-check --private --source=. --push
```

→ URL が返ってくる（例: `https://github.com/osamu-morishima/kintai-check`）

### Step 4: 他の担当者をコラボレーターに追加

```bash
gh api repos/osamu-morishima/kintai-check/collaborators/sakusa-username -X PUT -f permission=pull
gh api repos/osamu-morishima/kintai-check/collaborators/kunihiro-username -X PUT -f permission=pull
gh api repos/osamu-morishima/kintai-check/collaborators/ishihara-username -X PUT -f permission=pull
# username は各人の GitHub アカウント名に置き換え
```

### Step 5: 他の担当者のセットアップ手順（共有する内容）

```bash
# 1. リポジトリをクローン
git clone https://github.com/osamu-morishima/kintai-check.git
cd kintai-check

# 2. customer-dashboard の .venv があることを確認
ls ../customer-dashboard/.venv/bin/python3

# 3. SLACK_BOT_TOKEN を設定（customer-dashboard/.env になければ）
cp .env.example .env
# .env を開いて SLACK_BOT_TOKEN を貼り付け

# 4. 初回ログイン
../customer-dashboard/.venv/bin/python3 approve_daily.py
# → ブラウザが開くので Google アカウントでログイン

# 5. Claude Code でこのディレクトリを開く
claude
# → /kintai-daily または /kintai-monthly を実行
```

### 残タスク（PR 前に完了が必要なもの）

- [ ] `reconcile.py` 実機テスト: 月次申請が来たら `/kintai-monthly` で実行確認
- [ ] 他の担当者の GitHub ユーザー名を確認（コラボレーター追加に必要）
