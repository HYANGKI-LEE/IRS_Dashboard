"""IRS 브로커 채팅 파싱에 쓰이는 키워드/정규식 사전. 새 은어를 발견하면 이 파일만 고치면 된다."""
import re

DATE_HEADER_RE = re.compile(r"^\[(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일.*\]$")
MESSAGE_START_RE = re.compile(r"^(\S.*?)\s*\((\d{2}):(\d{2}):(\d{2})\)\s*:\s?(.*)$")

# Tier 1: 우선순위 순서대로 검사 (앞에 있을수록 먼저 매치됨). "거래/기븐/테이큰"이
# "비드/오퍼"보다 먼저 와야 "테이큰"이 "비드"로 오분류되지 않는다. "리퍼"도 마찬가지.
SIDE_ACTION_RULES = [
    ("GIVEN", re.compile(r"기븐")),
    ("TAKEN", re.compile(r"테이큰")),
    ("TRADE", re.compile(r"거래|체결")),
    ("REFER", re.compile(r"리퍼")),
    ("BID", re.compile(r"비드")),
    ("OFFER", re.compile(r"오퍼")),
]
IS_LIVE_RE = re.compile(r"비드온|오퍼온")

# Tier 2: 만기(tenor). 다리(leg) 2~3개(*, / 구분자 모두 허용) 우선, 단일 만기 폴백.
_NUM = r"\d+(?:\.\d+)?"
_UNIT = r"(?:년|개월|주|[yYmMwW])"
TENOR_MULTI_LEG_RE = re.compile(
    rf"({_NUM})\s*([*/])\s*({_NUM})(?:\s*([*/])\s*({_NUM}))?\s*({_UNIT})"
)
TENOR_SINGLE_RE = re.compile(rf"({_NUM})\s*({_UNIT})")
# "6*9*12 나비"처럼 단위(개월/년) 없이 숫자만 쓰고 바로 나비/버터플라이가 오는 경우.
# 단위를 못 쓰므로 tenor_unit은 None으로 남지만, 최소한 숫자를 만기로 인식해서
# 가격(rate) 추출 시 이 숫자들이 잘못 가격으로 잡히는 것을 막는다.
TENOR_IMPLICIT_BUTTERFLY_RE = re.compile(
    rf"({_NUM})\s*([*/])\s*({_NUM})\s*([*/])\s*({_NUM})\s*(?=나비|버터플라이)"
)
# "2년클"처럼 만기 단위 뒤에 공백 없이 붙는 클리어링 표시
TENOR_CLEARING_SUFFIX_RE = re.compile(r"(년|개월)클")

# Tier 2: 가격(rate). "@"로 시작하는 체결가 표기를 선택적으로 소비, "/"로 나뉜 양방향 가격 지원.
RATE_RE = re.compile(rf"@?\s*(-?{_NUM})(?:\s*/\s*(-?{_NUM}))?")

# Tier 2: 금액 (억 단위 그대로 보존 — billion 환산은 착오 위험이 있어 하지 않음)
AMOUNT_RE = re.compile(rf"({_NUM})\s*억")

# Tier 2: 청산/venue 태그 (동시 출현 가능하므로 리스트로 수집)
CLEARING_TAG_PATTERNS = [
    ("CCP", re.compile(r"ccp", re.IGNORECASE)),
    # 한글(예: "양쪽ND")은 정규식 \b 기준 단어문자라 \bnd\b가 못 잡는다.
    # 라틴 알파벳과만 안 붙어있으면 되도록 lookaround로 완화.
    ("ND", re.compile(r"(?<![A-Za-z])nd(?![A-Za-z])", re.IGNORECASE)),
    ("청산", re.compile(r"청산")),
    ("포린", re.compile(r"포린")),
    ("로컬", re.compile(r"로컬")),
]

# Tier 2: 상품 구분. 나비/버터플라이는 동일 개념 -> 동일 값으로 정규화.
INSTRUMENT_RULES = [
    ("버터플라이", re.compile(r"나비|버터플라이")),
    ("코베", re.compile(r"코베")),
    ("KOFR베이시스", re.compile(r"kofr|베이시스", re.IGNORECASE)),
]
DEFAULT_INSTRUMENT = "IRS"

# Tier 2: 금리 종류. 코퍼/KOFR/kofr/코베가 들어가면 KOFR, 그 외(기본)는 CD.
RATE_TYPE_KOFR_RE = re.compile(r"코퍼|코베|kofr", re.IGNORECASE)
DEFAULT_RATE_TYPE = "CD"
