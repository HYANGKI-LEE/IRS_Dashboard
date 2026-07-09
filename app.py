from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from parser.build_dataset import build_dataset

DATA_DIR = Path(__file__).parent / "data"

st.set_page_config(page_title="IRS 브로커 채팅 대시보드", layout="wide")

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
    date_range = st.sidebar.date_input(
        "날짜 범위",
        value=(pd.to_datetime(valid_dates[0]).date(), pd.to_datetime(valid_dates[-1]).date()),
        min_value=pd.to_datetime(valid_dates[0]).date(),
        max_value=pd.to_datetime(valid_dates[-1]).date(),
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

st.title("IRS 브로커 채팅 대시보드")
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

tab_charts, tab_table, tab_audit = st.tabs(["📊 차트", "📋 테이블", "🔍 미분류 감사"])

with tab_charts:
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

    st.subheader("만기별 가격 추이")
    tenor_options = sorted(fdf["tenor_raw"].dropna().unique())
    if tenor_options:
        picked_tenor = st.selectbox("만기 선택", tenor_options)
        rdf = fdf[(fdf["tenor_raw"] == picked_tenor) & fdf["rate_1"].notna() & fdf["datetime"].notna()]
        if len(rdf):
            st.plotly_chart(
                px.scatter(
                    rdf.sort_values("datetime"),
                    x="datetime",
                    y="rate_1",
                    color="action_label",
                    hover_data=["sender", "raw_text"],
                ),
                use_container_width=True,
            )
        else:
            st.info("이 만기에는 가격이 파싱된 데이터가 없어요.")
    else:
        st.info("선택된 데이터에 만기 정보가 없어요.")

with tab_table:
    display_cols = [
        "source_file", "sender", "date", "time", "action_label", "is_live",
        "instrument_type", "tenor_raw", "rate_1", "rate_2", "amount_eok",
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
