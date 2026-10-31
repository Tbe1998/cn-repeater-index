#!/usr/bin/env python3
"""中继台速查 —— 零依赖服务端（标准库）。

  python3 server.py                 # 默认 127.0.0.1:8787
  python3 server.py --host 0.0.0.0 --port 8787

接口：
  GET /api/meta                       数据源、构建时间、条数
  GET /api/repeaters?lat=&lon=&radius=&band=&mode=&q=&limit=
  GET /api/sources                    数据源与免责声明
  GET /api/export/chirp.csv?...       同一套过滤参数，返回 CHIRP 可直接导入的 CSV
  GET /                               手机端 PWA 页面（web/ 目录静态托管）
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
from common import bearing_deg, cardinal_zh, chirp_row, haversine_km  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "db", "repeaters.sqlite")
WEB_DIR = os.path.join(ROOT, "web")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def meta_payload(conn: sqlite3.Connection) -> dict:
    m = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    sources = [dict(r) for r in conn.execute("SELECT * FROM sources ORDER BY page_date DESC")]
    total = conn.execute("SELECT COUNT(*) FROM repeaters").fetchone()[0]
    return {
        "generated_at": m.get("generated_at"),
        "records": total,
        "sources": sources,
        "disclaimer": "数据由公开渠道抓取，仅供查频参考；实际使用以当地无线电管理机构最新公示与中继台实际参数为准。",
        "coordinate_crs": "GCJ-02（行政区中心点）",
    }


def query(conn: sqlite3.Connection, qp: dict) -> list[dict]:
    sql = "SELECT * FROM repeaters WHERE 1=1"
    args: list = []
    lat, lon = qp.get("lat"), qp.get("lon")
    if qp.get("band") and qp["band"] != "all":
        sql += " AND band = ?"
        args.append(qp["band"])
    if qp.get("mode") and qp["mode"] != "all":
        sql += " AND mode_class = ?"
        args.append(qp["mode"])
    if qp.get("q"):
        like = f"%{qp['q']}%"
        sql += " AND (call LIKE ? OR province LIKE ? OR city LIKE ? OR district LIKE ? OR mode_raw LIKE ?)"
        args += [like] * 5
    rows = [dict(r) for r in conn.execute(sql, args)]

    # 去重：同 (呼号+频率) 已在 build 阶段按 publish 日期择优，这里只做兜底去重
    seen, uniq = set(), []
    for r in rows:
        key = r["dup_key"]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    if lat and lon:
        try:
            la, lo = float(lat), float(lon)
            withpos = []
            for r in uniq:
                if r["lat"] is None or r["lon"] is None:
                    r["distance_km"] = None
                    withpos.append(r)
                    continue
                r["distance_km"] = round(haversine_km(la, lo, r["lat"], r["lon"]), 2)
                b = bearing_deg(la, lo, r["lat"], r["lon"])
                r["bearing_deg"] = round(b, 1)
                r["bearing_zh"] = cardinal_zh(b)
                withpos.append(r)
            withpos.sort(key=lambda x: (x["distance_km"] is None, x["distance_km"] or 9e9))
            uniq = withpos
            if qp.get("radius"):
                rad_km = float(qp["radius"])
                uniq = [r for r in uniq if r["distance_km"] is not None and r["distance_km"] <= rad_km]
        except ValueError:
            pass
    else:
        uniq.sort(key=lambda r: (r["province"] or "", r["city"] or "", r["call"] or ""))

    if qp.get("limit"):
        uniq = uniq[: int(qp["limit"])]
    return uniq


class Handler(BaseHTTPRequestHandler):
    server_version = "RepeaterIndex/0.1"

    def log_message(self, fmt, *a):  # 安静一点
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _csv(self, rows: list[dict]):
        buf = io.StringIO()
        w = csv.writer(buf)
        from common import CHIRP_HEADER
        w.writerow(CHIRP_HEADER)
        n = 0
        for r in rows:
            try:
                w.writerow(chirp_row(n + 1, r))
                n += 1
            except ValueError:
                continue
        body = ("\ufeff" + buf.getvalue()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="repeaters-chirp.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        qp = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if path.startswith("/api/"):
            if not os.path.exists(DB_PATH):
                return self._json({"error": "数据库不存在，请先运行 python3 scripts/build.py"}, 503)
            conn = db()
            try:
                if path == "/api/meta":
                    return self._json(meta_payload(conn))
                if path == "/api/sources":
                    return self._json([dict(r) for r in conn.execute("SELECT * FROM sources")])
                if path == "/api/repeaters":
                    rows = query(conn, qp)
                    return self._json({"count": len(rows), "repeaters": rows})
                if path == "/api/export/chirp.csv":
                    return self._csv(query(conn, qp))
            finally:
                conn.close()
            return self._json({"error": "not found"}, 404)

        # 静态文件
        if path in ("/", ""):
            path = "/index.html"
        fpath = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not fpath.startswith(WEB_DIR) or not os.path.isfile(fpath):
            self.send_error(404, "not found")
            return
        ext = os.path.splitext(fpath)[1].lower()
        with open(fpath, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    if not os.path.exists(DB_PATH):
        raise SystemExit("数据库不存在，请先运行: python3 scripts/build.py")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"中继台速查已启动: http://{args.host}:{args.port}/")
    print(f"接口示例: http://{args.host}:{args.port}/api/repeaters?lat=30.2741&lon=120.1551&radius=200")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
