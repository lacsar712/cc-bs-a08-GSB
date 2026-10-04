"""桥梁微应变换算与判定。

换算公式（应变片，灵敏度系数 K，激励/额定电压 E，输出电压 U 以毫伏计）：

    epsilon(με) = U(mV) / (K * E(V)) * 1000

微应变合法量程 0～100000 με；判定带 80～220 με 为合格，否则越界。

所有退回措辞集中在本模块常量中：试算预览与正式报送共用同一组校验函数，
因此页面表单与直打接口拿到的退回文本完全一致。
"""

import math

# 微应变量程
MICROSTRAIN_MIN = 0.0
MICROSTRAIN_MAX = 100_000.0

# 判定带
PASS_MIN = 80.0
PASS_MAX = 220.0

# 统一退回措辞（预览 / 报送 / 设置保存共用，改动需三处同时生效故集中于此）
ERR_SENSITIVITY = "灵敏度系数非法：须为大于 0 的数字"
ERR_RATED_VOLTAGE = "额定电压非法：须为大于 0 的数字（伏）"
ERR_RAW_VOLTAGE = "原始电压非法：须为数字（毫伏）"
ERR_MICROSTRAIN = "微应变必须是数字"
ERR_OUT_OF_RANGE = "换算出界：微应变超出 0～100000 με 量程"
ERR_MICROSTRAIN_RANGE = "微应变超出 0～100000 με 量程"
ERR_PATH_AMBIGUOUS = "只能选择一条报送路径：原始电压或微应变二选一"
ERR_PATH_MISSING = "请填写原始电压或微应变"


class ConversionError(ValueError):
    """换算/校验失败，message 即统一退回措辞。"""


def _finite_float(raw, err_message: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ConversionError(err_message)
    if not math.isfinite(value):
        raise ConversionError(err_message)
    return value


def parse_sensitivity(raw) -> float:
    value = _finite_float(raw, ERR_SENSITIVITY)
    if value <= 0:
        raise ConversionError(ERR_SENSITIVITY)
    return value


def parse_rated_voltage(raw) -> float:
    value = _finite_float(raw, ERR_RATED_VOLTAGE)
    if value <= 0:
        raise ConversionError(ERR_RATED_VOLTAGE)
    return value


def parse_raw_voltage(raw) -> float:
    return _finite_float(raw, ERR_RAW_VOLTAGE)


def parse_microstrain(raw) -> float:
    return _finite_float(raw, ERR_MICROSTRAIN)


def convert_voltage_to_microstrain(
    raw_voltage: float, sensitivity: float, rated_voltage: float
) -> float:
    """U(mV)/(K*E(V))*1000，结果越界抛统一措辞。"""
    try:
        microstrain = raw_voltage * 1000.0 / (sensitivity * rated_voltage)
    except ZeroDivisionError:
        # parse 阶段已拦住，双保险
        raise ConversionError(ERR_SENSITIVITY)
    if not math.isfinite(microstrain):
        raise ConversionError(ERR_OUT_OF_RANGE)
    if not (MICROSTRAIN_MIN <= microstrain <= MICROSTRAIN_MAX):
        raise ConversionError(ERR_OUT_OF_RANGE)
    return microstrain


def ensure_microstrain_range(microstrain: float) -> float:
    if not math.isfinite(microstrain) or not (
        MICROSTRAIN_MIN <= microstrain <= MICROSTRAIN_MAX
    ):
        raise ConversionError(ERR_MICROSTRAIN_RANGE)
    return microstrain


def conversion_formula_text(
    raw_voltage: float, sensitivity: float, rated_voltage: float, microstrain: float
) -> str:
    return (
        f"{raw_voltage:g} mV ÷（{sensitivity:g} × {rated_voltage:g} V）× 1000"
        f" = {microstrain:g} με"
    )


def judge_microstrain(microstrain: float) -> tuple[str, str]:
    if PASS_MIN <= microstrain <= PASS_MAX:
        return "合格", "微应变处于 80～220 με 设计允许范围内"
    if microstrain < PASS_MIN:
        return "越界", "微应变低于 80 με 设计下限"
    return "越界", "微应变高于 220 με 设计上限"
