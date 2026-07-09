"""Tier 1: 하위라인 하나를 방향/액션(BID/OFFER/TRADE/GIVEN/TAKEN/REFER/UNCLASSIFIED)으로 분류한다.

부분일치 검색이며 우선순위가 있다 (taxonomy.SIDE_ACTION_RULES 순서대로 체크) —
예를 들어 "테이큰"이 있으면 그 문자열에 "비드"가 없어도 상관없이 TAKEN으로 분류되고,
"비드 리퍼"는 "비드"보다 먼저 체크되는 "리퍼" 규칙에 걸려 REFER가 된다.
"가격을 찾습니다" 같은 문의성 표현은 별도 버켓 없이 UNCLASSIFIED로 둔다(사용자 확정 사항).
"""
from parser.taxonomy import IS_LIVE_RE, SIDE_ACTION_RULES


def classify(sub_line: str) -> tuple[str, bool]:
    side_action = "UNCLASSIFIED"
    for label, pattern in SIDE_ACTION_RULES:
        if pattern.search(sub_line):
            side_action = label
            break
    is_live = bool(IS_LIVE_RE.search(sub_line))
    return side_action, is_live
