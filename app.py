import os
import json
from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from openai import OpenAI


# =========================
# 0) 기본 설정
# =========================
st.set_page_config(
    page_title="개인 지출 분석 대시보드",
    page_icon="💰",
    layout="wide",
)

st.title("💰 개인 지출 분석 대시보드")

# (Streamlit Cloud) Secrets 권장
# - 로컬: 환경변수 OPENAI_API_KEY 설정
# - 클라우드: st.secrets["OPENAI_API_KEY"] 사용
OPENAI_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None


# =========================
# 1) 유틸 함수
# =========================
def _to_datetime_safe(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_datetime(df[col], errors="coerce")


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    required_cols = ["date", "amount", "category", "description"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.error(f"필수 컬럼이 없습니다: {', '.join(missing)}")
        st.stop()

    df["date"] = _to_datetime_safe(df, "date")
    df = df.dropna(subset=["date"])

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)

    # 연/월 컬럼
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.month.astype(int)
    df["year_month"] = df["date"].dt.to_period("M")  # 정렬 안전

    # payment_method 없으면 안전하게 생성
    if "payment_method" not in df.columns:
        df["payment_method"] = "미기재"

    # memo 없으면 생성
    if "memo" not in df.columns:
        df["memo"] = ""

    return df


def format_won(x: int) -> str:
    try:
        return f"{int(x):,}원"
    except Exception:
        return "-"


def calc_previous_period(df_all: pd.DataFrame, start_date, end_date):
    """선택 기간과 동일 길이의 '직전 기간' 데이터 추출"""
    if start_date is None or end_date is None:
        return df_all.iloc[0:0]

    length_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length_days - 1)

    df_prev = df_all[
        (df_all["date"].dt.date >= prev_start) & (df_all["date"].dt.date <= prev_end)
    ]
    return df_prev


def calc_yoy_if_single_month(df_all: pd.DataFrame, df_filtered: pd.DataFrame):
    """선택 범위가 '단일 월'일 때만 전년 동월 비교"""
    if df_filtered.empty:
        return None

    # start/end가 같은 year_month인지
    ym = df_filtered["year_month"].unique()
    if len(ym) != 1:
        return None

    current_ym = ym[0]  # Period('YYYY-MM')
    prev_ym = (current_ym - 12)

    df_yoy = df_all[df_all["year_month"] == prev_ym]
    return df_yoy


def build_kpi_card(title: str, value: int, delta_pct: float | None):
    """Streamlit metric 대신 '대시보드 카드' 느낌으로 HTML 카드"""
    if delta_pct is None:
        delta_html = "<span style='color:#6b7280;font-size:13px;'>전기 대비: -</span>"
    else:
        arrow = "▲" if delta_pct >= 0 else "▼"
        # 사용자님 요청 느낌대로: 증가=빨강 / 감소=초록
        color = "#ef4444" if delta_pct >= 0 else "#22c55e"
        delta_html = f"<span style='color:{color};font-size:13px;font-weight:700;'>{arrow} {abs(delta_pct):.1f}%</span>"

    st.markdown(
        f"""
        <div style="
            border:1px solid #e5e7eb;
            border-radius:16px;
            padding:16px 16px 14px 16px;
            background:#ffffff;
            box-shadow:0 1px 8px rgba(0,0,0,0.04);
            ">
            <div style="color:#374151;font-size:14px;font-weight:700;margin-bottom:6px;">{title}</div>
            <div style="font-size:28px;font-weight:800;letter-spacing:-0.5px;margin-bottom:6px;">{format_won(value)}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def compute_budget_reco(df_filtered: pd.DataFrame, save_target_pct: int = 10) -> pd.DataFrame:
    """
    맞춤형 예산 추천(표/계산 결과):
    - 현재 지출(카테고리 합)
    - 권장 예산(카테고리별 절감률 적용)
    - 절감 목표 금액/절감률
    """
    if df_filtered.empty:
        return pd.DataFrame(columns=["카테고리", "현재 지출", "권장 예산", "절감 목표", "절감률"])

    cat_sum = df_filtered.groupby("category")["amount"].sum().sort_values(ascending=False)
    total = cat_sum.sum() if cat_sum.sum() else 1

    # 지출 비중 기반으로 "현실적인" 절감률 차등
    # - 비중 큰 카테고리일수록 절감율 조금 더 주기
    rows = []
    for cat, amt in cat_sum.items():
        share = amt / total  # 0~1
        # base 절감률: 전체 목표를 기본으로, 비중이 큰 카테고리일수록 +α
        # 예) 목표 10%면, 상위 비중은 12~18% 정도까지
        adj = 0
        if share >= 0.25:
            adj = 8
        elif share >= 0.15:
            adj = 5
        elif share >= 0.08:
            adj = 2

        # 카테고리 성격별 조정(예시)
        # (필요하면 사용자님 데이터 기준으로 더 튜닝 가능)
        if cat in ["통신비", "교통비", "구독"]:
            adj = max(adj - 2, 0)  # 필수성 높으면 완화
        if cat in ["쇼핑", "문화/여가", "기타", "미용/관리"]:
            adj = adj + 3  # 변동성/절감 여지 높음

        save_pct = min(max(save_target_pct + adj, 0), 40)
        reco = int(round(amt * (1 - save_pct / 100)))

        rows.append(
            {
                "카테고리": cat,
                "현재 지출": int(amt),
                "권장 예산": reco,
                "절감 목표": int(amt - reco),
                "절감률": f"{save_pct:.0f}%",
            }
        )

    out = pd.DataFrame(rows)
    # 절감 목표 큰 순
    out = out.sort_values("절감 목표", ascending=False).reset_index(drop=True)
    return out


def df_to_markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "표시할 데이터가 없습니다."
    return df.to_markdown(index=False)


# =========================
# 2) 사이드바: 업로드 + 필터
# =========================
uploaded_file = st.sidebar.file_uploader("CSV 또는 Excel 파일 업로드", type=["csv", "xlsx"])

if not uploaded_file:
    st.info("👈 왼쪽 사이드바에서 파일을 업로드해주세요.")
    st.stop()

# 파일 읽기
if uploaded_file.name.endswith(".csv"):
    df_raw = pd.read_csv(uploaded_file)
else:
    df_raw = pd.read_excel(uploaded_file)

df = preprocess(df_raw)

st.success("파일 업로드 성공 🎉")


# 업로드 데이터 미리보기(요구사항)
with st.expander("📌 업로드 데이터 미리보기", expanded=False):
    st.dataframe(df.head(30), width="stretch")


# =========================
# 3) 필터 UI (연도 + 기간 + 체크박스)
# =========================
with st.sidebar:
    st.header("🧩 데이터 필터")

    # 연도 선택
    years = sorted(df["year"].unique().tolist())
    year_options = ["전체"] + [str(y) for y in years]
    selected_year = st.selectbox("📅 연도 선택", options=year_options, index=0)

    if selected_year != "전체":
        y = int(selected_year)
        df_year = df[df["year"] == y].copy()
    else:
        df_year = df.copy()

    # 날짜 필터
    min_date = df_year["date"].min().date()
    max_date = df_year["date"].max().date()

    date_range = st.date_input(
        "🗓️ 기간 선택",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    if len(date_range) == 2:
        start_date, end_date = date_range
        df_filtered = df_year[
            (df_year["date"].dt.date >= start_date) & (df_year["date"].dt.date <= end_date)
        ].copy()
    else:
        df_filtered = df_year.copy()
        start_date, end_date = min_date, max_date

    st.divider()

    # 카테고리 체크박스
    st.subheader("✅ 카테고리 선택")
    all_categories = sorted(df_year["category"].dropna().unique().tolist())

    # 기본: 전체 선택
    if "cat_checked" not in st.session_state:
        st.session_state["cat_checked"] = {c: True for c in all_categories}

    # 새 카테고리 등장 시 반영
    for c in all_categories:
        if c not in st.session_state["cat_checked"]:
            st.session_state["cat_checked"][c] = True

    colA, colB = st.columns(2)
    half = (len(all_categories) + 1) // 2
    left_cats = all_categories[:half]
    right_cats = all_categories[half:]

    with colA:
        for c in left_cats:
            st.session_state["cat_checked"][c] = st.checkbox(
                c, value=st.session_state["cat_checked"][c], key=f"cat_{c}"
            )
    with colB:
        for c in right_cats:
            st.session_state["cat_checked"][c] = st.checkbox(
                c, value=st.session_state["cat_checked"][c], key=f"cat2_{c}"
            )

    selected_categories = [c for c, v in st.session_state["cat_checked"].items() if v]
    df_filtered = df_filtered[df_filtered["category"].isin(selected_categories)].copy()

    st.divider()

    # 결제수단(멀티 선택 유지)
    st.subheader("💳 결제수단 선택")
    pay_opts = sorted(df_year["payment_method"].dropna().unique().tolist())
    selected_pay = st.multiselect("결제수단", options=pay_opts, default=pay_opts)
    df_filtered = df_filtered[df_filtered["payment_method"].isin(selected_pay)].copy()

    st.divider()

    # 금액 범위(데이터 기반)
    st.subheader("💰 금액 범위 선택")
    if not df_year.empty:
        min_amt = int(df_year["amount"].min())
        max_amt = int(df_year["amount"].max())
        # step 너무 작으면 UX 안좋아서 적당히 자동
        step = max(1000, int((max_amt - min_amt) / 200) if (max_amt - min_amt) > 0 else 1000)
    else:
        min_amt, max_amt, step = 0, 0, 1000

    amount_range = st.slider(
        "금액 범위",
        min_value=min_amt,
        max_value=max_amt,
        value=(min_amt, max_amt),
        step=step,
    )
    df_filtered = df_filtered[
        (df_filtered["amount"] >= amount_range[0]) & (df_filtered["amount"] <= amount_range[1])
    ].copy()

    st.divider()

    # 예산 추천 목표(%) - 계산 결과(표)에 반영
    st.subheader("🧾 맞춤형 예산 추천 설정")
    save_target_pct = st.slider("전체 절감 목표(%)", min_value=0, max_value=30, value=10, step=1)


# =========================
# 4) KPI(대시보드 느낌 + 전월/전기 대비)
# =========================
st.markdown("## 📌 핵심 지표")

total_expense = int(df_filtered["amount"].sum()) if not df_filtered.empty else 0
avg_expense = int(df_filtered["amount"].mean()) if not df_filtered.empty else 0
max_expense = int(df_filtered["amount"].max()) if not df_filtered.empty else 0
transaction_count = int(len(df_filtered))

# 전기(직전 기간) 비교
#df_prev = calc_previous_period(df_year, start_date, end_date)
df_prev = calc_previous_period(df, start_date, end_date)
prev_total = int(df_prev["amount"].sum()) if not df_prev.empty else 0
prev_avg = int(df_prev["amount"].mean()) if not df_prev.empty else 0
prev_max = int(df_prev["amount"].max()) if not df_prev.empty else 0
prev_cnt = int(len(df_prev))

def pct_change(curr, prev):
    if prev == 0:
        return None
    return (curr - prev) / prev * 100

total_delta = pct_change(total_expense, prev_total)
avg_delta = pct_change(avg_expense, prev_avg)
max_delta = pct_change(max_expense, prev_max)
cnt_delta = pct_change(transaction_count, prev_cnt)

k1, k2, k3, k4 = st.columns(4)
with k1:
    build_kpi_card("총 지출", total_expense, total_delta)
with k2:
    build_kpi_card("평균 지출", avg_expense, avg_delta)
with k3:
    build_kpi_card("최대 지출", max_expense, max_delta)
with k4:
    # 거래건수는 원이 아니라서 텍스트 카드로 처리
    delta_html = "<span style='color:#6b7280;font-size:13px;'>전기 대비: -</span>"
    if cnt_delta is not None:
        arrow = "▲" if cnt_delta >= 0 else "▼"
        color = "#ef4444" if cnt_delta >= 0 else "#22c55e"
        delta_html = f"<span style='color:{color};font-size:13px;font-weight:700;'>{arrow} {abs(cnt_delta):.1f}%</span>"
    st.markdown(
        f"""
        <div style="
            border:1px solid #e5e7eb;
            border-radius:16px;
            padding:16px 16px 14px 16px;
            background:#ffffff;
            box-shadow:0 1px 8px rgba(0,0,0,0.04);
            ">
            <div style="color:#374151;font-size:14px;font-weight:700;margin-bottom:6px;">거래 건수</div>
            <div style="font-size:28px;font-weight:800;letter-spacing:-0.5px;margin-bottom:6px;">{transaction_count:,}건</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

# YoY(선택 범위가 단일 월일 때만)
df_yoy = calc_yoy_if_single_month(df_year, df_filtered)
if df_yoy is not None:
    yoy_total = int(df_yoy["amount"].sum()) if not df_yoy.empty else 0
    yoy_delta = pct_change(total_expense, yoy_total)

    st.markdown("")
    if yoy_delta is None:
        st.info("📌 전년 동월 데이터가 없어서 전년 동월 대비(YoY)는 표시되지 않습니다.")
    else:
        arrow = "▲" if yoy_delta >= 0 else "▼"
        color = "#ef4444" if yoy_delta >= 0 else "#22c55e"
        st.markdown(
            f"📌 **전년 동월 대비(YoY)**: <span style='color:{color};font-weight:800;'>{arrow} {abs(yoy_delta):.1f}%</span>",
            unsafe_allow_html=True,
        )

st.divider()


# =========================
# 5) 차트(대시보드 영역)
# =========================
st.markdown("## 📈 지출 분석")

left, right = st.columns(2)

with left:
    st.markdown("### 🥧 카테고리별 지출")
    category_sum = (
        df_filtered.groupby("category")["amount"].sum().reset_index().sort_values("amount", ascending=False)
        if not df_filtered.empty
        else pd.DataFrame({"category": [], "amount": []})
    )

    fig_pie = px.pie(category_sum, values="amount", names="category", hole=0.55)
    fig_pie.update_traces(textposition="inside", textinfo="percent+label")
    st.plotly_chart(fig_pie, width="stretch")

with right:
    st.markdown("### 📉 월별 지출 추이")
    monthly_sum = (
        df_filtered.groupby("year_month", as_index=False)["amount"].sum().sort_values("year_month")
        if not df_filtered.empty
        else pd.DataFrame({"year_month": [], "amount": []})
    )
    monthly_sum["year_month_str"] = monthly_sum["year_month"].astype(str)

    fig_line = px.line(monthly_sum, x="year_month_str", y="amount", markers=True)
    fig_line.update_layout(xaxis_title="월", yaxis_title="지출 금액(원)")
    st.plotly_chart(fig_line, width="stretch")


st.divider()


# =========================
# 6) 맞춤형 예산 추천(기능: 표/계산 결과)
# =========================
st.markdown("## 📊 맞춤형 예산 추천")

budget_df = compute_budget_reco(df_filtered, save_target_pct=save_target_pct)

if budget_df.empty:
    st.info("현재 필터 조건에서 예산 추천을 계산할 데이터가 없습니다.")
else:
    # 표 가독성 개선(원 포맷 + 절감 목표 강조)
    show_df = budget_df.copy()
    show_df["현재 지출"] = show_df["현재 지출"].apply(format_won)
    show_df["권장 예산"] = show_df["권장 예산"].apply(format_won)
    show_df["절감 목표"] = show_df["절감 목표"].apply(format_won)

    st.dataframe(show_df, width="stretch", hide_index=True)

    # 요약
    total_now = int(budget_df["현재 지출"].replace(",", "", regex=True).replace("원", "", regex=True).astype(int).sum()) \
        if "현재 지출" in budget_df.columns else int(df_filtered["amount"].sum())
    total_reco = int(budget_df["권장 예산"].sum())
    total_save = int(budget_df["절감 목표"].sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("현재 총 지출", format_won(int(df_filtered["amount"].sum())))
    c2.metric("권장 총 예산", format_won(total_reco))
    c3.metric("예상 절감액", format_won(total_save))

# 리포트에서도 쓰려고 저장
st.session_state["budget_table"] = budget_df


st.divider()


# =========================
# 7) AI 소비 분석(고급 프롬프트 + 3탭 + 안내문구 + 리포트 연동)
# =========================
st.markdown("## 🤖 AI 소비 분석")

def build_ai_payload(df_filtered: pd.DataFrame) -> dict:
    total = int(df_filtered["amount"].sum()) if not df_filtered.empty else 0
    avg = int(df_filtered["amount"].mean()) if not df_filtered.empty else 0
    mx = int(df_filtered["amount"].max()) if not df_filtered.empty else 0
    cnt = int(len(df_filtered))

    by_cat = (
        df_filtered.groupby("category")["amount"].agg(["sum", "count"]).reset_index()
        if not df_filtered.empty
        else pd.DataFrame(columns=["category", "sum", "count"])
    )
    if total > 0 and not by_cat.empty:
        by_cat["percentage"] = (by_cat["sum"] / total * 100).round(1)
    else:
        by_cat["percentage"] = 0.0

    monthly = (
        df_filtered.groupby("year_month", as_index=False)["amount"].sum().sort_values("year_month")
        if not df_filtered.empty
        else pd.DataFrame({"year_month": [], "amount": []})
    )
    monthly["year_month"] = monthly["year_month"].astype(str)

    payload = {
        "기간": {"시작": str(start_date), "종료": str(end_date)},
        "요약": {"총지출": total, "평균지출": avg, "최대지출": mx, "거래건수": cnt},
        "카테고리별": by_cat.to_dict("records"),
        "월별": monthly.to_dict("records"),
    }
    return payload


def get_ai_insights_advanced(payload: dict) -> dict:
    """
    AI가 '패턴/절약/예산'을 각각 따로 반환하도록 JSON 강제
    """
    if client is None:
        return {
            "error": "OPENAI_API_KEY가 설정되지 않았습니다. (Streamlit Cloud: secrets / 로컬: 환경변수 설정 필요)",
        }

    prompt = f"""
당신은 매우 꼼꼼한 개인 재무 분석가입니다.
아래 입력 데이터(지출 요약/카테고리별/월별)를 바탕으로,
사용자가 바로 행동할 수 있도록 "구체적인 수치"와 "우선순위"를 포함해서 분석하세요.

반드시 아래 JSON 형식으로만 답하세요. (설명 문장 추가 금지)
- 패턴_분석: 핵심 관찰 4~6개(불릿), 급증/급감 월이나 카테고리 언급, 이상치 가능성도 언급
- 절약_영역: (1)상위 절약 후보 3~5개, (2)각 후보별 '권장 절감액(원)'과 '왜' (3)실행 팁 1~2개
- 예산_제안: 다음 달 카테고리별 권장 예산(원) 리스트 + 총 권장 예산 + 예상 절감액
- 요약_한줄: 대시보드 상단에 넣을 한 줄 요약 문장(한국어)
- 주의사항: 과도한 단정 피하고, 데이터의 한계 1~2줄

JSON 스키마(예시):
{{
  "요약_한줄": "...",
  "패턴_분석": ["...", "..."],
  "절약_영역": [
    {{"카테고리": "...", "권장_절감액": 12345, "근거": "...", "실행팁": ["...", "..."]}}
  ],
  "예산_제안": {{
    "카테고리별": [{{"카테고리":"...", "권장예산":12345}}],
    "총_권장예산": 12345,
    "예상_절감액": 12345
  }},
  "주의사항": ["...", "..."]
}}

입력 데이터(JSON):
{json.dumps(payload, ensure_ascii=False)}
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 친절하지만 매우 꼼꼼한 개인 재무 분석가입니다. 반드시 JSON만 출력합니다."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
            temperature=0.4,
        )
        text = res.choices[0].message.content.strip()

        # 혹시 코드블록으로 오면 제거
        if text.startswith("```"):
            text = text.strip("`")
            # 그래도 안전하게 첫 {부터 마지막 }까지
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                text = text[start : end + 1]

        data = json.loads(text)
        return data
    except Exception as e:
        return {"error": str(e)}


# AI 버튼 + 탭
tab1, tab2, tab3 = st.tabs(["📌 패턴 분석", "💡 절약 영역", "🧾 예산 제안"])

# 버튼은 탭 위에 배치(UX 개선)
btn_col1, btn_col2 = st.columns([1, 3])
with btn_col1:
    run_ai = st.button("🔍 AI 분석 시작", type="primary")
with btn_col2:
    st.caption("※ AI 분석 결과는 리포트 생성 시 자동으로 포함됩니다.")

if run_ai:
    with st.spinner("AI가 지출 패턴을 분석하고 있습니다..."):
        payload = build_ai_payload(df_filtered)
        ai_data = get_ai_insights_advanced(payload)
        st.session_state["ai_result"] = ai_data

ai_result = st.session_state.get("ai_result", None)

with tab1:
    if not ai_result:
        st.info("AI 분석을 실행하면 여기에 결과가 표시됩니다 🙂")
    elif "error" in ai_result:
        st.error(f"AI 분석 오류: {ai_result['error']}")
    else:
        st.markdown(f"**{ai_result.get('요약_한줄','')}**")
        st.markdown("### 1) 지출 패턴 분석")
        for item in ai_result.get("패턴_분석", []):
            st.write(f"• {item}")

        st.markdown("### 2) 주의사항")
        for w in ai_result.get("주의사항", []):
            st.write(f"• {w}")

with tab2:
    st.markdown("AI 분석 결과 중 **절약 가능 영역**을 참고하세요.")  # 사용자님 요청 문구 ✅
    if not ai_result:
        st.info("AI 분석을 실행하면 여기에 결과가 표시됩니다 🙂")
    elif "error" in ai_result:
        st.error(f"AI 분석 오류: {ai_result['error']}")
    else:
        st.markdown("### 1) 절약 가능 영역")
        items = ai_result.get("절약_영역", [])
        if not items:
            st.warning("절약 영역 결과가 비어있습니다. (프롬프트/응답 형식 문제일 수 있어요)")
        else:
            for it in items:
                cat = it.get("카테고리", "-")
                save_amt = it.get("권장_절감액", 0)
                reason = it.get("근거", "")
                tips = it.get("실행팁", [])
                st.markdown(f"**- {cat}**: 권장 절감액 **{format_won(save_amt)}**")
                if reason:
                    st.write(f"  - 근거: {reason}")
                if tips:
                    st.write("  - 실행 팁:")
                    for t in tips:
                        st.write(f"    • {t}")

with tab3:
    st.markdown("AI 제안 예산을 아래 **예산표**와 비교하세요.")  # 사용자님 요청 문구 ✅
    if not ai_result:
        st.info("AI 분석을 실행하면 여기에 결과가 표시됩니다 🙂")
    elif "error" in ai_result:
        st.error(f"AI 분석 오류: {ai_result['error']}")
    else:
        bud = ai_result.get("예산_제안", {})
        st.markdown("### 1) AI 예산 제안")
        cat_list = bud.get("카테고리별", [])
        if cat_list:
            ai_budget_df = pd.DataFrame(cat_list)
            if "권장예산" in ai_budget_df.columns:
                ai_budget_df["권장예산"] = ai_budget_df["권장예산"].apply(format_won)
            st.dataframe(ai_budget_df, width="stretch", hide_index=True)
        else:
            st.warning("예산 제안 데이터가 비어있습니다.")

        st.markdown(f"**총 권장 예산:** {format_won(bud.get('총_권장예산', 0))}")
        st.markdown(f"**예상 절감액:** {format_won(bud.get('예상_절감액', 0))}")


st.divider()


# =========================
# 8) 월간 리포트(요약/카테고리/주요지출/AI/예산추천 전부 포함)
# =========================
st.markdown("## 🧾 월간 리포트")

def generate_monthly_report(df_filtered: pd.DataFrame, ai_result: dict | None, budget_df: pd.DataFrame | None) -> str:
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

    total = int(df_filtered["amount"].sum()) if not df_filtered.empty else 0
    avg = int(df_filtered["amount"].mean()) if not df_filtered.empty else 0
    mx = int(df_filtered["amount"].max()) if not df_filtered.empty else 0
    cnt = int(len(df_filtered))

    # 전기 대비(동일 길이 직전기간)
    df_prev_local = calc_previous_period(df_year, start_date, end_date)
    prev_total_local = int(df_prev_local["amount"].sum()) if not df_prev_local.empty else 0
    mom = pct_change(total, prev_total_local)

    mom_txt = "-" if mom is None else f"{mom:+.1f}%"

    # 카테고리 분석
    cat = (
        df_filtered.groupby("category")["amount"].sum().sort_values(ascending=False)
        if not df_filtered.empty
        else pd.Series(dtype=int)
    )
    cat_df = (
        pd.DataFrame({"카테고리": cat.index, "금액": cat.values})
        if not cat.empty
        else pd.DataFrame(columns=["카테고리", "금액"])
    )
    if not cat_df.empty and total > 0:
        cat_df["비율"] = (cat_df["금액"] / total * 100).round(1).astype(str) + "%"
    else:
        cat_df["비율"] = ""

    # 상위 5개
    top5 = (
        df_filtered.sort_values("amount", ascending=False).head(5)[["date", "category", "description", "amount"]]
        if not df_filtered.empty
        else pd.DataFrame(columns=["date", "category", "description", "amount"])
    )
    if not top5.empty:
        top5["date"] = top5["date"].dt.strftime("%Y-%m-%d")
        top5["amount"] = top5["amount"].apply(format_won)

    # 예산 추천
    budget_md = "예산 추천 데이터가 없습니다."
    if budget_df is not None and not budget_df.empty:
        bud_show = budget_df.copy()
        bud_show["현재 지출"] = bud_show["현재 지출"].apply(format_won)
        bud_show["권장 예산"] = bud_show["권장 예산"].apply(format_won)
        bud_show["절감 목표"] = bud_show["절감 목표"].apply(format_won)
        budget_md = df_to_markdown_table(bud_show[["카테고리", "현재 지출", "권장 예산", "절감 목표", "절감률"]])

    # AI 인사이트(리포트에 포함)
    ai_md = "AI 분석 결과가 없습니다. (AI 분석을 먼저 실행해주세요)"
    if ai_result and "error" not in ai_result:
        pattern_lines = "\n".join([f"- {x}" for x in ai_result.get("패턴_분석", [])])
        save_lines = ""
        for it in ai_result.get("절약_영역", []):
            save_lines += f"- **{it.get('카테고리','-')}**: 권장 절감액 {format_won(it.get('권장_절감액',0))} / 근거: {it.get('근거','')}\n"
        bud = ai_result.get("예산_제안", {})
        bud_lines = "\n".join(
            [f"- {x.get('카테고리','-')}: {format_won(x.get('권장예산',0))}" for x in bud.get("카테고리별", [])]
        )
        ai_md = f"""
**한 줄 요약**: {ai_result.get('요약_한줄','')}

### 1) 지출 패턴 분석
{pattern_lines if pattern_lines else "- (데이터 없음)"}

### 2) 절약 가능 영역
{save_lines if save_lines else "- (데이터 없음)"}

### 3) AI 예산 제안
{bud_lines if bud_lines else "- (데이터 없음)"}

**총 권장 예산**: {format_won(bud.get('총_권장예산',0))}  
**예상 절감액**: {format_won(bud.get('예상_절감액',0))}
"""

    report = f"""
# 📊 월간 지출 리포트
생성일: {now}

---

## 📌 요약
- 총 지출: {format_won(total)}
- 평균 지출: {format_won(avg)}
- 최대 지출: {format_won(mx)}
- 거래 건수: {cnt:,}건
- 전기 대비 변화: {mom_txt}

---

## 🧩 카테고리 분석
{df_to_markdown_table(cat_df.assign(금액=cat_df["금액"].apply(format_won)))}

---

## 🔝 주요 지출(상위 5개)
{df_to_markdown_table(top5) if not top5.empty else "표시할 데이터가 없습니다."}

---

## 🤖 AI 인사이트
{ai_md}

---

## 💡 예산 추천
{budget_md}
"""
    return report


if st.button("📄 리포트 생성"):
    report = generate_monthly_report(
        df_filtered=df_filtered,
        ai_result=st.session_state.get("ai_result", None),
        budget_df=st.session_state.get("budget_table", None),
    )

    st.markdown("### 📋 월간 지출 리포트")
    st.markdown(report)

    st.download_button(
        label="📥 리포트 다운로드 (Markdown)",
        data=report,
        file_name=f"expense_report_{pd.Timestamp.now().strftime('%Y%m%d')}.md",
        mime="text/markdown",
    )