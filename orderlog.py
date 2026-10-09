# -*- coding: utf-8 -*-
"""발주 기록 → 구글 시트(Apps Script 웹훅) 저장·조회 + 관리자 통계 화면."""
import json
import threading
import urllib.request

import pandas as pd
import streamlit as st


def _post(url: str, payload: dict, timeout: int = 20):
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def log_order(url: str, row: dict):
    """비동기 기록 (화면을 막지 않음)."""
    if not url:
        return
    def _run():
        try:
            _post(url, dict(row, action="log"))
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_run, daemon=True).start()


@st.cache_data(ttl=60, show_spinner="구글 시트에서 기록을 불러오는 중…")
def fetch_rows(url: str) -> pd.DataFrame:
    if not url:
        return pd.DataFrame()
    r = _post(url, {"action": "rows"})
    df = pd.DataFrame(r.get("rows", []), columns=r.get("headers", []))
    for c in ("총구매량kg", "예상금액", "품목수", "식단가", "식단가예산", "예산대비%"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "작성일시" in df.columns:
        df["작성일시"] = df["작성일시"].astype(str)
        df["월"] = df["작성일시"].str[:7]
    return df


def refresh_sheet_stats(url: str) -> int:
    r = _post(url, {"action": "stats"})
    return int(r.get("rows", 0))


def admin_panel(url: str):
    st.markdown("### 📊 관리자 통계 (센터 영양사용)")
    if not url:
        st.warning("Streamlit Secrets에 LOG_WEBHOOK_URL 이 없어 기록·통계를 사용할 수 없습니다.")
        return
    c1, c2 = st.columns([1, 3])
    if c1.button("🔄 새로 고침"):
        fetch_rows.clear()
    try:
        df = fetch_rows(url)
    except Exception as e:  # noqa: BLE001
        st.error(f"구글 시트를 읽지 못했습니다: {e}")
        return
    if df.empty:
        st.info("아직 기록이 없습니다. 기관에서 엑셀 발주서를 내려받으면 자동으로 쌓입니다.")
        return

    f1, f2, f3 = st.columns(3)
    months = sorted(df["월"].dropna().unique().tolist())
    sel_m = f1.multiselect("월", months, default=months)
    groups = sorted(df["시설구분"].dropna().unique().tolist())
    sel_g = f2.multiselect("시설구분", groups, default=groups)
    q = f3.text_input("기관명 검색")
    d = df[df["월"].isin(sel_m) & df["시설구분"].isin(sel_g)]
    if q.strip():
        d = d[d["기관명"].astype(str).str.contains(q.strip(), na=False)]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("발주 건수", len(d))
    m2.metric("이용 기관 수", d["기관명"].nunique())
    m3.metric("총 구매량", f"{d['총구매량kg'].sum():,.1f} kg")
    m4.metric("예상 식재료비 합계", f"{d['예상금액'].sum():,.0f} 원")

    t1, t2, t3, t4 = st.tabs(["기관별", "시설구분별", "월별 추이", "전체 기록"])
    def _agg(col):
        g = d.groupby(col).agg(건수=("기관명", "size"), 총구매량kg=("총구매량kg", "sum"), 예상금액=("예상금액", "sum"), 평균예산대비=("예산대비%", "mean")).reset_index()
        g["총구매량kg"] = g["총구매량kg"].round(1)
        g["예상금액"] = g["예상금액"].round(0)
        g["평균예산대비"] = g["평균예산대비"].round(0)
        return g.sort_values("건수", ascending=False)
    with t1:
        st.dataframe(_agg("기관명"), hide_index=True, use_container_width=True)
    with t2:
        g = _agg("시설구분")
        st.dataframe(g, hide_index=True, use_container_width=True)
        st.bar_chart(g.set_index("시설구분")["건수"])
    with t3:
        g = d.groupby("월").agg(건수=("기관명", "size"), 기관수=("기관명", "nunique"), 총구매량kg=("총구매량kg", "sum"), 예상금액=("예상금액", "sum")).reset_index().sort_values("월")
        st.dataframe(g, hide_index=True, use_container_width=True)
        st.line_chart(g.set_index("월")["건수"])
    with t4:
        st.dataframe(d.drop(columns=["월"]).sort_values("작성일시", ascending=False), hide_index=True, use_container_width=True, height=400)
        st.download_button("⬇️ 기록 CSV 내려받기", d.to_csv(index=False).encode("utf-8-sig"), "급식발주기록.csv", "text/csv")

    st.divider()
    if st.button("📑 구글 시트 '통계' 탭 갱신"):
        try:
            n = refresh_sheet_stats(url)
            st.success(f"시트 '통계' 탭을 다시 만들었습니다 (기록 {n}건).")
        except Exception as e:  # noqa: BLE001
            st.error(f"갱신 실패: {e}")
