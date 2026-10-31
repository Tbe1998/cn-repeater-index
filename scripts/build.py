"""构建管线：抓取 -> 解析 -> 坐标解析 -> 入库 -> 导出离线数据包。

用法：
  python3 scripts/build.py            # 全量重建
  python3 scripts/build.py --offline  # 只用 data/raw 下的缓存，不联网
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch_crac
import fetch_gov_table
import georesolve
from common import band_of, classify_mode, is_suspended

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "db", "repeaters.sqlite")
WEB_DATA = os.path.join(ROOT, "web", "data", "repeaters.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, name TEXT, publisher TEXT, url TEXT,
  page_date TEXT, citation TEXT, terms TEXT, freshness_warning TEXT,
  fetched_at TEXT, record_count INTEGER
);
CREATE TABLE IF NOT EXISTS repeaters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call TEXT, province TEXT, city TEXT, district TEXT, address TEXT,
  uplink_mhz REAL, downlink_mhz REAL, offset_mhz REAL, band TEXT,
  mode_raw TEXT, mode_class TEXT, submode TEXT,
  ctcss_hz REAL, dcs TEXT, color_code INTEGER, timeslot TEXT,
  status TEXT, license_no TEXT,
  lon REAL, lat REAL, geo_accuracy TEXT, geo_path TEXT,
  source_id TEXT, source_name TEXT, source_url TEXT, source_date TEXT,
  fetched_at TEXT, raw_line TEXT, dup_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_dup ON repeaters(dup_key);
CREATE INDEX IF NOT EXISTS idx_geo ON repeaters(lat, lon);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def load_sources() -> list[dict]:
    with open(os.path.join(ROOT, "sources.json"), encoding="utf-8") as fh:
        return json.load(fh)["sources"]


def collect(src: dict, offline: bool) -> tuple[list[dict], str]:
    fetched_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    if src["kind"] == "html_lines":
        cache = f"{src['id']}.html"
        path = os.path.join(fetch_crac.RAW_DIR, cache)
        if offline:
            page = open(path, encoding="utf-8").read()
        else:
            page = fetch_crac.fetch(src["url"], cache)
        recs = fetch_crac.parse(page, src["id"])
    elif src["kind"] == "html_table":
        cache = f"{src['id']}.html"
        path = os.path.join(fetch_crac.RAW_DIR, cache)
        if offline:
            page = open(path, encoding="utf-8").read()
        else:
            page = fetch_crac.fetch(src["url"], cache)
        recs = fetch_gov_table.parse(page, src)
    else:
        raise SystemExit(f"未知源类型: {src['kind']}")

    default_prov = src.get("province", "")
    for r in recs:
        if not r.get("province"):
            r["province"] = default_prov
        r["source_name"] = src["name"]
        r["source_url"] = src["url"]
        r["source_date"] = src.get("page_date", "")
        r["fetched_at"] = fetched_at
    return recs, fetched_at


def enrich(r: dict) -> dict:
    up, down = r["uplink_mhz"], r["downlink_mhz"]
    cls, sub = classify_mode(r.get("mode_raw", ""))
    r["mode_class"], r["submode"] = cls, sub
    r["offset_mhz"] = round(up - down, 4)
    r["band"] = band_of(down)
    r["status"] = "suspended" if is_suspended(r.get("status_raw", "")) else "active"
    r["dup_key"] = f"{r['call']}|{up:.4f}|{down:.4f}"
    geo = georesolve.resolve(
        r.get("province", ""), r.get("location", ""),
        r.get("city", ""), r.get("district", ""),
    )
    r.update(geo)
    if not r.get("city"):
        parts = [p for p in (r.get("geo_path") or "").split("/") if p]
        # geo_path 形如 省/市/区
        r["city"] = parts[1] if len(parts) > 1 else ""
        r["district"] = parts[2] if len(parts) > 2 else ""
        # 直辖市：geo_path 只有省一级时，城市即该直辖市本身
        if not r["city"] and parts and parts[0][:2] in ("北京", "上海", "天津", "重庆"):
            r["city"] = parts[0]
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    sources = load_sources()
    all_recs: list[dict] = []
    src_meta = []
    for src in sources:
        try:
            recs, fetched_at = collect(src, args.offline)
        except Exception as exc:  # 单源失败不影响整体
            print(f"[warn] 源 {src['id']} 抓取失败: {exc}")
            continue
        recs = [enrich(r) for r in recs]
        all_recs.extend(recs)
        meta = dict(src, fetched_at=fetched_at, record_count=len(recs))
        src_meta.append(meta)
        print(f"[ok] {src['id']}: {len(recs)} 条")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    cols = [
        "call", "province", "city", "district", "address",
        "uplink_mhz", "downlink_mhz", "offset_mhz", "band",
        "mode_raw", "mode_class", "submode", "ctcss_hz", "dcs", "color_code", "timeslot",
        "status", "license_no", "lon", "lat", "geo_accuracy", "geo_path",
        "source_id", "source_name", "source_url", "source_date", "fetched_at", "raw_line", "dup_key",
    ]
    for r in all_recs:
        conn.execute(
            f"INSERT INTO repeaters ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [r.get(c) for c in cols],
        )
    for m in src_meta:
        conn.execute(
            "INSERT INTO sources (id,name,publisher,url,page_date,citation,terms,freshness_warning,fetched_at,record_count)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [m.get("id"), m.get("name"), m.get("publisher"), m.get("url"), m.get("page_date"),
             m.get("citation"), m.get("terms"), m.get("freshness_warning"),
             m.get("fetched_at"), m.get("record_count")],
        )

    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    conn.execute("INSERT INTO meta VALUES ('generated_at', ?)", (generated_at,))
    conn.execute("INSERT INTO meta VALUES ('total_records', ?)", (str(len(all_recs)),))
    conn.commit()

    # 去重：同一 (呼号+频率) 只留最新公布日期的那条，但把来源列表带上
    rows = conn.execute("SELECT * FROM repeaters").fetchall()
    names = [d[0] for d in conn.execute("SELECT * FROM repeaters").description]
    recs = [dict(zip(names, row)) for row in rows]
    best: dict[str, dict] = {}
    for r in recs:
        cur = best.get(r["dup_key"])
        if cur is None or (r["source_date"] or "") > (cur["source_date"] or ""):
            r["also_sources"] = []
            if cur:
                r["also_sources"].append({"source": cur["source_name"], "date": cur["source_date"]})
            best[r["dup_key"]] = r
        else:
            cur.setdefault("also_sources", []).append({"source": r["source_name"], "date": r["source_date"]})

    out_recs = list(best.values())
    payload = {
        "generated_at": generated_at,
        "coordinate_crs": "GCJ-02（阿里云 DataV 行政区中心点），仅到行政区精度",
        "disclaimer": "数据由公开渠道抓取，仅供查频参考；实际使用以当地无线电管理机构最新公示与中继台实际参数为准。",
        "counts": {
            "raw": len(all_recs),
            "unique": len(out_recs),
            "with_coords": sum(1 for r in out_recs if r["lat"] is not None),
            "by_source": {m["id"]: m["record_count"] for m in src_meta},
        },
        "sources": [
            {k: m.get(k) for k in ("id", "name", "publisher", "url", "page_date", "citation", "terms", "freshness_warning", "fetched_at", "record_count")}
            for m in src_meta
        ],
        "repeaters": sorted(
            out_recs,
            key=lambda r: (r["province"] or "", r["city"] or "", r["call"] or "", r["downlink_mhz"] or 0),
        ),
    }
    os.makedirs(os.path.dirname(WEB_DATA), exist_ok=True)
    with open(WEB_DATA, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)

    conn.close()
    print(f"[done] 原始 {len(all_recs)} 条 / 去重后 {len(out_recs)} 条 / 有坐标 {payload['counts']['with_coords']} 条")
    print(f"       DB  : {DB_PATH}")
    print(f"       JSON: {WEB_DATA}")


if __name__ == "__main__":
    main()
