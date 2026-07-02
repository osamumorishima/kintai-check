# kintai-check

インターン生のバクラク申請を自動承認し、Slack打刻と突合するツール。

---

## 全体フロー

```
① インターン生が日次申請を提出
    ↓
② 担当者が /kintai-daily を実行 → 日次申請を自動承認
    ↓
③ 上妻・柳原（経理）が手動でW承認（バクラク上で実施）
    ↓
④ インターン生が月次申請を提出
    ↓
⑤ 担当者が /kintai-monthly を実行
    → Slack打刻 × バクラク出退勤を突合
    → 全一致: 月次申請を自動承認
    → 不一致: HTMLレポートを確認 →「問題なし」と返答 → 承認
```

---

## セットアップ（初回のみ）

### 1. リポジトリをクローン

```bash
git clone https://github.com/osamumorishima/kintai-check.git
cd kintai-check
```

### 2. .env を作成

```bash
cp .env.example .env
```

`.env` を開いて以下を設定する。

```
# 担当インターン生の姓（カンマ区切り）
INTERN_NAMES=福田,上野

# Slack Bot Token（customer-dashboard/.env に設定済みなら不要）
SLACK_BOT_TOKEN=xoxb-...
```

> `INTERN_NAMES` は自分が担当するインターン生の姓のみ記載する。

### 3. バクラクに初回ログイン

```bash
../customer-dashboard/.venv/bin/python3 approve_daily.py
```

ブラウザが開くので Google アカウントでログインする。以降は自動復元されるため再ログイン不要。

### 4. Claude Code でこのディレクトリを開く

```bash
claude
```

---

## 使い方

### 日次申請が届いたとき

```
/kintai-daily
```

### 月次申請・突合（W承認完了後）

```
/kintai-monthly
```

実行すると担当インターン生の Slack ID を自動取得し、バクラクと突合する。

- **全一致** → 月次承認まで自動で完了
- **不一致あり** → HTMLレポートのリンクが表示される。内容を確認して「問題なし」と返答すると承認に進む

---

## 担当者 → インターン生 対応表

| 担当者 | INTERN_NAMES に設定する値 |
|---|---|
| 森島 | `福田,上野` |
| 佐草 | `御園,兵庫` |
| 国広 | `廣嶋` |
| 石原 | `西口` |

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| 「未ログイン」と表示される | ブラウザが開くのでGoogleアカウントでログイン |
| ログイン後も「未ログイン」になる | `browser_profile/` を削除して再実行 |
| `INTERN_NAMES が未設定` と表示される | `.env` に `INTERN_NAMES=姓,姓` を追記 |
| Slack IDが見つからない | `.env` の `INTERN_NAMES` の表記をSlackの表示名に合わせる |
| SLACK_BOT_TOKEN エラー | `.env` に `SLACK_BOT_TOKEN` を設定 |
