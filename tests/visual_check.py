"""用真实 Chromium 核对手机端页面并截图（此前缺的视觉核对环节）。

先起服务再跑：python3 server.py --port 8787 &
"""
import os
from playwright.sync_api import sync_playwright

URL = os.environ.get("TARGET_URL", "http://127.0.0.1:8787/")
OUT = os.environ.get("SHOT_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist"))
os.makedirs(OUT, exist_ok=True)
HZ = {"latitude": 30.2741, "longitude": 120.1551}

with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
        locale="zh-CN",
        geolocation=HZ,
        permissions=["geolocation"],
    )
    pg = ctx.new_page()
    errs = []
    pg.on("console", lambda m: errs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))

    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_selector(".card", timeout=8000)
    pg.click("#loc")
    pg.wait_for_timeout(1500)

    cards = pg.locator(".card").count()
    geo = pg.inner_text("#geo")
    cnt = pg.inner_text("#cnt")
    first = pg.locator(".card").first.inner_text().replace("\n", " | ")

    # 展开首条，检查详情区
    pg.locator(".card").first.click()
    pg.wait_for_timeout(300)
    det_visible = pg.locator(".card").first.locator(".det").is_visible()

    pg.screenshot(path=f"{OUT}/shot-1-nearby.png", full_page=False)
    pg.screenshot(path=f"{OUT}/shot-2-full.png", full_page=True)

    # 过滤 + 搜索
    pg.locator('.chip[data-v="2m"]').click()
    pg.wait_for_timeout(300)
    n2m = pg.inner_text("#cnt")
    pg.screenshot(path=f"{OUT}/shot-3-2m.png")

    print(f"卡片数: {cards}")
    print(f"计数: {cnt}")
    print(f"定位栏: {geo}")
    print(f"首条: {first}")
    print(f"详情展开: {det_visible}")
    print(f"2m 过滤后计数: {n2m}")
    print(f"控制台错误/警告: {errs[:5] if errs else '无'}")

    b.close()
