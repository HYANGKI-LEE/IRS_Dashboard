from pathlib import Path

from parser.build_dataset import build_dataset, build_rows
from parser.classifier import classify
from parser.extractor import extract

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---- Tier 1: 방향/액션 분류 ----


def test_bid_with_two_leg_tenor():
    assert classify("2*3년 09.25 비드")[0] == "BID"


def test_bid_with_negative_rate():
    assert classify("10*15년 -04 비드")[0] == "BID"


def test_refer_beats_bid():
    assert classify("3년 비드 리퍼")[0] == "REFER"


def test_refer_no_space_variant():
    assert classify("9*10년 비드리퍼")[0] == "REFER"
    assert classify("2*3년 오퍼리퍼")[0] == "REFER"


def test_taken_beats_bid():
    side, is_live = classify("5년 99 테이큰 비드온")
    assert side == "TAKEN"
    assert is_live is True  # "비드온"이 있으므로 태그는 별도로 살아있음


def test_given_and_trade():
    assert classify("2*3년 09.75 기븐")[0] == "GIVEN"
    assert classify("4년 95.5 거래")[0] == "TRADE"


def test_two_sided_market_is_unclassified():
    # 방향 단어가 없는 양방향 시세는 UNCLASSIFIED가 맞는 동작 (방향을 단정할 근거가 없음)
    assert classify("4년 95.5/95.25")[0] == "UNCLASSIFIED"


def test_true_unclassified_stays_unclassified_in_build_rows():
    text = "[2026년 7월 8일 수요일]\n최정욱 (08:48:51) : 안녕하세요 오늘도 좋은 하루 되세요!\n"
    rows = build_rows(text, "test.txt")
    assert rows[0]["side_action"] == "UNCLASSIFIED"


def test_greeting_is_unclassified_no_crash():
    assert classify("안녕하세요 오늘도 좋은 하루 되세요!")[0] == "UNCLASSIFIED"


# ---- Tier 2: 필드 추출 ----


def test_extract_two_leg_tenor_and_rate():
    fields = extract("2*3년 09.25 비드")
    assert fields["tenor_legs"] == [2.0, 3.0]
    assert fields["tenor_unit"] == "년"
    assert fields["rate_1"] == 9.25


def test_extract_negative_rate():
    fields = extract("10*15년 -04 비드")
    assert fields["rate_1"] == -4.0


def test_extract_no_rate_on_refer():
    fields = extract("3년 비드 리퍼")
    assert fields["rate_raw"] is None


def test_extract_english_week_unit():
    # "1w"의 영문 w(주) 단위가 만기로 인식되지 않으면 "1"이 가격으로 잘못 잡히는 버그가 있었음
    fields = extract("1w kofr 59 / 55")
    assert fields["tenor_legs"] == [1.0]
    assert fields["tenor_unit"] == "w"
    assert fields["rate_1"] == 59.0
    assert fields["rate_2"] == 55.0


def test_extract_amount_and_clearing_tags():
    fields = extract("1*3년 42 / 41.5 CCP/ND 오퍼 100억")
    assert set(fields["clearing_tags"]) == {"CCP", "ND"}
    assert fields["amount_eok"] == 100.0
    assert fields["rate_1"] == 42.0
    assert fields["rate_2"] == 41.5


def test_extract_crs_suffix_attached_to_tenor():
    # "클"은 청산 태그가 아니라 CRS(통화스왑, IRS와 다른 상품) 표시
    fields = extract("2년클 26.5/25 로컬/포린")
    assert fields["tenor_raw"] == "2년"
    assert fields["instrument_type"] == "CRS"
    assert "클" not in fields["clearing_tags"]
    assert "로컬" in fields["clearing_tags"]
    assert "포린" in fields["clearing_tags"]


def test_extract_nd_attached_without_space():
    fields = extract("2*5년 21.25 / 20.25 양쪽ND")
    assert "ND" in fields["clearing_tags"]


def test_extract_rate_type_defaults_to_cd():
    assert extract("2*3년 09.25 비드")["rate_type"] == "CD"


def test_extract_rate_type_kofr_keywords():
    assert extract("9m kofr 베이시스 -18.5 비드")["rate_type"] == "KOFR"
    assert extract("9개월 KOFR Basis -17오퍼 청산")["rate_type"] == "KOFR"
    assert extract("1.5년 코베 -21 거래 비드온")["rate_type"] == "KOFR"
    assert extract("2*3년 09.25 코퍼 비드")["rate_type"] == "KOFR"


def test_extract_slash_tenor_separator():
    # 한국자금중개 파일은 만기 구분자로 '/'를 쓴다 (5/8년 등) - 가격 슬래시와 헷갈리면 안 됨
    fields = extract("5/8년 06 비드 청산")
    assert fields["tenor_legs"] == [5.0, 8.0]
    assert fields["rate_1"] == 6.0
    assert fields["rate_2"] is None


def test_extract_english_month_year_units():
    fields = extract("9m kofr 베이시스 -18.5 비드")
    assert fields["tenor_legs"] == [9.0]
    assert fields["tenor_unit"] == "m"
    assert fields["rate_1"] == -18.5


def test_extract_implicit_butterfly_tenor_no_unit():
    # "6*9*12 나비"처럼 단위 없이 숫자만 있고 바로 나비가 오는 경우 -> legs는 잡되
    # 그 숫자들이 가격으로 오인되면 안 됨
    fields = extract("6*9*12 나비 2.5 거래")
    assert fields["tenor_legs"] == [6.0, 9.0, 12.0]
    assert fields["tenor_unit"] is None
    assert fields["rate_1"] == 2.5


def test_extract_instrument_type_normalizes_butterfly_spelling():
    assert extract("6*9*12개월 나비 01.5 비드")["instrument_type"] == "버터플라이"
    assert extract("5*7*10년 버터플라이 00.5 오퍼 CCP")["instrument_type"] == "버터플라이"


# ---- 통합: 실제 데이터 파일 ----


def test_build_dataset_from_real_files_no_crash():
    df = build_dataset(str(DATA_DIR))
    assert len(df) > 0
    assert df["side_action"].isna().sum() == 0


def test_multiline_refer_block_gfi():
    # 최정욱 (12:08:23) 메시지는 3줄(9*10년/10*12년/10*15년 비드 리퍼)짜리 멀티라인 메시지
    df = build_dataset(str(DATA_DIR))
    rows = df[(df["sender"] == "최정욱") & (df["time"] == "12:08:23")]
    assert len(rows) == 3
    assert (rows["side_action"] == "REFER").all()


def test_multiline_kofr_basis_block_kidb():
    # 김희진 (10:36:54) 메시지는 4개의 서로 다른 만기(9m/1y/1.5y/2y) 줄로 된 멀티라인 메시지
    df = build_dataset(str(DATA_DIR))
    rows = df[(df["sender"] == "김희진") & (df["time"] == "10:36:54")]
    assert len(rows) == 4
    assert set(rows["tenor_raw"]) == {"9m", "1y", "1.5y", "2y"}


def test_market_trades_recap_block_does_not_crash():
    # 한국자금중개 파일의 <<Market trades...>> 시황요약 블록(약 25줄)은
    # 에러 없이 전부 UNCLASSIFIED로 떨어지는 게 기대 동작
    df = build_dataset(str(DATA_DIR))
    recap = df[df["raw_text"].str.contains("Market trades", na=False)]
    assert len(recap) >= 1  # 데이터가 느는 만큼 시황요약 블록도 계속 늘어날 수 있음
    assert (recap["side_action"] == "UNCLASSIFIED").all()
