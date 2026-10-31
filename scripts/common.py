"""通用工具：字段规范化、距离/方位计算、CHIRP 导出。

设计约束：
- 只用标准库，零安装依赖（用户机器装不上第三方依赖）。
- 中继台字段严格对齐 CRAC 官方填报格式：
  台址-省、台址-地市县、台址-具体地址、呼号、上行/下行频率、工作模式及主要参数、执照编号
"""
from __future__ import annotations

import math
import re

# ---------- 频率 ----------

FREQ_RE = re.compile(r"(\d{2,4}\.\d{1,5})\s*(?:MHz)?\s*[/／]\s*(\d{2,4}\.\d{1,5})", re.I)


def parse_pair(text: str) -> tuple[float | None, float | None]:
    """从一段文本里取 上行/下行 频率对。CRAC 口径是先上行（中继输入）后下行（中继输出）。"""
    m = FREQ_RE.search(text or "")
    if not m:
        return None, None
    try:
        up, down = float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None
    if up < 20 or down < 20:  # 明显不是 V/UHF，丢弃
        return None, None
    return up, down


def band_of(mhz: float | None) -> str:
    if mhz is None:
        return "unknown"
    if 28 <= mhz < 54:
        return "6m"
    if 50 <= mhz < 54:
        return "6m"
    if 144 <= mhz < 148:
        return "2m"
    if 430 <= mhz < 440:
        return "70cm"
    if 1240 <= mhz < 1300:
        return "23cm"
    if 1240 <= mhz < 2450:
        return "13cm"
    if 2450 <= mhz < 2500:
        return "13cm"
    return "other"


# ---------- 模式 ----------

DIGITAL_MARKS = ("DMR", "C4FM", "D-STAR", "DSTAR", "P25", "NXDN", "M17", "数字", "MOTOTRBO")
ANALOG_MARKS = ("FM", "模拟", "NFM", "WFM")


def classify_mode(raw: str) -> tuple[str, str]:
    """返回 (mode_class, submode)。mode_class ∈ analog/digital/mixed/unknown。"""
    up = (raw or "").upper()
    has_d = any(m.upper() in up for m in DIGITAL_MARKS)
    # 注意：'FM' 是模拟标记，但 'C4FM' 是数字标记，先剔除 C4FM 再判模拟
    analog_probe = up.replace("C4FM", "")
    has_a = any(m.upper() in analog_probe for m in ANALOG_MARKS)

    sub = []
    for name, key in (
        ("DMR", "DMR"),
        ("C4FM", "C4FM"),
        ("D-STAR", "D-STAR"),
        ("P25", "P25"),
        ("NXDN", "NXDN"),
        ("M17", "M17"),
    ):
        if key in up:
            sub.append(name)

    if has_d and has_a:
        cls = "mixed"
    elif has_d:
        cls = "digital"
    elif has_a:
        cls = "analog"
    else:
        cls = "unknown"
    return cls, ",".join(sub)


TONES_RE = re.compile(r"(CTCSS|TSQL)\s*[:：]?\s*([\d.]+)", re.I)
BARE_TONE_RE = re.compile(r"FM\s*[/／]\s*([\d.]+)")
DCS_RE = re.compile(r"DCS\s*[:：]?\s*(\d{3})", re.I)
CC_RE = re.compile(r"彩色码\s*(\d+)", re.I)
TS_RE = re.compile(r"时隙\s*([\d/]+)", re.I)


def parse_tone(raw: str) -> tuple[float | None, str | None]:
    """返回 (ctcss_hz, dcs_code)。"""
    t = raw or ""
    m = TONES_RE.search(t)
    if m:
        try:
            return float(m.group(2)), None
        except ValueError:
            pass
    m = BARE_TONE_RE.search(t)
    if m:
        try:
            return float(m.group(1)), None
        except ValueError:
            pass
    d = DCS_RE.search(t)
    if d:
        return None, d.group(1)
    return None, None


def parse_digital_params(raw: str) -> tuple[int | None, str | None]:
    cc = CC_RE.search(raw or "")
    ts = TS_RE.search(raw or "")
    return (int(cc.group(1)) if cc else None), (ts.group(1) if ts else None)


def is_suspended(raw: str) -> bool:
    return any(k in (raw or "") for k in ("暂停", "维护中", "停用"))


# ---------- 几何 ----------

EARTH_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


CARDINALS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]


def cardinal_zh(deg: float) -> str:
    return CARDINALS[int((deg % 360) / 45 + 0.5) % 8]


# ---------- CHIRP 导出 ----------

CHIRP_HEADER = [
    "Location", "Name", "Frequency", "Duplex", "Offset", "Tone",
    "rToneFreq", "cToneFreq", "DtcsCode", "DtcsPolarity", "Mode",
    "TStep", "Skip", "Comment",
]


def chirp_row(idx: int, r: dict) -> list[str]:
    """生成一行 CHIRP（CHIRP-next 通用列）。接收频率=下行，发射频率=上行。"""
    down, up = r.get("downlink_mhz"), r.get("uplink_mhz")
    if not down or not up:
        raise ValueError("缺少频率")
    offset = round(up - down, 4)
    duplex = "+" if offset > 0 else ("-" if offset < 0 else "")
    tone = "Tone" if r.get("ctcss_hz") else ("DTCS" if r.get("dcs") else "OFF")
    rtf = f"{r.get('ctcss_hz'):.1f}" if r.get("ctcss_hz") else "88.5"
    dtcs = r.get("dcs") or "023"
    name = f"{r.get('call','')} {r.get('city') or r.get('district') or ''}".strip()[:16]
    return [
        str(idx), name, f"{down:.5f}".rstrip("0").rstrip("."), duplex,
        f"{abs(offset):.5f}".rstrip("0").rstrip("."), tone, rtf, rtf, dtcs,
        "NN", "FM", "5.00", "", (r.get("mode_raw") or "")[:40],
    ]
