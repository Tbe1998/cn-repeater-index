"""抓取与解析：CRAC 业余中继台信息公布页（html_lines 类型源）。

原文格式（每行一条）：
  地区：呼号，上行/下行MHz，工作模式及主要参数
  地区 可能是 "北京" 或 "浙江，温州鹿城" 这类 省[，市/区] 组合
"""
from __future__ import annotations

import html
import os
import re
import urllib.request

from common import parse_digital_params, parse_pair, parse_tone

UA = "Mozilla/5.0 (compatible; CNRepeaterIndex/0.1; +https://www.crac.org.cn/)"
RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")

MUNICIPALITIES = {"北京", "上海", "天津", "重庆"}

LINE_RE = re.compile(r"^\s*(?P<loc>[^：:]{2,40})[：:]\s*(?P<body>.+)$")


def fetch(url: str, cache_name: str) -> str:
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, cache_name)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    text = data.decode("utf-8", errors="replace")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def _lines(page: str) -> list[str]:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", page))
    return [l.strip() for l in text.split("\n") if l.strip()]


def parse(page: str, source_id: str) -> list[dict]:
    out: list[dict] = []
    for line in _lines(page):
        m = LINE_RE.match(line)
        if not m:
            continue
        body = m.group("body")
        if "/" not in body:          # 频率对是硬性条件，没有就跳过
            continue
        loc_parts = [p.strip() for p in re.split(r"[，,、]", m.group("loc")) if p.strip()]
        if not loc_parts:
            continue
        province = loc_parts[0]
        location = loc_parts[1] if len(loc_parts) > 1 else ""

        fields = [f.strip() for f in re.split(r"[，,]", body) if f.strip()]
        if not fields:
            continue
        call = fields[0].replace(" ", "")
        rest = fields[1:]
        up = down = None
        freq_field_idx = None
        for i, f in enumerate(rest):
            u, d = parse_pair(f)
            if u and d:
                up, down, freq_field_idx = u, d, i
                break
        if up is None:
            continue
        mode_raw = "，".join(rest[freq_field_idx + 1:]) if freq_field_idx is not None else ""
        # 有些行把模式参数和频率写在同一字段，例如 "CTCSS：88.5Hz/DMR 彩色码1 时隙1"
        same_field = rest[freq_field_idx]
        same_field_tail = re.sub(r"[\d.]+\s*(?:MHz)?\s*[/／]\s*[\d.]+\s*(?:MHz)?", "", same_field, flags=re.I)
        mode_raw = (same_field_tail.strip("，, ") + "，" + mode_raw).strip("，")

        ctcss, dcs = parse_tone(mode_raw)
        cc, ts = parse_digital_params(mode_raw)
        out.append(
            {
                "call": call,
                "province": province,
                "location": location,
                "address": "",
                "uplink_mhz": up,
                "downlink_mhz": down,
                "mode_raw": mode_raw,
                "ctcss_hz": ctcss,
                "dcs": dcs,
                "color_code": cc,
                "timeslot": ts,
                "license_no": "",
                "status_raw": mode_raw,
                "source_id": source_id,
                "raw_line": line,
            }
        )
    return out
