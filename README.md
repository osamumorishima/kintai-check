# kintai-check

インターン生のバクラク申請を自動承認し、Slack打刻と突合するツール。

---

## 毎月の運用フロー

```
① インターン生が日次申請を提出
    ↓
② 担当者が /kintai-daily を実行 → 日次申請を自動承認
    ↓
③ 上妻・柳原（経理）が手動でW承認（バクラク上で実施）
    ↓
④ インターン生が月次申請を提出
    ↓
⑤ 担当者が /kintai-monthly を実行 → 突合・月次承認
```

---

## 担当者 → インターン生 対応表

| 担当者 | 担当インターン生 |
|---|---|
| 森島 | 福田・上野 |
| 佐草 | 西口・兵庫 |
| 国広 | 廣嶋 |
| 石原 | 御園 |

---

## セットアップ（初回のみ）

### ステップ 1｜ファイルをダウンロードする

Mac の **Terminal.app**（アプリケーション → ユーティリティ → ターミナル）を開き、以下を実行する。

```bash
cd ~/Documents
git clone https://github.com/osamumorishima/kintai-check.git
cd kintai-check
```

### ステップ 2｜担当インターン生と Slack Token を設定する

以下のコマンドで設定ファイルを作成する。

```bash
cp .env.example .env
open -e .env
```

テキストエディットが開くので、以下の2行を自分の情報に書き換えて保存する。

```
INTERN_NAMES=福田:Fukuta,上野:Ueno    ← バクラク表示名:Slack表示名（ローマ字）をカンマ区切りで記入
SLACK_BOT_TOKEN=xoxb-...              ← 森島から共有されたトークンを貼り付け
```

> **`INTERN_NAMES` の記入形式:** `バクラク上の日本語名:Slack上のローマ字名` をカンマ区切り
>
> | 担当者 | 記入値 |
> |---|---|
> | 佐草 | `西口:Nishiguchi,兵庫:Hyogo` |
> | 国広 | `廣嶋:Yuzuki` |
> | 石原 | `御園:Misono` |

### ステップ 3｜Python 環境をセットアップしてバクラクにログインする

Terminal.app で以下を順番に実行する（初回のみ・数分かかる）。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

インストール完了後、以下を実行してバクラクにログインする。

```bash
.venv/bin/python3 approve_daily.py
```

ブラウザが自動で開くので、バクラクで使っている **Google アカウントでログイン** する。ログイン後はブラウザを閉じてよい。次回以降は自動でログイン状態が復元されるため、この手順は不要。

### ステップ 4｜Claude Code でこのフォルダを開く

Terminal.app で以下を実行する。

```bash
cd ~/Documents/kintai-check
claude
```

Claude Code が起動したら準備完了。次回以降はこのコマンドだけで使える。

---

## 使い方

### 日次申請が届いたとき → `/kintai-daily`

Claude Code の入力欄に以下を入力して Enter を押す。

```
/kintai-daily
```

バクラクが自動で開き、申請を承認して閉じる。

---

### 月次申請・突合（W承認完了後）→ `/kintai-monthly`

上妻・柳原（経理）のW承認が完了したら、Claude Code の入力欄に以下を入力して Enter を押す。

```
/kintai-monthly
```

自動で以下を実行する。

1. 担当インターン生の Slack ID を自動取得（名前の確認あり）
2. バクラクの出退勤データを取得
3. Slack の打刻データと突合
4. **全一致の場合** → 月次承認まで自動完了。終了メッセージが出る
5. **不一致がある場合** → HTMLレポートのリンクが表示される

**不一致があった場合：**
- 表示されたリンクをブラウザで開いてレポートを確認する
- 問題なければ Claude Code に「問題なし」と入力する
- 承認が自動で実行される

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| 「未ログイン」と表示される | ブラウザが開くのでバクラクのGoogleアカウントでログイン |
| ログイン後も「未ログイン」になる | `browser_profile/` フォルダを削除して再実行 |
| `INTERN_NAMES が未設定` と表示される | `.env` を開いて `INTERN_NAMES=姓,姓` を追記して保存 |
| Slack ID が見つからない | `.env` の `INTERN_NAMES` の表記をSlackの表示名に合わせる |
| SLACK_BOT_TOKEN エラー | `.env` に `SLACK_BOT_TOKEN` を設定（森島に確認） |
