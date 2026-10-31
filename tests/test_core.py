"""核心逻辑单测：python3 -m unittest discover -s tests -v （需在工程根目录执行）"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from common import (  # noqa: E402
    band_of, bearing_deg, cardinal_zh, chirp_row, classify_mode, haversine_km,
    is_suspended, parse_digital_params, parse_pair, parse_tone,
)


class TestFreq(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_pair("144.700/145.300MHz"), (144.7, 145.3))

    def test_no_unit(self):
        self.assertEqual(parse_pair("430.300/439.800 "), (430.3, 439.8))

    def test_with_tail_params(self):
        up, down = parse_pair("433.850/438.850MHz, CTCSS：88.5Hz/C4FM（FDMA）")
        self.assertEqual((up, down), (433.85, 438.85))

    def test_invalid(self):
        self.assertEqual(parse_pair("CTCSS：88.5Hz"), (None, None))

    def test_band(self):
        self.assertEqual(band_of(439.85), "70cm")
        self.assertEqual(band_of(145.3), "2m")
        self.assertEqual(band_of(2400.0), "13cm")


class TestMode(unittest.TestCase):
    def test_analog(self):
        self.assertEqual(classify_mode("CTCSS：88.5Hz，模拟调频系统")[0], "analog")

    def test_c4fm_is_digital_not_fm(self):
        cls, sub = classify_mode("C4FM（FDMA），YAESU数字系统")
        self.assertEqual(cls, "digital")
        self.assertIn("C4FM", sub)

    def test_mixed(self):
        self.assertEqual(classify_mode("CTCSS：88.5Hz/C4FM（FDMA），模拟调频系统/YAESU数字系统")[0], "mixed")

    def test_dmr_params(self):
        cc, ts = parse_digital_params("DMR 彩色码8，时隙1/2")
        self.assertEqual((cc, ts), (8, "1/2"))

    def test_tone(self):
        self.assertEqual(parse_tone("CTCSS：88.5Hz")[0], 88.5)
        self.assertEqual(parse_tone("FM/88.5")[0], 88.5)
        self.assertEqual(parse_tone("DCS： 073")[1], "073")

    def test_suspended(self):
        self.assertTrue(is_suspended("DMR 彩色码8（维护中，暂停使用）"))
        self.assertFalse(is_suspended("模拟调频系统"))


class TestGeo(unittest.TestCase):
    def test_hangzhou_to_shanghai(self):
        # 杭州(30.2741,120.1551) -> 上海(31.2304,121.4737) 约 165km
        d = haversine_km(30.2741, 120.1551, 31.2304, 121.4737)
        self.assertTrue(160 < d < 175, d)

    def test_bearing_quadrants(self):
        self.assertEqual(cardinal_zh(bearing_deg(30.0, 120.0, 31.0, 120.0)), "北")
        self.assertEqual(cardinal_zh(bearing_deg(30.0, 120.0, 30.0, 121.0)), "东")
        self.assertEqual(cardinal_zh(bearing_deg(30.0, 120.0, 29.0, 120.0)), "南")


class TestChirp(unittest.TestCase):
    def test_positive_offset(self):
        row = chirp_row(1, {"call": "BR7IAT", "downlink_mhz": 439.375, "uplink_mhz": 434.375,
                            "ctcss_hz": 88.5, "city": "深圳市"})
        self.assertEqual(row[0], "1")
        self.assertEqual(row[3], "-")           # 上行低于下行 = 负偏移
        self.assertEqual(row[4], "5")
        self.assertEqual(row[5], "Tone")

    def test_negative_offset_upward(self):
        row = chirp_row(2, {"call": "BR5AB", "downlink_mhz": 145.52, "uplink_mhz": 144.92,
                            "ctcss_hz": 67.0, "city": "温州"})
        self.assertEqual(row[3], "-")


if __name__ == "__main__":
    unittest.main()
