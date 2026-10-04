"""换算与双路径校验的标准库单元测试（无需第三方依赖/数据库）。

运行：cd backend && python3 -m unittest test_rules -v
"""

import unittest

from rules import (
    MSG_MICROSTRAIN_INVALID,
    MSG_OUT_OF_RANGE,
    MSG_PATH_CONFLICT,
    MSG_PATH_REQUIRED,
    MSG_RATED_VOLTAGE_INVALID,
    MSG_SENSITIVITY_INVALID,
    MSG_SPAN_REQUIRED,
    MSG_VOLTAGE_INVALID,
    ConversionError,
    convert_voltage_to_microstrain,
    judge_microstrain,
    parse_rated_voltage,
    parse_sensitivity,
    parse_voltage,
    resolve_submission,
)


def kv(**kw):
    return kw


class ConversionTests(unittest.TestCase):
    def test_formula_basic(self):
        # K=2.0, U额=5V: 0.001V -> 100 με
        self.assertAlmostEqual(
            convert_voltage_to_microstrain(0.001, 2.0, 5.0), 100.0
        )

    def test_pass_band_voltage(self):
        # 选一个换算后落在 80～220 带内的电压：150 με
        ms = convert_voltage_to_microstrain(0.0015, 2.0, 5.0)
        self.assertAlmostEqual(ms, 150.0)
        verdict, _ = judge_microstrain(ms)
        self.assertEqual(verdict, "合格")

    def test_out_of_band_voltage(self):
        # 故意算出越界：0.003V -> 300 με > 220
        ms = convert_voltage_to_microstrain(0.003, 2.0, 5.0)
        self.assertAlmostEqual(ms, 300.0)
        verdict, _ = judge_microstrain(ms)
        self.assertEqual(verdict, "越界")

    def test_below_band_voltage(self):
        ms = convert_voltage_to_microstrain(0.0005, 2.0, 5.0)
        self.assertAlmostEqual(ms, 50.0)
        verdict, _ = judge_microstrain(ms)
        self.assertEqual(verdict, "越界")

    def test_invalid_sensitivity_zero(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_SENSITIVITY_INVALID + "$"):
            resolve_submission(kv(span_code="S1", voltage=0.001, sensitivity=0, rated_voltage=5))

    def test_invalid_sensitivity_text(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_SENSITIVITY_INVALID + "$"):
            resolve_submission(kv(span_code="S1", voltage=0.001, sensitivity="abc", rated_voltage=5))

    def test_invalid_sensitivity_out_of_range(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_SENSITIVITY_INVALID + "$"):
            resolve_submission(kv(span_code="S1", voltage=0.001, sensitivity=99, rated_voltage=5))

    def test_invalid_rated_voltage(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_RATED_VOLTAGE_INVALID + "$"):
            resolve_submission(kv(span_code="S1", voltage=0.001, sensitivity=2, rated_voltage=0))

    def test_invalid_voltage_text(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_VOLTAGE_INVALID + "$"):
            resolve_submission(kv(span_code="S1", voltage="x", sensitivity=2, rated_voltage=5))

    def test_converted_out_of_instrument_range(self):
        # 极大电压 -> >100000 με，换算出界
        with self.assertRaisesRegex(ConversionError, "^" + MSG_OUT_OF_RANGE + "$"):
            resolve_submission(kv(span_code="S1", voltage=1000, sensitivity=2, rated_voltage=5))

    def test_direct_path_valid(self):
        d = resolve_submission(kv(span_code=" S2 ", microstrain=150))
        self.assertEqual(d["span_code"], "S2")
        self.assertAlmostEqual(d["microstrain"], 150.0)
        self.assertFalse(d["converted_from_voltage"])
        self.assertIsNone(d["raw_voltage"])

    def test_direct_path_out_of_range(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_OUT_OF_RANGE + "$"):
            resolve_submission(kv(span_code="S2", microstrain=200000))

    def test_direct_path_bad_number(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_MICROSTRAIN_INVALID + "$"):
            resolve_submission(kv(span_code="S2", microstrain="abc"))

    def test_both_paths_conflict(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_PATH_CONFLICT + "$"):
            resolve_submission(kv(span_code="S2", microstrain=150, voltage=0.001, sensitivity=2, rated_voltage=5))

    def test_neither_path(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_PATH_REQUIRED + "$"):
            resolve_submission(kv(span_code="S2"))

    def test_span_required(self):
        with self.assertRaisesRegex(ConversionError, "^" + MSG_SPAN_REQUIRED + "$"):
            resolve_submission(kv(span_code="   ", microstrain=150))

    def test_sensitivity_boundaries(self):
        self.assertAlmostEqual(parse_sensitivity(0.1), 0.1)
        self.assertAlmostEqual(parse_sensitivity(10.0), 10.0)
        with self.assertRaises(ConversionError):
            parse_sensitivity(0.09)

    def test_rated_voltage_boundaries(self):
        self.assertAlmostEqual(parse_rated_voltage(0.1), 0.1)
        with self.assertRaises(ConversionError):
            parse_rated_voltage(2000)

    def test_parse_voltage_accepts_negative(self):
        # 负电压（压应变侧）可换算；-100 με 在仪表量程内，入队后判定为越界
        self.assertAlmostEqual(parse_voltage(-0.001), -0.001)
        ms = convert_voltage_to_microstrain(-0.001, 2.0, 5.0)
        self.assertAlmostEqual(ms, -100.0)
        self.assertEqual(judge_microstrain(ms)[0], "越界")

    def test_two_paths_equivalent(self):
        # 同一读数：电压换算得到的微应变 == 直填微应变，判定必须一致
        voltage = convert_voltage_to_microstrain  # alias for readability
        ms = voltage(0.0018, 2.0, 5.0)
        a = resolve_submission(kv(span_code="S9", voltage=0.0018, sensitivity=2.0, rated_voltage=5.0))
        b = resolve_submission(kv(span_code="S9", microstrain=ms))
        self.assertAlmostEqual(a["microstrain"], b["microstrain"])
        self.assertEqual(
            judge_microstrain(a["microstrain"]), judge_microstrain(b["microstrain"])
        )


if __name__ == "__main__":
    unittest.main()
