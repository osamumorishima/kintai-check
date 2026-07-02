#!/usr/bin/env python3
"""
intern_config.py
インターン生の打刻キーワード・設定定義

担当インターン生の氏名（姓）は .env の INTERN_NAMES に設定してください。
Slack UID は起動時に自動取得します。
"""
import re, os

# 担当インターン生の姓リスト（.env の INTERN_NAMES から読み込む）
# 例: INTERN_NAMES=福田,上野
INTERN_NAMES = [n.strip() for n in os.getenv("INTERN_NAMES", "").split(",") if n.strip()]

# 打刻キーワード正規表現（RE_BREAK を先に評価すること）
RE_BREAK = re.compile(r"いちぬけ|なかぬけ|一旦退勤", re.IGNORECASE)
RE_BACK  = re.compile(r"再開|もどった|もどります|復帰|戻り|戻りました", re.IGNORECASE)
RE_IN    = re.compile(r"稼[働働]|かどう|出勤|しゅっきん", re.IGNORECASE)
RE_OUT   = re.compile(r"退勤|たいきん", re.IGNORECASE)

PUNCH_CHANNEL_NAME = "team-美容マーケ"
TOLERANCE_MIN = 10  # ±10分許容
