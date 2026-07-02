#!/usr/bin/env python3
"""
intern_config.py
インターン生の打刻キーワード・設定定義

担当インターン生の氏名（姓）は .env の INTERN_NAMES に設定してください。
Slack UID は起動時に自動取得します。
"""
import re, os

# 担当インターン生の姓リスト（.env の INTERN_NAMES から読み込む）
# 形式: バクラク表示名:Slack検索キー（カンマ区切り）
# 例: INTERN_NAMES=福田:Fukuta,上野:Ueno
# Slack名が日本語の場合は コロンなし: INTERN_NAMES=福田,上野
_raw_names = [n.strip() for n in os.getenv("INTERN_NAMES", "").split(",") if n.strip()]
INTERN_NAMES = []          # バクラク上の名前（Playwright text検索に使用）
INTERN_SLACK_NAMES = {}    # {バクラク名: Slack検索キー}

for _entry in _raw_names:
    if ":" in _entry:
        _bk, _slack = _entry.split(":", 1)
        _bk, _slack = _bk.strip(), _slack.strip()
    else:
        _bk = _slack = _entry
    INTERN_NAMES.append(_bk)
    INTERN_SLACK_NAMES[_bk] = _slack

# 打刻キーワード正規表現（RE_BREAK を先に評価すること）
RE_BREAK = re.compile(r"いちぬけ|なかぬけ|一旦退勤", re.IGNORECASE)
RE_BACK  = re.compile(r"再開|もどった|もどります|復帰|戻り|戻りました", re.IGNORECASE)
RE_IN    = re.compile(r"稼[働働]|かどう|出勤|しゅっきん", re.IGNORECASE)
RE_OUT   = re.compile(r"退勤|たいきん", re.IGNORECASE)

PUNCH_CHANNEL_NAME = "team-美容マーケ"
TOLERANCE_MIN = 10  # ±10分許容
