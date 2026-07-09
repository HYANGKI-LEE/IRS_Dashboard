"""Tier 2: 하위라인 하나에서 만기/가격/금액/청산태그/상품구분을 best-effort로 추출한다.

Tier 1 분류 결과와 무관하게 항상 시도한다. 만기를 먼저 찾아 그 구간을 제거한 뒤
나머지 문자열에서 가격을 찾는다 — 그래야 "5/8년"처럼 "/"로 나뉜 만기가 양방향
가격으로 오인되지 않는다. raw_text는 별도로 항상 보존되므로(build_dataset에서 처리)
여기서 추출에 실패해도 정보 손실은 없다.

주의: "4년 95.5/95.25"처럼 "/"로 나뉜 두 가격 중 어느 쪽이 bid이고 어느 쪽이 offer인지는
표기 관례상 문맥마다 다를 수 있어 자동으로 단정하지 않는다. 대신 rate_1/rate_2로 순서만
보존해서 표에 그대로 노출한다 (원문 raw_text와 나란히 보면 실제 의미 판단 가능).
"""
from parser.taxonomy import (
    AMOUNT_RE,
    CLEARING_TAG_PATTERNS,
    DEFAULT_INSTRUMENT,
    INSTRUMENT_RULES,
    RATE_RE,
    TENOR_CLEARING_SUFFIX_RE,
    TENOR_IMPLICIT_BUTTERFLY_RE,
    TENOR_MULTI_LEG_RE,
    TENOR_SINGLE_RE,
)


def _extract_tenor(sub_line: str):
    match = TENOR_MULTI_LEG_RE.search(sub_line)
    if match:
        n1, sep1, n2, sep2, n3, unit = match.groups()
        legs = [float(n1), float(n2)]
        if n3:
            legs.append(float(n3))
        remaining = sub_line[: match.start()] + sub_line[match.end() :]
        return match.group(0), legs, unit, remaining

    match = TENOR_SINGLE_RE.search(sub_line)
    if match:
        num, unit = match.groups()
        remaining = sub_line[: match.start()] + sub_line[match.end() :]
        return match.group(0), [float(num)], unit, remaining

    match = TENOR_IMPLICIT_BUTTERFLY_RE.search(sub_line)
    if match:
        n1, sep1, n2, sep2, n3 = match.groups()
        legs = [float(n1), float(n2), float(n3)]
        remaining = sub_line[: match.start()] + sub_line[match.end() :]
        return match.group(0), legs, None, remaining

    return None, [], None, sub_line


def _extract_rate(remaining: str):
    match = RATE_RE.search(remaining)
    if not match:
        return None, None, None
    r1, r2 = match.groups()
    return match.group(0).strip(), float(r1), (float(r2) if r2 else None)


def _extract_amount(sub_line: str):
    match = AMOUNT_RE.search(sub_line)
    return float(match.group(1)) if match else None


def _extract_clearing_tags(sub_line: str) -> list[str]:
    tags = [label for label, pattern in CLEARING_TAG_PATTERNS if pattern.search(sub_line)]
    if TENOR_CLEARING_SUFFIX_RE.search(sub_line):
        tags.append("클")
    return tags


def _extract_instrument_type(sub_line: str) -> str:
    for label, pattern in INSTRUMENT_RULES:
        if pattern.search(sub_line):
            return label
    return DEFAULT_INSTRUMENT


def extract(sub_line: str) -> dict:
    tenor_raw, tenor_legs, tenor_unit, remaining = _extract_tenor(sub_line)
    rate_raw, rate_1, rate_2 = _extract_rate(remaining)
    return {
        "instrument_type": _extract_instrument_type(sub_line),
        "tenor_raw": tenor_raw,
        "tenor_legs": tenor_legs,
        "tenor_unit": tenor_unit,
        "rate_raw": rate_raw,
        "rate_1": rate_1,
        "rate_2": rate_2,
        "amount_eok": _extract_amount(sub_line),
        "clearing_tags": _extract_clearing_tags(sub_line),
    }
