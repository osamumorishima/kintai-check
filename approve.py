#!/usr/bin/env python3
"""
approve.py  v2.1
バクラク申請自動承認スクリプト（Step1: 森島承認）
セッション永続化: launch_persistent_context でブラウザプロファイルをローカル保存

実行:
  cd /Users/info/Documents/projects/kintai-check
  ../customer-dashboard/.venv/bin/python3 approve.py

初回のみ: ブラウザが開くのでGoogleアカウントでログイン → 以降は自動
"""
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PROFILE_DIR   = Path(__file__).parent / "browser_profile"
PROFILE_DIR.mkdir(exist_ok=True)

OUT_DIR       = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)
BAKURAKU_BASE = "https://attendance.layerx.jp"
DAILY_URL     = f"{BAKURAKU_BASE}/workflow_instances/assigned/daily"
MONTHLY_URL   = f"{BAKURAKU_BASE}/workflow_instances/assigned/monthly"


def wait_for_login(page):
    """ログイン完了をサイドバー要素の出現で検知する（最大10分）。"""
    print("  ブラウザでGoogleアカウントにログインしてください...")
    print("  ログイン完了を自動検知します（最大10分待機）...")
    for i in range(600):
        time.sleep(1)
        try:
            body = page.inner_text("body")
            if any(kw in body for kw in ["出勤簿", "承認する", "打刻", "申請履歴"]):
                print("  ✅ ログイン検知: 認証済み画面を確認")
                return True
        except Exception:
            pass
        if i % 15 == 0 and i > 0:
            print(f"  待機中... ({i}秒経過)")
    print("  ❌ ログインタイムアウト（10分経過）")
    return False


def approve_all(page, target_url, label):
    """承認待ち申請を全選択→一括承認する。label は「日次」or「月次」。"""
    print(f"\n  [{label}] {target_url}")
    round_num = 0

    while round_num < 20:
        round_num += 1
        try:
            page.goto(target_url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass
        time.sleep(3)

        page.screenshot(path=str(OUT_DIR / f"{label}_round_{round_num:02d}_before.png"))

        # 「承認待ち」タブがあればクリック
        try:
            tab = page.query_selector('button:has-text("承認待ち"), [role="tab"]:has-text("承認待ち")')
            if tab and tab.is_visible():
                tab.click()
                time.sleep(2)
        except Exception:
            pass

        body = page.inner_text("body")
        if "承認待ち" not in body and "進行中" not in body:
            print(f"  [{label}] 承認待ちの申請なし → スキップ")
            return 0

        # ヘッダーCBで全選択、なければ個別にチェック
        header_cb = None
        for sel in [
            'thead input[type="checkbox"]',
            'th input[type="checkbox"]',
            'input[type="checkbox"][aria-label*="全"]',
            'input[type="checkbox"]:first-of-type',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    header_cb = el
                    break
            except Exception:
                pass

        if header_cb is None:
            cbs = page.query_selector_all('tbody input[type="checkbox"], tr input[type="checkbox"]')
            checked = 0
            for cb in cbs:
                try:
                    if cb.is_visible() and not cb.is_checked():
                        cb.click()
                        checked += 1
                        time.sleep(0.3)
                except Exception:
                    pass
            if checked == 0:
                print(f"  [{label}] 承認待ちの申請がなくなりました → 完了")
                return round_num - 1
            print(f"  [{label}] {checked}件を個別選択")
        else:
            header_cb.click()
            time.sleep(1)
            print(f"  [{label}] 全件を一括選択")

        page.screenshot(path=str(OUT_DIR / f"{label}_round_{round_num:02d}_selected.png"))

        # 「一括承認する」ボタン
        bulk_btn = None
        for sel in [
            'button:has-text("一括承認する")',
            'button:has-text("一括承認")',
            'button:has-text("承認する")',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    bulk_btn = el
                    break
            except Exception:
                pass

        if bulk_btn is None:
            print(f"  [{label}] 「一括承認する」ボタンが見つかりません → {OUT_DIR}/ を確認")
            break

        bulk_btn.click()
        time.sleep(2)
        page.screenshot(path=str(OUT_DIR / f"{label}_round_{round_num:02d}_dialog.png"))

        # 確認ダイアログ「一括承認」（innerText完全一致）
        confirmed = False
        time.sleep(1)
        try:
            for btn in page.query_selector_all("button"):
                try:
                    if not btn.is_visible():
                        continue
                    if btn.inner_text().strip() == "一括承認":
                        btn.click()
                        confirmed = True
                        print(f"  [{label}] 確認ダイアログ → 「一括承認」クリック")
                        time.sleep(3)
                        break
                except Exception:
                    pass
        except Exception as e:
            print(f"  [{label}] ダイアログボタン探索エラー: {e}")

        if not confirmed:
            print(f"  [{label}] 確認ダイアログが見つかりません → 処理を中断")
            page.screenshot(path=str(OUT_DIR / f"{label}_round_{round_num:02d}_no_dialog.png"))
            break

        time.sleep(2)
        page.screenshot(path=str(OUT_DIR / f"{label}_round_{round_num:02d}_after.png"))

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
        body_after = page.inner_text("body")
        if "承認待ち" not in body_after and "進行中" not in body_after:
            print(f"  [{label}] ✅ ラウンド{round_num}: 全件承認完了")
            return round_num
        else:
            print(f"  [{label}] ラウンド{round_num}: 一部承認完了、残件確認中...")

    return 0


# ── メイン処理 ─────────────────────────────────────────────────────────────────
with sync_playwright() as p:
    print(f"[1/3] ブラウザプロファイル読み込み中: {PROFILE_DIR}")
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=False,
        slow_mo=300,
        viewport={"width": 1440, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.new_page()

    try:
        page.goto(DAILY_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        pass
    time.sleep(2)

    cur = page.url
    if any(kw in cur for kw in ["sign_in", "login", "google", "accounts"]):
        print("  未ログイン → ブラウザでGoogleアカウントにログインしてください")
        if not wait_for_login(page):
            ctx.close()
            sys.exit(1)
    else:
        print(f"  ✅ ログイン済み（プロファイルより自動復元）: {page.url}")

    print("\n[2/3] 日次申請を承認中...")
    daily_count = approve_all(page, DAILY_URL, "日次")

    print("\n[3/3] 月次申請を承認中...")
    monthly_count = approve_all(page, MONTHLY_URL, "月次")

    page.screenshot(path=str(OUT_DIR / "final.png"))
    ctx.close()

print(f"\n{'=' * 50}")
print(f"  日次承認: {'完了' if daily_count > 0 else 'なし（0件）'}")
print(f"  月次承認: {'完了' if monthly_count > 0 else 'なし（0件）'}")
print(f"{'=' * 50}")
