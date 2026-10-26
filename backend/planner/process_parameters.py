"""Typed parameters with evidence checks shared by configured workflows."""
import math
import re


def parameter_value(value, spec):
    kind = spec.get("type", "number")
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("必须为有限数值")
        if "minimum" in spec and value < spec["minimum"] or "maximum" in spec and value > spec["maximum"]:
            raise ValueError("数值超出该参数的合法范围")
        if spec.get("integer") and int(value) != value:
            raise ValueError("必须为整数")
    elif kind == "boolean":
        if type(value) is not bool:
            raise ValueError("必须为是或否")
    elif kind == "string":
        if not isinstance(value, str) or not value.strip() or len(value) > spec.get("maxLength", 300):
            raise ValueError("必须为非空且长度合法的文字")
    else:
        raise ValueError("不支持的参数类型")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError("必须从指定选项中选择")
    return value


def parse_explicit(text, specs):
    values, conflicts = {}, []
    for name, spec in specs.items():
        prefix = re.escape(spec["label"]) + r"\s*[:：=]\s*"
        kind = spec.get("type", "number")
        suffix = re.escape(spec.get("unit", ""))
        if kind == "number":
            matches = list(re.finditer(prefix + r"(-?\d+(?:\.\d+)?)\s*" + suffix + r"(?![A-Za-z])", text, re.I))
            parsed = [(float(m[1]), m[0]) for m in matches]
        else:
            matches = list(re.finditer(prefix + r"([^\r\n；;。]+)", text))
            parsed = [(m[1].strip(), m[0]) for m in matches]
            if kind == "boolean":
                choices = {"是": True, "否": False, "true": True, "false": False}
                parsed = [(choices.get(v.lower(), v), q) for v, q in parsed]
        if len({str(v) for v, _ in parsed}) > 1:
            conflicts.append(f"{spec['label']}出现不同数值或内容，请修改原文消除冲突")
        elif parsed:
            value, quote = parsed[0]
            values[name] = {"value": value, "quote": quote, "source": "user_text"}
    return values, conflicts


def verify_model_binding(key, binding, spec, text, explicit):
    if not isinstance(binding, dict) or set(binding) != {"value", "quote", "token"}:
        raise ValueError("模型返回了未知参数或缺少来源")
    quote, token, value = binding["quote"], binding["token"], binding["value"]
    if not isinstance(quote, str) or not quote or quote not in text or not isinstance(token, str) or not token:
        raise ValueError("模型参数没有可核验的原文来源")
    parameter_value(value, spec)
    kind = spec.get("type", "number")
    if kind == "number":
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", token) or float(token) != value or not re.search(
            rf"(?<![\d.]){re.escape(token)}\s*{re.escape(spec.get('unit', ''))}(?![A-Za-z])", quote, re.I
        ):
            raise ValueError("模型参数数值或单位与原文不一致")
    elif kind == "string" and (token != value or token not in quote):
        raise ValueError("模型文字参数与原文不一致")
    elif kind == "boolean" and ({"是": True, "否": False, "true": True, "false": False}.get(token.lower()) is not value or token not in quote):
        raise ValueError("模型确认值与原文不一致")
    if not any(word.lower() in quote.lower() for word in (spec.get("anchors") or [spec["label"]])):
        raise ValueError("模型参数缺少所属阶段的证据")
    if key in explicit and explicit[key]["value"] != value:
        raise ValueError("模型参数与明确字段冲突")
    return {"value": value, "source": "user_text", "quote": quote}
