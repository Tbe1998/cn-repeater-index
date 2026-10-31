"""行政区坐标解析：把 "浙江，温州鹿城" 这类文本落到经纬度。

坐标来源：阿里云 DataV 行政区 GeoJSON（areas_v3/bound/{adcode}_full.json）。
注意：该数据集为 **GCJ-02（火星坐标）**，与 WGS84 存在数百米级偏移；
中继台本身只有行政区精度，故本工程只标注精度等级（district/city/province），不做精确门牌。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

UA = "Mozilla/5.0 (compatible; CNRepeaterIndex/0.1)"
BASE = "https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json"
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")

SUFFIX = re.compile(r"(特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|自治州|自治县|地区|省|市|盟|区|县)$")

MUNICIPALITIES = {"北京", "上海", "天津", "重庆"}
MUNI_ADCODE = {"北京": "110000", "天津": "120000", "上海": "310000", "重庆": "500000"}


def _norm(name: str) -> str:
    n = re.sub(r"\s+", "", name or "")
    return SUFFIX.sub("", n) or n


def _load(adcode: str) -> dict:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{adcode}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    req = urllib.request.Request(BASE.format(adcode=adcode), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = json.load(resp)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return data


def _features(doc: dict) -> list[dict]:
    out = []
    for f in doc.get("features", []):
        p = f.get("properties") or {}
        center = p.get("center") or p.get("centroid")
        if not center or len(center) < 2:
            continue
        out.append(
            {
                "adcode": str(p.get("adcode") or ""),
                "name": p.get("name") or "",
                "norm": _norm(p.get("name") or ""),
                "level": p.get("level") or "",
                "lon": float(center[0]),
                "lat": float(center[1]),
                "children_num": p.get("childrenNum", 0),
            }
        )
    return out


def provinces() -> list[dict]:
    return _features(_load("100000"))


def find_child(adcode: str, hint: str) -> dict | None:
    """在 adcode 的子级里按名称提示匹配，最长匹配优先。"""
    if not hint:
        return None
    hint_n = _norm(hint)
    best = None
    for feat in _features(_load(adcode)):
        n = feat["norm"]
        if not n:
            continue
        if hint_n.startswith(n) or n in hint_n or hint_n in n:
            score = len(n)
            if best is None or score > best[0]:
                best = (score, feat)
    return best[1] if best else None


def resolve(province: str, location: str, city_hint: str = "", district_hint: str = "") -> dict:
    """返回 {lon, lat, geo_accuracy, geo_path}。失败时返回空坐标并标注 unknown。"""
    if city_hint or district_hint:  # 已结构化的来源（政府表格）
        province_feat = _find_province(province) if province else None
        adcode = province_feat["adcode"] if province_feat else None
        if adcode:
            city = find_child(adcode, city_hint)
            if city and district_hint:
                d = find_child(city["adcode"], district_hint)
                if d:
                    return _hit(d, "district", f"{province_feat['name']}/{city['name']}/{d['name']}")
            if city:
                return _hit(city, "city", f"{province_feat['name']}/{city['name']}")
        if province_feat:
            return _hit(province_feat, "province", province_feat["name"])
        return _miss()

    text = location or ""
    prov = province or text
    if _norm(prov) in MUNICIPALITIES or prov in MUNICIPALITIES:
        adcode = MUNI_ADCODE.get(_norm(prov)) or MUNI_ADCODE.get(prov)
        if adcode:
            d = find_child(adcode, text)
            if d:
                return _hit(d, "district", f"{prov}/{d['name']}")
            prov_feat = _find_province(prov)
            if prov_feat:
                return _hit(prov_feat, "province", prov_feat["name"])
        return _miss()

    prov_feat = _find_province(prov)
    if not prov_feat:
        return _miss()
    remainder = text
    if text and text != prov:
        remainder = text
    city = find_child(prov_feat["adcode"], remainder) if remainder else None
    if city:
        rest = remainder
        rest_n = re.sub(r"\s+", "", rest)
        if rest_n.startswith(city["norm"]):
            rest_n = rest_n[len(city["norm"]):]
        if rest_n and city["adcode"]:
            d = find_child(city["adcode"], rest_n)
            if d:
                return _hit(d, "district", f"{prov_feat['name']}/{city['name']}/{d['name']}")
        return _hit(city, "city", f"{prov_feat['name']}/{city['name']}")
    return _hit(prov_feat, "province", prov_feat["name"])


def _find_province(name: str) -> dict | None:
    n = _norm(name)
    if not n:
        return None
    for feat in provinces():
        if feat["norm"] and (n.startswith(feat["norm"]) or feat["norm"] in n):
            return feat
    return None


def _hit(feat: dict, acc: str, path: str) -> dict:
    return {"lon": feat["lon"], "lat": feat["lat"], "geo_accuracy": acc, "geo_path": path}


def _miss() -> dict:
    return {"lon": None, "lat": None, "geo_accuracy": "unknown", "geo_path": ""}
