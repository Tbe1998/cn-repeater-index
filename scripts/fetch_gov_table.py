"""抓取与解析：政府公开信息表（html_table 类型源）。

配置在 sources.json 的 table_header 里给出表头，按表头名映射字段，避免依赖列序。
"""
from __future__ import annotations

import html
import re

from common import parse_digital_params, parse_tone

MUNICIPALITIES = {"北京", "上海", "天津", "重庆"}

# 表头名 -> 内部字段
HEADER_MAP = {
    "台站所属区域": "location",
    "区域": "location",
    "台址": "location",
    "上行中心频率（MHz）": "uplink_mhz",
    "上行中心频率(MHz)": "uplink_mhz",
    "上行频率": "uplink_mhz",
    "下行中心频率（MHz）": "downlink_mhz",
    "下行中心频率(MHz)": "downlink_mhz",
    "下行频率": "downlink_mhz",
    "调制方式": "modulation",
    "亚音频（Hz）": "tone",
    "亚音频(Hz)": "tone",
    "亚音": "tone",
    "呼号": "call",
    "台站呼号": "call",
    "执照编号": "license_no",
}


def _cells(row_html: str) -> list[str]:
    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S | re.I)
    out = []
    for c in cells:
        txt = html.unescape(re.sub(r"<[^>]+>", " ", c))
        out.append(re.sub(r"\s+", " ", txt).strip())
    return out


def _float(s: str):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _split_location(loc: str) -> tuple[str, str, str]:
    """'深圳市福田区' -> (广东?, 深圳市, 福田区)。省份由调用方补，这里只拆市/区。"""
    loc = re.sub(r"\s+", "", loc or "")
    m = re.match(r"^(.{2,4}?(?:市|地区|自治州|盟))(.+)$", loc)
    if m:
        return m.group(1), m.group(2)
    return loc, ""


def parse(page: str, source: dict) -> list[dict]:
    header = source.get("table_header") or []
    tables = re.findall(r"<table[^>]*>.*?</table>", page, flags=re.S | re.I)
    out: list[dict] = []
    for tbl in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, flags=re.S | re.I)
        if not rows:
            continue
        first = _cells(rows[0])
        if not any(h in first for h in header):
            continue
        colmap = {}
        for i, name in enumerate(first):
            key = HEADER_MAP.get(name)
            if key:
                colmap[key] = i
        if "call" not in colmap or "uplink_mhz" not in colmap:
            continue
        for r in rows[1:]:
            cells = _cells(r)
            if len(cells) < len(first) - 1:
                continue
            get = lambda k: cells[colmap[k]] if k in colmap and colmap[k] < len(cells) else ""
            up, down = _float(get("uplink_mhz")), _float(get("downlink_mhz"))
            call = re.sub(r"\s+", "", get("call"))
            if not call or not up or not down:
                continue
            modulation = get("modulation")
            tone = get("tone")
            mode_raw = "，".join(x for x in (modulation, (f"CTCSS:{tone}Hz" if tone else "")) if x)
            city, district = _split_location(get("location"))
            ctcss, dcs = parse_tone(f"CTCSS:{tone}Hz" if tone else modulation)
            cc, ts = parse_digital_params(modulation)
            out.append(
                {
                    "call": call,
                    "province": "",
                    "location": get("location"),
                    "city": city,
                    "district": district,
                    "address": "",
                    "uplink_mhz": up,
                    "downlink_mhz": down,
                    "mode_raw": mode_raw,
                    "ctcss_hz": ctcss,
                    "dcs": dcs,
                    "color_code": cc,
                    "timeslot": ts,
                    "license_no": get("license_no"),
                    "status_raw": "",
                    "source_id": source["id"],
                    "raw_line": " | ".join(cells),
                }
            )
    return out
