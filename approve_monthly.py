#!/usr/bin/env python3
"""
approve_monthly.py  v1.0
バクラク月次申請 自動承認（Step3: 突合確認後に実行）

実行:
  ../customer-dashboard/.venv/bin/python3 approve_monthly.py
"""
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PROFILE_DIR   = Path(__file__).parent / "browser_profile"
PROFILE_DIR.mkdir(exist_ok=True)
OUT_DIR       = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)
BAKURAKU_BASE = "https://attendance.layerx.jp"
MONTHLY_URL   = f"{BAKURAKU_BASE}/workflow_instances/assigned/monthly"


def wait_for_login(page):
    print("  ブラウザでGoogleアカウントにログインしてください...")
    for i in range(600):
        time.sleep(1)
        try:
            body = page.inner_text("body")
            if any(kw in body for kw in ["出勤簿", "承認する", "打刻", "申請履歴"]):
                print("  ✅ ログイン検知")
                return True
        except Exception:
            pass
        if i % 15 == 0 and i > 0:
            print(f"  待機中... ({i}秒経過)")
    print("  ❌ ログインタイムアウト")
    return False


def approve_all(page, target_url, label):
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
            print(f"  [{label}] 「一括承認する」ボタンが見つかりません")
            break

        bulk_btn.click()
        time.sleep(2)
        page.screenshot(path=str(OUT_DIR / f"{label}_round_{round_num:02d}_dialog.png"))

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


with sync_playwright() as p:
    print(f"[1/2] ブラウザプロファイル読み込み中: {PROFILE_DIR}")
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=False,
        slow_mo=300,
        viewport={"width": 1440, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.new_page()

    try:
        page.goto(MONTHLY_URL, timeout=30000)
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
        print(f"  ✅ ログイン済み（プロファイルより自動復元）")

    print("\n[2/2] 月次申請を承認中...")
    monthly_count = approve_all(page, MONTHLY_URL, "月次")

    page.screenshot(path=str(OUT_DIR / "monthly_final.png"))
    ctx.close()

print(f"\n{'=' * 50}")
print(f"  月次承認: {'✅ 完了' if monthly_count > 0 else '⬛ なし（0件）'}")
print(f"{'=' * 50}")
