#!/usr/bin/env python3
"""把 PWA 打包成一个自包含 HTML 文件：内联 CSS/JS/数据。

用途：设备上装不了任何东西、也不想跑服务端时，双击即用（离线可用，定位照常）。
用法：python3 scripts/make_single_file.py  ->  dist/中继台速查.html
"""
from __future__ import annotations

import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(DIST, "中继台速查.html")


def read(rel: str) -> str:
    with open(os.path.join(WEB, rel), encoding="utf-8") as fh:
        return fh.read()


def main() -> None:
    html = read("index.html")
    css = read("style.css")
    js = read("app.js")
    data = read(os.path.join("data", "repeaters.json"))

    # 数据、样式、脚本全部内联；去掉 manifest 与 service worker（单文件形态不需要）
    html = html.replace('<link rel="manifest" href="manifest.webmanifest">', "")
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}\n</style>")
    # 数据脚本必须排在 app.js 之前（app.js 一加载就渲染）
    inline_js = js.replace(
        "const res = await fetch('data/repeaters.json', { cache: 'no-cache' });\n  state.data = await res.json();",
        "state.data = window.__DATA__;",
    ).replace(
        "if ('serviceWorker' in navigator) {\n  navigator.serviceWorker.register('sw.js').catch(() => {});\n}",
        "/* 单文件模式：不注册 Service Worker */",
    )
    html = html.replace(
        '<script src="app.js"></script>',
        f"<script>window.__DATA__={data};</script>\n<script>\n{inline_js}\n</script>",
    )
    html = html.replace(
        "</title>",
        f"</title>\n<!-- 生成于 {dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='seconds')}，"
        f"由 scripts/make_single_file.py 内联打包 -->",
    )

    os.makedirs(DIST, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)

    payload = json.loads(data)
    size = os.path.getsize(OUT)
    checks = {
        "内联数据条目": len(payload.get("repeaters", [])),
        "含 window.__DATA__": "window.__DATA__" in html,
        "已移除外部 app.js 引用": '<script src="app.js">' not in html,
        "已移除外部 style.css 引用": 'href="style.css"' not in html,
        "文件大小(KB)": round(size / 1024, 1),
    }
    for k, v in checks.items():
        print(f"  {k}: {v}")
    print(f"[done] {OUT}")


if __name__ == "__main__":
    main()
