"""桥梁微应变判定与原始电压换算。

判定带：80～220 με 为合格，否则越界。
换算：应变片输出原始电压 U，按灵敏度 K 与额定电压 U额 换算微应变

    με = U / (U额 × K) × 1_000_000

两条报送路径（直填微应变 / 填原始电压由服务端换算）共用本模块的
校验与判定，保证措辞与结论一致。
"""

import math

# 合格带（με）
MIN_MICROSTRAIN = 80.0
MAX_MICROSTRAIN = 220.0

# 仪表可接受的微应变量程：超出即「换算出界」，退回不入队
# （允许压应变负值；落带判定仍按 80～220 με）
RANGE_MIN_MICROSTRAIN = -100000.0
RANGE_MAX_MICROSTRAIN = 100000.0

# 灵敏度（K，无量纲）允许范围
MIN_SENSITIVITY = 0.1
MAX_SENSITIVITY = 10.0

# 额定电压（V）允许范围
MIN_RATED_VOLTAGE = 0.1
MAX_RATED_VOLTAGE = 1000.0

# —— 统一退回措辞（表单与直打共用，逐字一致）——
MSG_SPAN_REQUIRED = "跨段编号不能为空"
MSG_SENSITIVITY_INVALID = "灵敏度非法，须为 %.1f～%.1f 之间的数字" % (
    MIN_SENSITIVITY,
    MAX_SENSITIVITY,
)
MSG_RATED_VOLTAGE_INVALID = "额定电压非法，须为 %.1f～%.1f V 之间的数字" % (
    MIN_RATED_VOLTAGE,
    MAX_RATED_VOLTAGE,
)
MSG_VOLTAGE_INVALID = "原始电压必须是数字"
MSG_MICROSTRAIN_INVALID = "微应变必须是数字"
MSG_PATH_REQUIRED = "请填写微应变，或填写原始电压由服务端换算"
MSG_PATH_CONFLICT = "微应变与原始电压只能二选一填写"
MSG_OUT_OF_RANGE = "换算出界：微应变须在 %.0f～%.0f με 之间" % (
    RANGE_MIN_MICROSTRAIN,
    RANGE_MAX_MICROSTRAIN,
)


class ConversionError(ValueError):
    """换算或参数校验失败；message 即统一退回措辞。"""


def _to_float(value, invalid_msg: str) -> float:
    """严格转 float：None / 空串 / 布尔 / NaN / Inf 一律视为非法。"""
    if value is None or isinstance(value, bool):
        raise ConversionError(invalid_msg)
    if isinstance(value, str) and not value.strip():
        raise ConversionError(invalid_msg)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConversionError(invalid_msg)
    if not math.isfinite(number):
        raise ConversionError(invalid_msg)
    return number


def parse_sensitivity(value) -> float:
    number = _to_float(value, MSG_SENSITIVITY_INVALID)
    if not (MIN_SENSITIVITY <= number <= MAX_SENSITIVITY):
        raise ConversionError(MSG_SENSITIVITY_INVALID)
    return number


def parse_rated_voltage(value) -> float:
    number = _to_float(value, MSG_RATED_VOLTAGE_INVALID)
    if not (MIN_RATED_VOLTAGE <= number <= MAX_RATED_VOLTAGE):
        raise ConversionError(MSG_RATED_VOLTAGE_INVALID)
    return number


def parse_voltage(value) -> float:
    return _to_float(value, MSG_VOLTAGE_INVALID)


def parse_microstrain(value) -> float:
    return _to_float(value, MSG_MICROSTRAIN_INVALID)


def _is_filled(value) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def resolve_submission(body: dict) -> dict:
    """解析双路径报送载荷，返回统一的落库字段（两条路径唯一入口）。

    - 直填微应变：microstrain
    - 原始电压：voltage + sensitivity + rated_voltage，服务端换算
    二选一，互斥；任何一步非法都抛 ConversionError，措辞与直打完全一致。
    """
    span_code = str(body.get("span_code", "")).strip()
    if not span_code:
        raise ConversionError(MSG_SPAN_REQUIRED)

    has_microstrain = _is_filled(body.get("microstrain"))
    has_voltage = _is_filled(body.get("voltage"))
    if has_microstrain and has_voltage:
        raise ConversionError(MSG_PATH_CONFLICT)
    if not has_microstrain and not has_voltage:
        raise ConversionError(MSG_PATH_REQUIRED)

    if has_microstrain:
        microstrain = parse_microstrain(body.get("microstrain"))
        validate_microstrain_range(microstrain)
        return {
            "span_code": span_code,
            "microstrain": microstrain,
            "raw_voltage": None,
            "sensitivity": None,
            "rated_voltage": None,
            "converted_from_voltage": False,
        }

    sensitivity = parse_sensitivity(body.get("sensitivity"))
    rated_voltage = parse_rated_voltage(body.get("rated_voltage"))
    voltage = parse_voltage(body.get("voltage"))
    microstrain = convert_voltage_to_microstrain(
        voltage, sensitivity, rated_voltage
    )
    return {
        "span_code": span_code,
        "microstrain": microstrain,
        "raw_voltage": voltage,
        "sensitivity": sensitivity,
        "rated_voltage": rated_voltage,
        "converted_from_voltage": True,
    }


def convert_voltage_to_microstrain(
    voltage: float, sensitivity: float, rated_voltage: float
) -> float:
    """原始电压 → 微应变：με = U / (U额 × K) × 1e6。

    调用方须先用 parse_* 校验参数；换算结果落在仪表量程之外时
    抛 ConversionError（MSG_OUT_OF_RANGE），由接口统一退回。
    """
    denominator = rated_voltage * sensitivity
    if denominator <= 0:
        raise ConversionError(MSG_SENSITIVITY_INVALID)
    microstrain = voltage / denominator * 1_000_000.0
    # 收敛浮点尾差，使电压换算与直填同一数值时单据微应变严格一致
    microstrain = round(microstrain, 6)
    if not (RANGE_MIN_MICROSTRAIN <= microstrain <= RANGE_MAX_MICROSTRAIN):
        raise ConversionError(MSG_OUT_OF_RANGE)
    return microstrain


def validate_microstrain_range(microstrain: float) -> float:
    if not (RANGE_MIN_MICROSTRAIN <= microstrain <= RANGE_MAX_MICROSTRAIN):
        raise ConversionError(MSG_OUT_OF_RANGE)
    return microstrain


def judge_microstrain(microstrain: float) -> tuple[str, str]:
    if MIN_MICROSTRAIN <= microstrain <= MAX_MICROSTRAIN:
        return "合格", "微应变处于 80～220 με 设计允许范围内"
    if microstrain < MIN_MICROSTRAIN:
        return "越界", "微应变低于 80 με 设计下限"
    return "越界", "微应变高于 220 με 设计上限"
