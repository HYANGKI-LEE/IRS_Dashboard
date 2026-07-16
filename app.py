from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from parser.build_dataset import build_dataset

DATA_DIR = Path(__file__).parent / "data"

st.set_page_config(page_title="IRS 호가 대시보드", layout="wide")

DEAL_ACTIONS = {"TRADE", "GIVEN", "TAKEN"}
ACTION_LABELS = {
    "BID": "Bid",
    "OFFER": "Offer",
    "TRADE": "거래",
    "GIVEN": "기븐",
    "TAKEN": "테이큰",
    "REFER": "리퍼",
    "UNCLASSIFIED": "미분류",
}


@st.cache_data
def load_data(mtime_key: float) -> pd.DataFrame:
    return build_dataset(str(DATA_DIR))


def data_mtime_key() -> float:
    files = list(DATA_DIR.glob("*.txt"))
    return max((f.stat().st_mtime for f in files), default=0.0)


df = load_data(data_mtime_key())

if df.empty:
    st.warning("data/ 폴더에 .txt 채팅 로그가 없어요. 파일을 추가하고 새로고침하세요.")
    st.stop()

df["action_label"] = df["side_action"].map(ACTION_LABELS).fillna(df["side_action"])

# ---------------- 사이드바 필터 ----------------
st.sidebar.header("필터")

valid_dates = sorted(d for d in df["date"].dropna().unique())
if valid_dates:
    latest_date = pd.to_datetime(valid_dates[-1]).date()
    date_range = st.sidebar.date_input(
        "날짜 범위",
        value=(latest_date, latest_date),  # 기본값 = 가장 최신 날짜 하루만
        min_value=pd.to_datetime(valid_dates[0]).date(),
        max_value=latest_date,
    )
else:
    date_range = None

companies = sorted(df["source_file"].unique())
sel_companies = st.sidebar.multiselect("회사(파일)", companies, default=companies)

senders = sorted(df["sender"].dropna().unique())
sel_senders = st.sidebar.multiselect("발신자", senders, default=senders)

actions = list(ACTION_LABELS.keys())
sel_actions = st.sidebar.multiselect(
    "방향/액션", actions, default=actions, format_func=lambda a: ACTION_LABELS.get(a, a)
)

instruments = sorted(df["instrument_type"].dropna().unique())
sel_instruments = st.sidebar.multiselect("상품 구분", instruments, default=instruments)

all_tags = sorted({tag for tags in df["clearing_tags"] for tag in tags})
sel_tags = st.sidebar.multiselect("청산/venue 태그 (선택 안 하면 전체)", all_tags, default=[])

search_text = st.sidebar.text_input("원문 검색 (raw_text)")

# ---------------- 필터 적용 ----------------
mask = (
    df["source_file"].isin(sel_companies)
    & df["sender"].isin(sel_senders)
    & df["side_action"].isin(sel_actions)
    & df["instrument_type"].isin(sel_instruments)
)

if date_range and isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
    mask &= df["date"].apply(
        lambda d: d is not None and start <= pd.to_datetime(d).date() <= end
    )

if sel_tags:
    mask &= df["clearing_tags"].apply(lambda tags: any(t in tags for t in sel_tags))

if search_text:
    mask &= df["raw_text"].str.contains(search_text, case=False, na=False)

fdf = df[mask]

st.title("IRS 호가 대시보드")
st.caption(f"data/ 폴더의 .txt {len(list(DATA_DIR.glob('*.txt')))}개 파일 기준, 전체 {len(df)}건 중 {len(fdf)}건 표시 중")

# ---------------- KPI ----------------
total = len(fdf)
bid_n = (fdf["side_action"] == "BID").sum()
offer_n = (fdf["side_action"] == "OFFER").sum()
deal_n = fdf["side_action"].isin(DEAL_ACTIONS).sum()
refer_n = (fdf["side_action"] == "REFER").sum()
unclassified_n = (fdf["side_action"] == "UNCLASSIFIED").sum()
unclassified_pct = (unclassified_n / total * 100) if total else 0

k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
k1.metric("전체 건수", f"{total:,}")
k2.metric("Bid", f"{bid_n:,}")
k3.metric("Offer", f"{offer_n:,}")
k4.metric("거래/기븐/테이큰", f"{deal_n:,}")
k5.metric("리퍼", f"{refer_n:,}")
k6.metric("미분류 비율", f"{unclassified_pct:.1f}%")
k7.metric("발신자 수", fdf["sender"].nunique())

tab_price, tab_stats, tab_table, tab_audit = st.tabs(
    ["💰 가격", "📊 통계", "📋 테이블", "🔍 미분류 감사"]
)

UNIT_TO_MONTHS = {
    "년": 12, "y": 12, "Y": 12, "개월": 1, "m": 1, "M": 1,
    "주": 12 / 52, "w": 12 / 52, "W": 12 / 52,
}
WEEK_UNITS = ("주", "w", "W")
OFFER_COLOR = "#4C9F9F"
BID_COLOR = "#F5A65B"
TRADE_COLOR = "#9E9E9E"
QUOTE_ACTIONS = ["BID", "OFFER"]
DEAL_ACTION_LIST = ["GIVEN", "TAKEN", "TRADE"]  # 기븐 = Bid 쪽 체결, 테이큰 = Offer 쪽 체결, 거래 = 방향 불명

# Outright(단일 만기)의 기본 축 — 항상 이 순서로 표시하고, 데이터에 없으면 0으로 비워둔다.
BASE_OUTRIGHT_ORDER = ["6M", "9M", "1Y", "1.5Y", "2Y", "3Y", "4Y", "5Y", "7Y", "9Y", "10Y"]


def _tenor_avg_months(legs, unit):
    if not legs:
        return None
    factor = UNIT_TO_MONTHS.get(unit, 1)
    return (sum(legs) / len(legs)) * factor


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _unwrap_handle_series(values: list) -> list:
    """IRS 호가 관행상 '핸들'(정수부)을 생략하고 끝 두 자리만 부르는 경우가 많다
    (예: 4.99 -> "99", 5.02 -> "02"). 그대로 숫자로 보면 02(2.0)가 99보다 작아 보이지만
    실제로는 핸들이 4->5로 넘어간 것이므로 02가 더 높은 호가다.
    시간순으로 인접한 값끼리 차이가 50을 넘으면 핸들이 넘어간 것으로 보고 100 단위로
    보정해서, 연속적인(실제 크기 순서가 맞는) 시계열로 만든다. 첫 값은 원문 그대로 기준점으로 쓴다."""
    if not values:
        return values
    unwrapped = [values[0]]
    for v in values[1:]:
        prev = unwrapped[-1]
        diff = v - prev
        diff = ((diff + 50) % 100) - 50  # diff를 (-50, 50] 범위로 보정
        unwrapped.append(prev + diff)
    return unwrapped


def _outright_label(legs, unit):
    """단일 만기를 표준 표기(6M/1.5Y 등)로 정규화. 스펠링이 달라도(9개월/9m) 같은 라벨로 합쳐진다.
    주(week) 단위는 개월로 어설프게 환산하면 지저분해지므로 별도로 W 표기를 쓴다."""
    if not legs or len(legs) != 1:
        return None
    if unit in WEEK_UNITS:
        return f"{_fmt_num(legs[0])}W"
    months = _tenor_avg_months(legs, unit)
    if months is None:
        return None
    return f"{_fmt_num(months)}M" if months < 12 else f"{_fmt_num(months / 12)}Y"


def _outright_label_months(label: str) -> float:
    num, unit = float(label[:-1]), label[-1]
    if unit == "W":
        return num * (12 / 52)
    return num if unit == "M" else num * 12


def render_diverging_bar(cats, offer_vals, bid_vals, empty_msg: str):
    if not cats:
        st.info(empty_msg)
        return

    # 가운데 라벨이 막대 끝 숫자와 겹치지 않도록, 0을 중심으로 라벨 전용 여백(gap)을 비워두고
    # 그 바깥쪽에서부터 막대가 시작되게 한다. gap은 막대 값 크기에 비례.
    max_val = max(offer_vals + bid_vals) if (offer_vals + bid_vals) else 1
    gap = max(max_val * 0.126, 1.05)  # 기존 대비 70%

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=cats, x=[-v for v in offer_vals], base=-gap, orientation="h", name="Offer",
        marker_color=OFFER_COLOR, text=offer_vals, textposition="outside",
        hovertemplate="%{y} Offer: %{text}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=cats, x=bid_vals, base=gap, orientation="h", name="Bid",
        marker_color=BID_COLOR, text=bid_vals, textposition="outside",
        hovertemplate="%{y} Bid: %{text}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        y=cats, x=[0] * len(cats), mode="text", text=cats, textposition="middle center",
        textfont=dict(size=13, color="#333"), showlegend=False, hoverinfo="skip",
    ))
    outer = gap + max_val
    fig.update_layout(
        barmode="overlay",
        bargap=0.3,
        height=max(320, 40 * len(cats)),
        xaxis=dict(showticklabels=False, zeroline=False, range=[-outer * 1.2, outer * 1.2]),
        yaxis=dict(showticklabels=False, autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def _spread_label(legs, unit):
    """'*'와 '/' 구분자를 같은 만기로 합친다 (예: 5*10년, 5/10년 -> 둘 다 '5*10년').
    unit이 None인 경우(예: "6*9*12 나비"처럼 단위 표기가 아예 없는 경우) pandas를 거치면
    NaN(float)으로 바뀌어 `if unit`이 True로 오판되면서 "6*9*12nan" 같은 라벨이 생기던
    버그가 있어, 문자열인지 명시적으로 확인한다."""
    if not legs or len(legs) < 2:
        return None
    joined = "*".join(_fmt_num(x) for x in legs)
    if isinstance(unit, str) and unit:
        display_unit = "월" if unit == "개월" else unit
        return f"{joined}{display_unit}"
    return joined


def _is_single_leg(l):
    return isinstance(l, list) and len(l) == 1


def _is_multi_leg(l):
    return isinstance(l, list) and len(l) >= 2


def _label_counts(data: pd.DataFrame, actions: list, label_fn, leg_filter) -> pd.DataFrame:
    """actions(side_action 목록)별 만기 라벨 카운트 테이블. 데이터가 없어도 actions 컬럼은 항상 존재."""
    sub = data[data["side_action"].isin(actions) & data["tenor_legs"].apply(leg_filter)].copy()
    counts = pd.DataFrame(columns=actions)
    if not sub.empty:
        sub["label"] = sub.apply(lambda r: label_fn(r["tenor_legs"], r["tenor_unit"]), axis=1)
        sub = sub[sub["label"].notna()]
        if not sub.empty:
            counts = sub.groupby(["label", "side_action"]).size().unstack(fill_value=0)
    for a in actions:
        if a not in counts:
            counts[a] = 0
    return counts


def outright_order(data: pd.DataFrame) -> list:
    """기본 11개 만기 + 새로 발견된 만기를 모두 합쳐서 실제 기간(개월 환산) 기준으로 정렬.
    "1W"/"3M"처럼 기본 11개보다 짧은 만기도 맨 뒤가 아니라 제자리(맨 앞)에 오게 된다."""
    counts = _label_counts(data, QUOTE_ACTIONS + DEAL_ACTION_LIST, _outright_label, _is_single_leg)
    all_labels = set(BASE_OUTRIGHT_ORDER) | set(counts.index)
    return sorted(all_labels, key=_outright_label_months)


def spread_order(data: pd.DataFrame) -> list:
    """호가/거래 둘 다 포함해서 등장하는 스프레드 만기 라벨을, 각 다리를 개월로 환산한 뒤
    첫 번째 다리(A) 기준 오름차순으로 정렬한다. 단위를 무시하고 숫자만 비교하면
    "9*12개월"(9~12개월)이 "9*10년"(9~10년)과 같은 자리로 섞여버리므로 반드시 환산해야 함."""
    sub = data[
        data["side_action"].isin(QUOTE_ACTIONS + DEAL_ACTION_LIST)
        & data["tenor_legs"].apply(_is_multi_leg)
    ].copy()
    if sub.empty:
        return []
    sub["label"] = sub.apply(lambda r: _spread_label(r["tenor_legs"], r["tenor_unit"]), axis=1)
    sub = sub[sub["label"].notna()]
    meta = sub.drop_duplicates("label").set_index("label")[["tenor_legs", "tenor_unit"]]

    def sort_key(label):
        legs = meta.loc[label, "tenor_legs"]
        factor = UNIT_TO_MONTHS.get(meta.loc[label, "tenor_unit"], 1)
        return tuple(v * factor for v in legs)

    return sorted(meta.index, key=sort_key)


def render_outright_chart(data: pd.DataFrame, order: list):
    counts = _label_counts(data, QUOTE_ACTIONS, _outright_label, _is_single_leg).reindex(order, fill_value=0)
    render_diverging_bar(order, counts["OFFER"].tolist(), counts["BID"].tolist(), "")


def render_spread_chart(data: pd.DataFrame, order: list):
    if not order:
        st.info("선택된 데이터에 스프레드 거래(2개 이상 만기 조합) 정보가 없어요.")
        return
    counts = _label_counts(data, QUOTE_ACTIONS, _spread_label, _is_multi_leg).reindex(order, fill_value=0)
    render_diverging_bar(order, counts["OFFER"].tolist(), counts["BID"].tolist(), "")


def render_deal_stacked_chart(cats: list, given_vals: list, taken_vals: list, trade_vals: list, empty_msg: str):
    if not cats or sum(given_vals) + sum(taken_vals) + sum(trade_vals) == 0:
        st.info(empty_msg)
        return

    def _labels(vals):
        return [str(v) if v > 0 else "" for v in vals]

    totals = [g + t + r for g, t, r in zip(given_vals, taken_vals, trade_vals)]
    max_total = max(totals) if totals else 0
    gap = max(max_total * 0.03, 0.2)  # 합계 숫자를 막대 끝에서 살짝 띄우는 여백 (기존 대비 절반)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=cats, x=given_vals, orientation="h", name="기븐",
        marker_color=BID_COLOR, text=_labels(given_vals), textposition="inside",
        insidetextanchor="end", textfont=dict(color="black"),
        hovertemplate="%{y} 기븐: %{x}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=cats, x=taken_vals, orientation="h", name="테이큰",
        marker_color=OFFER_COLOR, text=_labels(taken_vals), textposition="inside",
        insidetextanchor="end", textfont=dict(color="black"),
        hovertemplate="%{y} 테이큰: %{x}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=cats, x=trade_vals, orientation="h", name="거래",
        marker_color=TRADE_COLOR, text=_labels(trade_vals), textposition="inside",
        insidetextanchor="end", textfont=dict(color="black"),
        hovertemplate="%{y} 거래: %{x}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        y=cats, x=[t + gap for t in totals], mode="text",
        text=[str(t) if t > 0 else "" for t in totals],
        textposition="middle right", showlegend=False, hoverinfo="skip",
    ))
    fig.update_layout(
        barmode="stack",
        height=max(320, 40 * len(cats)),
        xaxis=dict(showticklabels=False, zeroline=False, range=[0, (max_total + gap) * 1.2 or 1]),
        yaxis=dict(autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_outright_deal_chart(data: pd.DataFrame, order: list):
    counts = _label_counts(data, DEAL_ACTION_LIST, _outright_label, _is_single_leg).reindex(order, fill_value=0)
    render_deal_stacked_chart(
        order, counts["GIVEN"].tolist(), counts["TAKEN"].tolist(), counts["TRADE"].tolist(),
        "선택된 데이터에 실제 거래 내역이 없어요.",
    )


def render_spread_deal_chart(data: pd.DataFrame, order: list):
    if not order:
        st.info("선택된 데이터에 스프레드 거래 내역이 없어요.")
        return
    counts = _label_counts(data, DEAL_ACTION_LIST, _spread_label, _is_multi_leg).reindex(order, fill_value=0)
    render_deal_stacked_chart(
        order, counts["GIVEN"].tolist(), counts["TAKEN"].tolist(), counts["TRADE"].tolist(),
        "선택된 데이터에 스프레드 실제 거래 내역이 없어요.",
    )


def render_outright_and_spread(data: pd.DataFrame):
    st.subheader("Outright 만기별")
    st.caption("6M/9M/1Y/1.5Y/2Y/3Y/4Y/5Y/7Y/9Y/10Y가 기본 만기이며, 그 외 만기는 호가/거래가 생기면 뒤에 임시로 추가돼요.")
    outright_ord = outright_order(data)
    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown("**호가 (Bid/Offer)**")
        render_outright_chart(data, outright_ord)
    with oc2:
        st.markdown("**실제 거래 (기븐/테이큰/거래)**")
        render_outright_deal_chart(data, outright_ord)

    st.subheader("스프레드 거래 만기별")
    st.caption("2개 이상 만기를 조합한 거래(예: `2*3년`, `1*3년` 등) — 첫 번째 만기 기준 오름차순, `*`/`/` 구분자는 같은 만기로 통합")
    spread_ord = spread_order(data)
    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown("**호가 (Bid/Offer)**")
        render_spread_chart(data, spread_ord)
    with sc2:
        st.markdown("**실제 거래 (기븐/테이큰/거래)**")
        render_spread_deal_chart(data, spread_ord)


with tab_price:
    st.header("CD")
    render_outright_and_spread(fdf[fdf["rate_type"] == "CD"])

    st.divider()

    st.header("KOFR")
    st.caption("원문에 코퍼/코베/kofr/KOFR가 포함된 호가·거래")
    render_outright_and_spread(fdf[fdf["rate_type"] == "KOFR"])

    st.divider()

    st.subheader("만기별 가격 추이 (Outright)")
    rate_type_pick = st.selectbox("금리 종류", ["CD", "KOFR"])
    rt_df = fdf[fdf["rate_type"] == rate_type_pick]

    tenor_options = outright_order(rt_df)
    if not tenor_options:
        st.info("선택된 데이터에 Outright 만기 정보가 없어요.")
    else:
        picked_tenor = st.selectbox("만기 선택", tenor_options)

        single = rt_df[
            # 시황요약 블록처럼 방향 정보 없는 잡음(미분류), 호가를 거둬들인다는 뜻인
            # 리퍼(취소)는 실제 가격이 아니므로 가격 추이에서 제외
            (~rt_df["side_action"].isin(["UNCLASSIFIED", "REFER"]))
            & rt_df["tenor_legs"].apply(_is_single_leg)
        ].copy()
        single["outright_label"] = single.apply(
            lambda r: _outright_label(r["tenor_legs"], r["tenor_unit"]), axis=1
        )
        rdf = single[
            (single["outright_label"] == picked_tenor)
            & single["rate_1"].notna()
            & single["datetime"].notna()
        ]
        if len(rdf):
            rdf = rdf.sort_values("datetime").copy()
            rdf["price"] = _unwrap_handle_series(rdf["rate_1"].tolist())
            st.caption(
                "핸들(정수부) 생략 관행 보정 적용: 4.99->\"99\", 5.02->\"02\"처럼 인접 호가 대비 "
                "50 이상 튀면 핸들이 넘어간 것으로 보고 100 단위로 이어 붙였어요. "
                "원래 입력값은 raw_text/hover에서 확인 가능."
            )
            st.plotly_chart(
                px.scatter(
                    rdf,
                    x="datetime",
                    y="price",
                    color="action_label",
                    hover_data=["sender", "rate_1", "raw_text"],
                ),
                use_container_width=True,
            )
        else:
            st.info("이 만기에는 가격이 파싱된 데이터가 없어요.")

with tab_stats:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("방향/액션 분포")
        action_counts = fdf["action_label"].value_counts().reset_index()
        action_counts.columns = ["action", "count"]
        st.plotly_chart(px.bar(action_counts, x="action", y="count"), use_container_width=True)

    with c2:
        st.subheader("발신자별 방향/액션")
        by_sender = fdf.groupby(["sender", "action_label"]).size().reset_index(name="count")
        st.plotly_chart(
            px.bar(by_sender, x="sender", y="count", color="action_label", barmode="stack"),
            use_container_width=True,
        )

    c3, c4 = st.columns(2)

    with c3:
        st.subheader("만기별 분포 (상위 20)")
        tenor_counts = (
            fdf[fdf["tenor_raw"].notna()]["tenor_raw"].value_counts().head(20).reset_index()
        )
        tenor_counts.columns = ["tenor", "count"]
        st.plotly_chart(px.bar(tenor_counts, x="tenor", y="count"), use_container_width=True)

    with c4:
        st.subheader("청산/venue 태그 분포")
        tag_series = fdf["clearing_tags"].explode().dropna()
        if len(tag_series):
            tag_counts = tag_series.value_counts().reset_index()
            tag_counts.columns = ["tag", "count"]
            st.plotly_chart(px.pie(tag_counts, names="tag", values="count"), use_container_width=True)
        else:
            st.info("선택된 데이터에 청산 태그가 없어요.")

    st.subheader("시간대별 활동량 (30분 단위)")
    tdf = fdf[fdf["datetime"].notna()].copy()
    if len(tdf):
        tdf["bucket"] = tdf["datetime"].dt.floor("30min")
        activity = tdf.groupby(["bucket", "action_label"]).size().reset_index(name="count")
        st.plotly_chart(
            px.bar(activity, x="bucket", y="count", color="action_label"), use_container_width=True
        )
    else:
        st.info("선택된 데이터에 시간 정보가 없어요.")

with tab_table:
    display_cols = [
        "source_file", "sender", "date", "time", "action_label", "is_live",
        "rate_type", "instrument_type", "tenor_raw", "rate_1", "rate_2", "amount_eok",
        "clearing_tags", "raw_text",
    ]
    show_df = fdf[display_cols].copy()
    show_df["clearing_tags"] = show_df["clearing_tags"].apply(lambda t: ", ".join(t))
    st.dataframe(show_df, use_container_width=True, height=500)
    st.download_button(
        "CSV 다운로드",
        show_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="irs_dashboard_filtered.csv",
        mime="text/csv",
    )

with tab_audit:
    st.caption("side_action이 '미분류'로 떨어진 원문만 모아서 보여줘요. 새로운 은어를 발견하면 parser/taxonomy.py에 추가하세요.")
    audit_df = fdf[fdf["side_action"] == "UNCLASSIFIED"][
        ["source_file", "sender", "date", "time", "raw_text"]
    ]
    st.dataframe(audit_df, use_container_width=True, height=500)
