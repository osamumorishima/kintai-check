#!/usr/bin/env python3
"""
reconcile.py  v1.0
バクラク月次出退勤 × Slack打刻 突合スクリプト

実行:
  ../customer-dashboard/.venv/bin/python3 reconcile.py              # 当月
  ../customer-dashboard/.venv/bin/python3 reconcile.py --month 2026-06

出力:
  out/reconcile_YYYY-MM.html  突合レポート（ブラウザで開いて確認）

終了コード:
  0 = 全一致（月次承認を自動実行してよい）
  1 = 不一致あり（HTMLを確認して「問題なし」と返答後に approve_monthly.py を実行）
"""
import sys, time, re, os, calendar, argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from dotenv import load_dotenv

# .env: customer-dashboard/.env を優先、次にローカル .env
_here = Path(__file__).parent
load_dotenv(_here.parent / "customer-dashboard" / ".env")
load_dotenv(_here / ".env", override=False)

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from intern_config import INTERN_NAMES, INTERN_SLACK_NAMES, RE_IN, RE_OUT, RE_BREAK, RE_BACK, PUNCH_CHANNEL_NAME, TOLERANCE_MIN

JST = timezone(timedelta(hours=9))
PROFILE_DIR   = _here / "browser_profile"
PROFILE_DIR.mkdir(exist_ok=True)
OUT_DIR       = _here / "out"
OUT_DIR.mkdir(exist_ok=True)
BAKURAKU_BASE = "https://attendance.layerx.jp"
MEMBERS_URL   = f"{BAKURAKU_BASE}/manager/daily_works"


# ── 引数処理 ────────────────────────────────────────────────────────────────────
def _parse_args():
    now = datetime.now(tz=JST)
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=f"{now.year}-{now.month:02d}",
                        help="対象月 YYYY-MM（省略時: 当月）")
    args = parser.parse_args()
    year, month = map(int, args.month.split("-"))
    return year, month, args.month


# ── Slack: インターン生の氏名から UID を自動取得 ────────────────────────────────
def resolve_slack_ids(names):
    """
    INTERN_NAMES の姓リストから Slack UID を自動取得。
    複数候補が出た場合は選択を求める。
    Returns: {name: slack_id}
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    try:
        from slack_sdk import WebClient
        client = WebClient(token=token)
    except ImportError:
        print("❌ slack_sdk が未インストールです")
        sys.exit(1)

    print("\n[Slack ID 自動取得]")

    # ユーザー一覧を全件取得
    all_users = []
    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor)
        all_users.extend(resp["members"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    # ボット・削除済みを除外
    real_users = [u for u in all_users if not u.get("is_bot") and not u.get("deleted")]

    result = {}
    for name in names:
        # バクラク名→Slackキーに変換（ローマ字対応、大文字小文字吸収）
        slack_key = INTERN_SLACK_NAMES.get(name, name)
        matches = []
        for u in real_users:
            profile = u.get("profile", {})
            candidate_names = [
                profile.get("display_name", ""),
                profile.get("real_name", ""),
                profile.get("display_name_normalized", ""),
                profile.get("real_name_normalized", ""),
            ]
            if any(slack_key.lower() in cn.lower() for cn in candidate_names):
                matches.append(u)

        if len(matches) == 1:
            uid = matches[0]["id"]
            display = matches[0].get("profile", {}).get("display_name") or matches[0].get("name", "")
            print(f"  {name} → {uid}（{display}）✅")
            result[name] = uid
        elif len(matches) == 0:
            print(f"  {name} → ❌ Slack上に見つかりませんでした（INTERN_NAMES の表記を確認してください）")
            result[name] = None
        else:
            print(f"  {name} → 複数候補あり:")
            for i, u in enumerate(matches):
                display = u.get("profile", {}).get("display_name") or u.get("name", "")
                print(f"    {i + 1}. {u['id']}（{display}）")
            choice = input(f"  {name} さんの番号を入力してください: ").strip()
            try:
                result[name] = matches[int(choice) - 1]["id"]
            except (ValueError, IndexError):
                result[name] = None

    print("\n以下の対応で突合を進めます:")
    for name, uid in result.items():
        print(f"  {name} → {uid or '未取得'}")
    confirm = input("よろしいですか？ [y/N]: ").strip().lower()
    if confirm != "y":
        print("中断しました。.env の INTERN_NAMES を確認してください。")
        sys.exit(0)

    return result


# ── バクラク: メンバーID自動取得 ────────────────────────────────────────────────
def discover_members(page, slack_id_map):
    """
    /manager/daily_works にアクセスし、メンバー名をクリックして
    各メンバーのバクラクIDを自動取得する。
    Returns: [{"name": "福田", "bakuraku_id": "01KMY...", "slack_id": "U083..."}]
    """
    print("[メンバー探索] /manager/daily_works へアクセス...")
    try:
        page.goto(MEMBERS_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        pass
    time.sleep(3)

    members = []
    for name, slack_id in slack_id_map.items():
        try:
            el = page.locator(f"text={name}").first
            if not el:
                continue
            el.click()
            time.sleep(2)
            url = page.url
            m = re.search(r"/manager/daily_works/([^?/]+)", url)
            if m:
                bakuraku_id = m.group(1)
                members.append({
                    "name": name,
                    "bakuraku_id": bakuraku_id,
                    "slack_id": slack_id,
                })
                print(f"  ✅ {name} → {bakuraku_id}")
            page.go_back()
            time.sleep(2)
        except Exception as e:
            print(f"  ⚠️  {name}: メンバーが見つかりません（{e}）")

    if not members:
        print("  ⚠️  メンバーが0件。URLパターンからIDを直接取得を試みます...")
        html = page.content()
        ulid_re = re.compile(r"/manager/daily_works/([A-Z0-9]{26})")
        found = ulid_re.findall(html)
        for uid in set(found):
            members.append({"name": "不明", "bakuraku_id": uid, "slack_id": None})
            print(f"  HTML抽出: {uid}")

    return members


# ── バクラク: 月次出退勤テーブル取得 ───────────────────────────────────────────
def scrape_member_attendance(page, member_id, year_month):
    """
    /manager/daily_works/{id}?yearMonth=YYYY-MM から出退勤データを取得。
    Returns: {date_str: {"in": "HH:MM"|None, "out": "HH:MM"|None}}
    """
    url = f"{BAKURAKU_BASE}/manager/daily_works/{member_id}?yearMonth={year_month}"
    print(f"  バクラク取得: {url}")
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        pass
    time.sleep(3)

    result = {}
    year, month = map(int, year_month.split("-"))

    # テーブル行から取得を試みる
    rows = page.query_selector_all("tr")
    if rows:
        for row in rows:
            cells = row.query_selector_all("td")
            texts = [c.inner_text().strip() for c in cells]
            date_str = _extract_date_from_texts(texts, year, month)
            if not date_str:
                continue
            times = _extract_times_from_texts(texts)
            bk_in = times[0] if times else None
            bk_out = _pick_out_time(times)
            result[date_str] = {"in": bk_in, "out": bk_out}

    # テーブル行から取得できなかった場合はbody textをパース
    if not result:
        body = page.inner_text("body")
        result = _parse_body_text(body, year, month)

    print(f"  → {len(result)}日分取得")
    return result


def _extract_date_from_texts(texts, year, month):
    full = " ".join(texts)
    patterns = [
        (re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"),
         lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
        (re.compile(r"(\d{1,2})月(\d{1,2})日"),
         lambda m: (year, int(m.group(1)), int(m.group(2)))),
        (re.compile(r"(\d{1,2})/(\d{1,2})"),
         lambda m: (year, int(m.group(1)), int(m.group(2)))),
    ]
    for pat, extractor in patterns:
        m = pat.search(full)
        if m:
            y, mo, d = extractor(m)
            if mo == month and 1 <= d <= 31:
                return f"{y}-{mo:02d}-{d:02d}"
    return None


def _extract_times_from_texts(texts):
    time_re = re.compile(r"(\d{1,2}):(\d{2})")
    result = []
    for t in texts:
        m = time_re.fullmatch(t.strip())
        if m:
            result.append(f"{int(m.group(1)):02d}:{m.group(2)}")
    return result


def _raw_min(t):
    """HH:MM を正規化なしで分数に変換（24:17 → 1457 のまま）"""
    if not t:
        return None
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _pick_out_time(times):
    """
    バクラクの退勤時刻を時刻リストから選ぶ。
    バクラクは翌日の時刻を 24:xx/25:xx と表記するため、
    真の退勤は raw_min >= 出勤 raw_min になる。
    times[1:] を順に見て、出勤以上の最初の値を退勤とする。
    出勤以上の値がなければ退勤なし（勤務時間・累計時間のみ）と判断して None を返す。
    """
    if not times:
        return None
    in_m = _raw_min(times[0])
    if in_m is None:
        return None
    for t in times[1:]:
        out_m = _raw_min(t)
        if out_m is not None and out_m >= in_m:
            return t
    return None


def _parse_body_text(text, year, month):
    """body テキストから日付+時刻パターンを行単位で抽出（フォールバック）"""
    result = {}
    date_re = re.compile(
        r"(?:(\d{4})[-/](\d{1,2})[-/](\d{1,2})|(\d{1,2})月(\d{1,2})日|(\d{1,2})/(\d{1,2}))"
    )
    time_re = re.compile(r"\b(\d{1,2}):(\d{2})\b")

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        dm = date_re.search(line)
        if not dm:
            continue

        if dm.group(1):
            y, mo, d = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        elif dm.group(4):
            y, mo, d = year, int(dm.group(4)), int(dm.group(5))
        else:
            mo, d = int(dm.group(6)), int(dm.group(7))
            y = year

        if mo != month:
            continue
        date_str = f"{y}-{mo:02d}-{d:02d}"
        times = time_re.findall(line)
        if len(times) >= 2:
            result[date_str] = {
                "in":  f"{int(times[0][0]):02d}:{times[0][1]}",
                "out": f"{int(times[1][0]):02d}:{times[1][1]}",
            }
        elif len(times) == 1:
            result[date_str] = {
                "in":  f"{int(times[0][0]):02d}:{times[0][1]}",
                "out": None,
            }
    return result


# ── Slack 打刻取得 ──────────────────────────────────────────────────────────────
def fetch_slack_kintai(year, month, target_slack_ids):
    """
    #team-美容マーケ から指定月の打刻を取得。
    Returns: {slack_id: {date_str: {"in": "HH:MM"|None, "out": "HH:MM"|None}}}
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        print("  ❌ SLACK_BOT_TOKEN が未設定です")
        print("     customer-dashboard/.env または kintai-check/.env に設定してください")
        sys.exit(1)

    try:
        from slack_sdk import WebClient
    except ImportError:
        print("  ❌ slack_sdk が未インストールです")
        print("     ../customer-dashboard/.venv/bin/pip install slack-sdk")
        sys.exit(1)

    client = WebClient(token=token)

    _, last_day = calendar.monthrange(year, month)
    oldest = datetime(year, month, 1,       0,  0,  0, tzinfo=JST).timestamp()
    latest = datetime(year, month, last_day, 23, 59, 59, tzinfo=JST).timestamp()

    # チャンネルID取得
    channel_id = None
    cursor = None
    while True:
        resp = client.conversations_list(
            exclude_archived=True,
            types="public_channel,private_channel",
            limit=200,
            cursor=cursor,
        )
        for ch in resp["channels"]:
            if ch["name"] == PUNCH_CHANNEL_NAME:
                channel_id = ch["id"]
                break
        if channel_id:
            break
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    if not channel_id:
        print(f"  ❌ #{PUNCH_CHANNEL_NAME} が見つかりません（Bot参加確認）")
        sys.exit(1)

    # メッセージ取得
    messages, cursor = [], None
    while True:
        resp = client.conversations_history(
            channel=channel_id,
            oldest=str(oldest),
            latest=str(latest),
            limit=200,
            cursor=cursor,
        )
        messages.extend(resp.get("messages", []))
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    print(f"  Slack取得: {len(messages)}件（#{PUNCH_CHANNEL_NAME}）")

    raw = defaultdict(lambda: defaultdict(lambda: {
        "in": None, "out": None, "_break_buf": None
    }))

    for msg in sorted(messages, key=lambda m: float(m["ts"])):
        uid = msg.get("user", "")
        if uid not in target_slack_ids:
            continue
        text = msg.get("text", "")
        dt   = datetime.fromtimestamp(float(msg["ts"]), tz=JST)
        hhmm = dt.strftime("%H:%M")

        if RE_OUT.search(text) and dt.hour < 6:
            prev = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
            raw[uid][prev]["out"] = hhmm
            continue

        date = dt.strftime("%Y-%m-%d")
        day  = raw[uid][date]

        if RE_BREAK.search(text):
            day["_break_buf"] = hhmm
        elif RE_BACK.search(text):
            day["_break_buf"] = None
        elif RE_IN.search(text) and day["in"] is None:
            day["in"] = hhmm
        elif RE_OUT.search(text):
            day["out"] = hhmm

    result = {}
    for uid, days in raw.items():
        result[uid] = {}
        for date, day in days.items():
            result[uid][date] = {"in": day["in"], "out": day["out"]}
    return result


# ── 突合 ────────────────────────────────────────────────────────────────────────
def _time_to_min(t):
    if not t:
        return None
    h, m = map(int, t.split(":"))
    # バクラクは深夜退勤を 24:xx (= 翌0:xx) / 25:xx (= 翌1:xx) と表記する
    # Slack は 00:xx / 01:xx と表記するため、比較時に正規化する
    if h >= 24:
        h -= 24
    return h * 60 + m


def _reason(bk_in, bk_out, sl_in, sl_out, status):
    """不一致・アラートの理由テキストを生成する。"""
    parts = []
    if status == "slack_only_missing":
        parts.append("Slack打刻なし（バクラクのみ記録）")
    elif status == "bk_only_missing":
        parts.append("バクラク記録なし（Slackのみ打刻）")
    elif status == "mismatch":
        bk_in_m  = _time_to_min(bk_in)
        sl_in_m  = _time_to_min(sl_in)
        bk_out_m = _time_to_min(bk_out)
        sl_out_m = _time_to_min(sl_out)

        if bk_in_m is not None and sl_in_m is not None:
            d = abs(bk_in_m - sl_in_m)
            if d > TOLERANCE_MIN:
                parts.append(f"出勤{d}分差（バクラク{bk_in}・Slack{sl_in}）")

        if bk_out_m is not None and sl_out_m is not None:
            d = abs(bk_out_m - sl_out_m)
            if d > TOLERANCE_MIN:
                parts.append(f"退勤{d}分差（バクラク{bk_out}・Slack{sl_out}）")
        elif bk_out and not sl_out:
            parts.append("Slack退勤打刻なし")
        elif sl_out and not bk_out:
            parts.append("バクラク退勤記録なし")

        if not parts:
            parts.append("時刻差が許容範囲超過")
    return "・".join(parts) if parts else ""


def compare_attendance(member, bk_data, slack_data):
    """
    Returns: [{"date", "bk_in", "bk_out", "sl_in", "sl_out", "status", "reason"}]
    status: "ok" | "mismatch" | "slack_only_missing" | "bk_only_missing"
    """
    uid = member["slack_id"]
    sl_days = slack_data.get(uid, {}) if uid else {}
    all_dates = sorted(set(list(bk_data.keys()) + list(sl_days.keys())))

    rows = []
    for date in all_dates:
        bk = bk_data.get(date, {})
        sl = sl_days.get(date, {})
        bk_in, bk_out = bk.get("in"), bk.get("out")
        sl_in, sl_out = sl.get("in"), sl.get("out")

        if not bk_in and not sl_in:
            continue  # 休日

        if bk_in and not sl_in:
            status = "slack_only_missing"
        elif sl_in and not bk_in:
            status = "bk_only_missing"
        else:
            in_diff  = abs((_time_to_min(bk_in)  or 0) - (_time_to_min(sl_in)  or 0))
            out_diff = abs((_time_to_min(bk_out) or 0) - (_time_to_min(sl_out) or 0)) if bk_out and sl_out else 0
            status = "ok" if in_diff <= TOLERANCE_MIN and out_diff <= TOLERANCE_MIN else "mismatch"

        rows.append({
            "date": date,
            "bk_in": bk_in, "bk_out": bk_out,
            "sl_in": sl_in, "sl_out": sl_out,
            "status": status,
            "reason": _reason(bk_in, bk_out, sl_in, sl_out, status),
        })
    return rows


# ── HTML レポート生成 ────────────────────────────────────────────────────────────
def build_html(year_month, member_results):
    """
    member_results: [{"member": {...}, "rows": [...], "has_mismatch": bool}]
    """
    year, month = year_month.split("-")
    total_members = len(member_results)
    ok_members    = sum(1 for r in member_results if not r["has_mismatch"])
    ng_members    = total_members - ok_members

    status_badge = (
        '<span style="background:#22c55e;color:#fff;padding:4px 12px;border-radius:20px;font-weight:bold;">✅ 全一致</span>'
        if ng_members == 0 else
        f'<span style="background:#ef4444;color:#fff;padding:4px 12px;border-radius:20px;font-weight:bold;">❌ 不一致 {ng_members}名</span>'
    )

    member_sections = ""
    for r in member_results:
        name = r["member"]["name"]
        rows = r["rows"]
        ok_count  = sum(1 for row in rows if row["status"] == "ok")
        ng_count  = len(rows) - ok_count

        table_rows = ""
        for row in rows:
            st = row["status"]
            if st == "ok":
                bg, icon = "#f0fdf4", "✅"
            elif st == "mismatch":
                bg, icon = "#fef2f2", "❌"
            else:
                bg, icon = "#fffbeb", "⚠️"

            reason_cell = (
                f'<td style="padding:6px 10px;font-size:0.82rem;color:#92400e;">{row["reason"]}</td>'
                if row["reason"] else
                '<td style="padding:6px 10px;"></td>'
            )
            table_rows += f"""
            <tr style="background:{bg};">
              <td style="padding:6px 10px;">{row['date']}</td>
              <td style="padding:6px 10px;font-family:monospace;">{row['bk_in'] or '—'}</td>
              <td style="padding:6px 10px;font-family:monospace;">{row['bk_out'] or '—'}</td>
              <td style="padding:6px 10px;font-family:monospace;">{row['sl_in'] or '—'}</td>
              <td style="padding:6px 10px;font-family:monospace;">{row['sl_out'] or '—'}</td>
              <td style="padding:6px 10px;text-align:center;">{icon}</td>
              {reason_cell}
            </tr>"""

        member_sections += f"""
        <div style="margin-bottom:32px;">
          <h2 style="font-size:1.1rem;margin-bottom:8px;color:#1e293b;">
            {name}
            <span style="font-size:0.85rem;font-weight:normal;color:#64748b;margin-left:8px;">
              {ok_count}日一致 / {ng_count}日不一致
            </span>
          </h2>
          <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
              <thead>
                <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;">
                  <th style="padding:8px 10px;text-align:left;">日付</th>
                  <th style="padding:8px 10px;text-align:left;">バクラク出勤</th>
                  <th style="padding:8px 10px;text-align:left;">バクラク退勤</th>
                  <th style="padding:8px 10px;text-align:left;">Slack出勤</th>
                  <th style="padding:8px 10px;text-align:left;">Slack退勤</th>
                  <th style="padding:8px 10px;text-align:center;">判定</th>
                  <th style="padding:8px 10px;text-align:left;">備考</th>
                </tr>
              </thead>
              <tbody>{table_rows}</tbody>
            </table>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>勤怠突合レポート {year_month}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 24px; color: #1e293b; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .meta {{ color: #64748b; font-size: 0.85rem; margin-bottom: 24px; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap; }}
  .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 24px; min-width: 120px; }}
  .card-num {{ font-size: 2rem; font-weight: bold; }}
  .card-label {{ font-size: 0.8rem; color: #64748b; }}
</style>
</head>
<body>
<h1>勤怠突合レポート</h1>
<div class="meta">{year}年{month}月 | 許容誤差 ±{TOLERANCE_MIN}分 | バクラク vs Slack(#{PUNCH_CHANNEL_NAME})</div>
<div style="margin-bottom:20px;">{status_badge}</div>
<div class="summary">
  <div class="card"><div class="card-num">{total_members}</div><div class="card-label">対象メンバー</div></div>
  <div class="card"><div class="card-num" style="color:#22c55e;">{ok_members}</div><div class="card-label">全一致</div></div>
  <div class="card"><div class="card-num" style="color:#ef4444;">{ng_members}</div><div class="card-label">不一致あり</div></div>
</div>
{member_sections}
</body>
</html>"""


# ── メイン処理 ──────────────────────────────────────────────────────────────────
def main():
    year, month, year_month = _parse_args()
    print(f"\n{'=' * 60}")
    print(f"  [勤怠突合] {year_month} 開始")
    print(f"{'=' * 60}")

    # ① INTERN_NAMES から Slack ID を自動取得
    if not INTERN_NAMES:
        print("❌ .env に INTERN_NAMES が未設定です")
        print("   例: INTERN_NAMES=福田,上野")
        sys.exit(1)
    slack_id_map = resolve_slack_ids(INTERN_NAMES)

    # ② バクラクからメンバー一覧 + 月次データ取得
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            slow_mo=300,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.new_page()

        # ログイン確認
        try:
            page.goto(MEMBERS_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass
        time.sleep(2)

        cur = page.url
        if any(kw in cur for kw in ["sign_in", "login", "google", "accounts"]):
            print("  未ログイン → ブラウザでGoogleアカウントにログインしてください")
            for i in range(600):
                time.sleep(1)
                try:
                    body = page.inner_text("body")
                    if any(kw in body for kw in ["出勤簿", "承認する", "打刻"]):
                        print("  ✅ ログイン検知")
                        break
                except Exception:
                    pass
            else:
                ctx.close()
                sys.exit(1)
        else:
            print(f"  ✅ ログイン済み（プロファイルより自動復元）")

        # メンバーID自動取得
        print("\n[1/3] メンバーIDを自動取得中...")
        members = discover_members(page, slack_id_map)
        if not members:
            print("  ❌ メンバーが見つかりませんでした")
            ctx.close()
            sys.exit(1)

        # 各メンバーの月次出退勤取得
        print(f"\n[2/3] バクラク月次出退勤を取得中（{year_month}）...")
        bakuraku_data = {}
        for member in members:
            bk = scrape_member_attendance(page, member["bakuraku_id"], year_month)
            bakuraku_data[member["name"]] = bk

        ctx.close()

    # ③ Slack打刻取得
    print(f"\n[3/3] Slack打刻データを取得中（#{PUNCH_CHANNEL_NAME} {year_month}）...")
    target_ids = [m["slack_id"] for m in members if m.get("slack_id")]
    slack_data = fetch_slack_kintai(year, month, set(target_ids))

    # ④ 突合
    member_results = []
    has_any_mismatch = False
    for member in members:
        bk = bakuraku_data.get(member["name"], {})
        rows = compare_attendance(member, bk, slack_data)
        has_mismatch = any(r["status"] != "ok" for r in rows)
        if has_mismatch:
            has_any_mismatch = True
        member_results.append({
            "member": member,
            "rows": rows,
            "has_mismatch": has_mismatch,
        })

    # ⑤ HTML生成
    html = build_html(year_month, member_results)
    html_path = OUT_DIR / f"reconcile_{year_month}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"\n  📄 レポート: file://{html_path}")

    # ⑥ 結果表示
    print(f"\n{'=' * 60}")
    if not has_any_mismatch:
        print("  ✅ 全一致 → 月次申請を自動承認します")
        print(f"{'=' * 60}")
        sys.exit(0)
    else:
        print("  ❌ 不一致あり → HTMLを確認して「問題なし」と返答してください")
        print(f"  file://{html_path}")
        print(f"{'=' * 60}")
        sys.exit(1)


if __name__ == "__main__":
    main()
