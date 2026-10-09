# -*- coding: utf-8 -*-
"""급식 식단·레시피·구매량 계산기 — 부천시어린이·사회복지급식관리지원센터
식단(센터 표준 레시피 DB) → 대상별 인원 입력 → 식재료 구매량·발주서·레시피 카드 자동 산출."""
import datetime as _dt
import json
import threading
import urllib.request

import pandas as pd
import streamlit as st

import calc as C
import pricing as P

st.set_page_config(page_title="급식 식단·구매량 계산기", page_icon="🧮", layout="wide")
CENTER = "부천시어린이·사회복지급식관리지원센터"


def _secret(name, default=""):
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # noqa: BLE001
        return default


ACCESS_CODES = [c.strip() for c in _secret("ACCESS_CODE", "").split(",") if c.strip()]
ADMIN_CODES = [c.strip() for c in _secret("ADMIN_CODE", "").split(",") if c.strip()]
GEMINI_KEY = _secret("GEMINI_API_KEY", "").strip()
LOG_WEBHOOK_URL = _secret("LOG_WEBHOOK_URL", "").strip()

st.title("🧮 급식 식단·레시피·구매량 계산기")
st.caption(f"{CENTER} · 센터 표준 레시피 기준 · 식단과 인원만 넣으면 식재료 구매량·발주서·레시피 카드가 나옵니다")

# ── 로그인 ──
if ACCESS_CODES and not st.session_state.get("user"):
    st.info("🔒 부천시 어린이집·지역아동센터·사회복지시설 전용입니다. 센터에서 안내받은 **접속 코드**와 담당자 정보를 입력하세요.")
    with st.form("login"):
        code = st.text_input("접속 코드 *", type="password")
        c1, c2 = st.columns(2)
        org = c1.text_input("기관명 *", placeholder="예: ○○어린이집 / ○○노인복지관")
        name = c2.text_input("담당자 성명 *", placeholder="예: 홍길동")
        ok = st.form_submit_button("입장", use_container_width=True)
    if ok:
        if code.strip() in ACCESS_CODES or code.strip() in ADMIN_CODES:
            if not org.strip() or not name.strip():
                st.error("기관명과 담당자 성명을 입력하세요.")
            else:
                st.session_state.user = {"org": org.strip(), "name": name.strip(), "admin": code.strip() in ADMIN_CODES}
                st.rerun()
        else:
            st.error("접속 코드가 올바르지 않습니다.")
    st.stop()
USER = st.session_state.get("user", {"org": "(테스트)", "name": "", "admin": True})

dishes, ings = C.load_db()
MONTHS = sorted(dishes["월"].unique())

# ── 1. 식단 선택 ──
st.markdown("### 1️⃣ 식단 선택")
c1, c2, c3 = st.columns([1.2, 1, 1])
group = c1.radio("시설 구분", ["어린이집", "기타시설(지역아동센터 등)", "사회복지시설"], horizontal=True)
month = c2.selectbox("식단 월", MONTHS, index=len(MONTHS) - 1)
G = dishes[(dishes["시설군"] == group) & (dishes["월"] == month)]

portions = []   # (식단유형, 환산인원, 라벨)
menu_types_for_table = []
if group == "어린이집":
    base = c3.selectbox("식단 형태", ["일반형", "오전간식과일형", "오전간식죽식형"])
    st.markdown("### 2️⃣ 인원 입력")
    k1, k2, k3, k4 = st.columns(4)
    n12 = k1.number_input("만 1~2세 (명)", 0, 500, 0)
    n35 = k2.number_input("만 3~5세 (명)", 0, 500, 0)
    nstaff = k3.number_input("교직원 (명)", 0, 100, 0, help="만3~5세 분량 × 성인 계수로 환산")
    staff_coef = k4.number_input("성인 환산 계수", 1.0, 2.0, 1.5, 0.1, help="성인 1명 = 유아 분량의 몇 배인지. 센터 기준 1.5")
    k5, k6, k7, k8 = st.columns(4)
    night = k5.checkbox("야간연장 석식 포함")
    n_night = k6.number_input("야간연장 아동 (명)", 0, 500, 0) if night else 0
    n_bf = {}
    with k7:
        with st.expander("이유식 인원 (해당 시)"):
            for stg in ["초기", "중기", "후기"]:
                n_bf[stg] = st.number_input(f"이유식 {stg} (명)", 0, 100, 0, key=f"bf_{stg}")
    t12, t35 = f"어린이집 만1~2세 {base}", f"어린이집 만3~5세 {base}"
    if n12:
        portions.append((t12, n12, t12))
    if n35 or nstaff:
        portions.append((t35, n35 + round(nstaff * staff_coef), t35))
    if night and n_night:
        # 야간연장 석식은 만3~5세 분량 기준
        portions.append(("어린이집 만3~5세 야간연장형", n_night, "어린이집 만3~5세 야간연장형"))
    for stg, n in n_bf.items():
        if n:
            portions.append((f"어린이집 이유식 {stg}", n, f"어린이집 이유식 {stg}"))
elif group == "기타시설(지역아동센터 등)":
    kind = c3.selectbox("식단 형태", ["지역아동센터 일반형 (석식+오후간식)", "지역아동센터 찬추가형 (석식+오후간식)", "조·중·석식형 (만6~18세, 그룹홈·쉼터 등)"])
    st.markdown("### 2️⃣ 인원 입력")
    k1, k2, k3 = st.columns(3)
    nkid = k1.number_input("아동·청소년 (명)", 0, 500, 0)
    nstaff = k2.number_input("교직원 (명)", 0, 100, 0)
    staff_coef = k3.number_input("성인 환산 계수", 1.0, 2.0, 1.2, 0.1)
    t = {"지역아동센터 일반형 (석식+오후간식)": "아동식 간식 일반형(만6~11세, 지역아동센터)", "지역아동센터 찬추가형 (석식+오후간식)": "아동식 찬추가형(만6~11세, 지역아동센터)"}.get(kind, "아동식 조·중·석식형(만6~18세, 기타시설)")
    if nkid or nstaff:
        portions.append((t, nkid + round(nstaff * staff_coef), t))
else:
    k0a, k0b = c3.columns(2)
    style = k0a.selectbox("급식 형태", ["조·중·석식형 (노인복지시설)", "중·석식형 (재가노인복지시설)"])
    diet = k0b.selectbox("식종", ["일반식", "저염저당식"])
    st.markdown("### 2️⃣ 인원 입력")
    k1, k2, k3 = st.columns(3)
    nold = k1.number_input("어르신 (명)", 0, 1000, 0)
    nstaff = k2.number_input("직원 (명)", 0, 200, 0)
    staff_coef = k3.number_input("직원 환산 계수", 1.0, 2.0, 1.2, 0.1)
    t = f"{diet} {'조·중·석식형(노인복지시설)' if style.startswith('조') else '중·석식형(재가노인복지시설)'}"
    if nold or nstaff:
        portions.append((t, nold + round(nstaff * staff_coef), t))

menu_types_for_table = [p[0] for p in portions]
if not portions:
    st.warning("인원을 입력하면 아래에 식단표와 구매량이 계산됩니다.")
    st.stop()

# ── 3. 기간·끼니 ──
st.markdown("### 3️⃣ 기간과 끼니")
k1, k2, k3 = st.columns([1, 2, 2])
mode = k1.radio("기간", ["하루", "주차", "날짜 선택"])
all_days = sorted(G[G["식단유형"].isin(menu_types_for_table)]["일"].unique().tolist())
weeks = sorted(G[G["식단유형"].isin(menu_types_for_table)]["주차"].unique().tolist())
if mode == "하루":
    d = k2.selectbox("날짜", all_days, format_func=lambda x: f"{month[-2:]}월 {x}일 ({C.weekday_of(month, x)})")
    days = [d]
elif mode == "주차":
    w = k2.selectbox("주차", weeks)
    days = sorted(G[(G["식단유형"].isin(menu_types_for_table)) & (G["주차"] == w)]["일"].unique().tolist())
else:
    days = k2.multiselect("날짜 (복수 선택)", all_days, default=all_days[:5], format_func=lambda x: f"{x}일({C.weekday_of(month, x)})")
avail_meals = [m for m in C.MEAL_ORDER if m in set(G[G["식단유형"].isin(menu_types_for_table)]["끼니"])]
meals = k3.multiselect("끼니", avail_meals, default=avail_meals)
if not days or not meals:
    st.stop()

# ── AI/직접 메뉴 추가 ──
with st.expander("➕ 식단에 없는 메뉴 추가 (직접 입력 또는 AI 레시피 초안)"):
    st.caption("센터 식단표에 없는 메뉴를 넣을 때 씁니다. AI 초안은 반드시 영양사가 분량을 확인하세요.")
    e1, e2, e3, e4 = st.columns([2, 1, 1, 1])
    ex_name = e1.text_input("메뉴명", placeholder="예: 닭가슴살샐러드")
    ex_type = e2.selectbox("적용 대상", menu_types_for_table, format_func=C.short)
    ex_day = e3.selectbox("일", days, key="ex_day")
    ex_meal = e4.selectbox("끼니", meals, key="ex_meal")
    ex_txt = st.text_area("재료와 1인 분량 (한 줄에 하나: 재료명, g)", placeholder="닭가슴살, 40\n양상추, 20\n방울토마토, 15", height=100)
    b1, b2 = st.columns(2)
    if GEMINI_KEY and b1.button("🤖 AI로 1인 분량 초안 만들기", use_container_width=True) and ex_name.strip():
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_KEY, vertexai=GEMINI_KEY.startswith("AQ."))
            tgt = C.short(ex_type)
            q = (f"급식 표준 레시피 작성. 메뉴: {ex_name}. 대상: {tgt}. 센터 급식 1인 제공량 기준으로 재료와 1인 분량(g)을 "
                 f"'재료명, g' 형식으로 한 줄에 하나씩만 출력. 설명·단위·번호 없이. 양념 포함 6~12줄.")
            r = client.models.generate_content(model="gemini-3.5-flash-lite", contents=q)
            st.session_state.ex_draft = r.text.strip()
        except Exception as e:  # noqa: BLE001
            st.error(f"AI 초안 실패: {e}")
    if st.session_state.get("ex_draft"):
        st.code(st.session_state.ex_draft, language=None)
        st.caption("위 초안을 복사해 재료 칸에 붙여넣고 분량을 확인한 뒤 추가하세요.")
    if b2.button("식단에 추가", use_container_width=True) and ex_name.strip() and ex_txt.strip():
        lst = []
        for line in ex_txt.splitlines():
            if "," in line:
                n, g = line.rsplit(",", 1)
                try:
                    lst.append((n.strip(), float(g.strip().replace("g", ""))))
                except ValueError:
                    pass
        persons = next((p[1] for p in portions if p[0] == ex_type), 0)
        st.session_state.setdefault("extra", []).append((ex_type, ex_day, ex_meal, ex_name.strip(), lst, persons))
        st.success(f"'{ex_name}' 추가됨 ({len(lst)}개 재료)")
    if st.session_state.get("extra"):
        st.write("추가된 메뉴:", ", ".join(f"{e[1]}일 {e[2]} {e[3]}" for e in st.session_state.extra))
        if st.button("추가 메뉴 모두 지우기"):
            st.session_state.extra = []
            st.rerun()

# ── 4. 계산 ──
agg, detail = C.compute(G, ings, portions, days, meals, st.session_state.get("extra", []))
if agg.empty:
    st.warning("선택한 기간·끼니에 해당하는 식단이 없습니다.")
    st.stop()

st.markdown("### 4️⃣ 식단표")
menu_df = C.menu_table(G, menu_types_for_table, days, meals, month)
st.dataframe(menu_df, use_container_width=True, height=min(80 + 120 * len(meals), 600))
st.caption("음식명 뒤 번호는 알레르기 유발식품 번호(①달걀 ②우유 ③메밀 ④땅콩 ⑤대두 ⑥밀 ⑦고등어 ⑧게 ⑨새우 ⑩돼지고기 ⑪복숭아 ⑫토마토 ⑬아황산류 ⑭호두 ⑮닭고기 ⑯쇠고기 ⑰오징어 ⑱조개류 ⑲잣)")

st.markdown("### 5️⃣ 식재료 구매량 (발주서)")
total_persons = sum(p[1] for p in portions)
st.info("환산 인원: " + " · ".join(f"{C.short(p[0])} {p[1]}명" for p in portions) + f"  |  기간 {len(days)}일 · 끼니 {', '.join(meals)}")
o1, o2, o3 = st.columns([1, 1.2, 2.8])
margin = o1.number_input("여유율 (%)", 0, 30, 5, help="조리 손실·계량 오차 대비. 구매량 = 정미량 × (1+여유율) ÷ (1−폐기율)")
place = o2.selectbox("단가 기준 (센터 시장조사)", P.PLACES, help="센터가 매월 조사한 식자재마트·대형마트·시장 가격. 조사 품목(채소·과일·수산·육류 약 90종)만 자동 채움")
o3.caption("**단가(원/kg)** 는 센터 시장조사 단가가 자동으로 들어가고(매칭 품목 표시), 조사에 없는 품목(쌀·우유·두부·양념 등)은 직접 입력합니다. "
           "**폐기율%** 기본값은 식품성분표 통상값. 고친 뒤 '구매량 다시 계산'을 누르세요.")
with st.expander("📄 우리 기관 단가표 올리기 (선택) — 엑셀/CSV, 열 이름: 식재료, 단가"):
    up = st.file_uploader("단가표 파일", type=["xlsx", "csv"], label_visibility="collapsed")
    if up is not None:
        try:
            pdf = pd.read_csv(up) if up.name.endswith(".csv") else pd.read_excel(up)
            pdf.columns = [str(c).strip() for c in pdf.columns]
            n = 0
            for _, r in pdf.iterrows():
                nm, pr = str(r.get("식재료", "")).strip(), pd.to_numeric(r.get("단가", None), errors="coerce")
                if nm and pd.notna(pr):
                    st.session_state.setdefault("price_map", {})[nm] = float(pr)
                    n += 1
            st.success(f"{n}개 품목 단가 적용 (같은 이름의 식재료에 우선 적용)")
        except Exception as e:  # noqa: BLE001
            st.error(f"파일을 읽지 못했습니다: {e}")
if "price_map" not in st.session_state:
    st.session_state.price_map = {}
if "waste_map" not in st.session_state:
    st.session_state.waste_map = {}
auto = P.auto_prices(agg["식재료"].tolist(), month, place)
agg["폐기율%"] = agg.apply(lambda r: st.session_state.waste_map.get(r["식재료"], r["폐기율%"]), axis=1)
agg["단가(원/kg)"] = agg["식재료"].map(lambda n: st.session_state.price_map.get(n, float(auto.get(n, (None, 0.0))[1])))
agg["단가출처"] = agg["식재료"].map(lambda n: "직접입력" if n in st.session_state.price_map else (f"시장조사:{auto[n][0]}" if n in auto else ""))
edited = st.data_editor(
    agg[["식재료", "정미량g", "폐기율%", "단가(원/kg)", "단가출처", "사용음식수", "사용음식"]],
    column_config={"정미량g": st.column_config.NumberColumn("정미량(g)", format="%.0f", disabled=True),
                   "폐기율%": st.column_config.NumberColumn("폐기율%", min_value=0, max_value=95, step=1),
                   "단가(원/kg)": st.column_config.NumberColumn("단가(원/kg)", min_value=0, step=100),
                   "단가출처": st.column_config.TextColumn("단가 출처", disabled=True),
                   "사용음식수": st.column_config.NumberColumn("음식수", disabled=True),
                   "사용음식": st.column_config.TextColumn("사용 음식", disabled=True)},
    hide_index=True, use_container_width=True, height=420, key="editor")
matched_w = agg[agg["단가(원/kg)"] > 0]["정미량g"].sum() / max(agg["정미량g"].sum(), 1) * 100
st.caption(f"단가가 들어간 품목: {int((agg['단가(원/kg)'] > 0).sum())}/{len(agg)}개 (중량 기준 {matched_w:.0f}%) — 나머지는 단가를 직접 입력하면 예상 금액에 반영됩니다.")
if st.button("🔁 구매량 다시 계산", type="primary"):
    for _, r in edited.iterrows():
        st.session_state.waste_map[r["식재료"]] = float(r["폐기율%"])
        st.session_state.price_map[r["식재료"]] = float(r["단가(원/kg)"])
    st.rerun()
purchase = C.apply_purchase(edited, margin)
total_cost = float(purchase["금액(원)"].sum())
m1, m2, m3, m4 = st.columns(4)
m1.metric("식재료 품목 수", len(purchase))
m2.metric("총 정미량", f"{purchase['정미량(kg)'].sum():,.1f} kg")
m3.metric("총 구매량", f"{purchase['구매량(kg)'].sum():,.1f} kg")
m4.metric("예상 식재료비", f"{total_cost:,.0f} 원" if purchase["단가(원/kg)"].sum() > 0 else "단가 입력 필요")
# ── 식단가 예산 대비 ──
DEFAULT_PRICE = {"어린이집": 3800, "사회복지시설": 3800, "기타시설(지역아동센터 등)": 7000}
b1, b2, b3, b4 = st.columns(4)
meal_price = b1.number_input("식단가 (원 / 1인·1일)", 0, 20000, DEFAULT_PRICE[group], 100, help="기관의 1인 1일 급식 단가. 어린이집·사회복지 3,800원, 지역아동센터 등 기타시설 7,000~10,000원")
head_count = sum(p[1] for p in portions)
budget = meal_price * head_count * len(days)
b2.metric("식단가 예산", f"{budget:,.0f} 원", help=f"식단가 {meal_price:,}원 × 환산인원 {head_count}명 × {len(days)}일")
ratio = (total_cost / budget * 100) if budget else 0
b3.metric("예산 대비 식재료비", f"{ratio:.0f} %" if total_cost else "-", help="단가가 들어간 품목만 합산한 값이라 실제보다 낮게 나올 수 있음")
b4.metric("1인 1일 식재료비", f"{total_cost / head_count / len(days):,.0f} 원" if total_cost and head_count else "-")
if total_cost and budget and ratio > 70:
    st.warning(f"식재료비가 식단가의 {ratio:.0f}%입니다. 통상 식재료비 비중(50~65%)을 넘으니 단가·여유율·메뉴를 확인하세요.")
st.dataframe(purchase[["식재료", "정미량(kg)", "폐기율%", "구매량(kg)", "단가(원/kg)", "금액(원)", "사용음식"]], hide_index=True, use_container_width=True, height=360)

# ── 6. 레시피 카드 ──
st.markdown("### 6️⃣ 레시피 카드 (조리실용)")
cards = C.recipe_cards(detail, G)
for cd in cards:
    with st.expander(f"{cd['일']}일 {cd['끼니']} · {cd['음식명']}{cd['알레르기']} · {C.short(cd['대상'])} {cd['환산인원']}명"):
        st.table(pd.DataFrame([{"식재료": a, "1인분(g)": b, f"{cd['환산인원']}명 총량(g)": c} for a, b, c in cd["재료"]]))
        if cd["조리방법"]:
            st.markdown("**조리방법**  \n" + cd["조리방법"].replace("\n", "  \n"))

# ── 7. 다운로드 + 기록 ──
st.markdown("### 7️⃣ 엑셀 내려받기")
info = {"기관명": USER["org"], "담당자": USER["name"], "시설구분": group, "식단": " + ".join(C.short(p[0]) for p in portions),
        "환산인원": " · ".join(f"{C.short(p[0])} {p[1]}명" for p in portions), "기간": f"{month} {days[0]}일~{days[-1]}일 ({len(days)}일)",
        "끼니": ", ".join(meals), "여유율": f"{margin}%", "작성일시": (_dt.datetime.utcnow() + _dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")}
xlsx = C.to_excel(info, purchase, detail, cards, menu_df)
fname = f"발주서_{USER['org']}_{month}_{days[0]}-{days[-1]}일.xlsx"
if st.download_button("⬇️ 발주서 + 식단표 + 레시피카드 (엑셀)", data=xlsx, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True):
    if LOG_WEBHOOK_URL:
        row = dict(info, 총구매량kg=round(float(purchase["구매량(kg)"].sum()), 2), 예상금액=float(purchase["금액(원)"].sum()), 품목수=len(purchase))
        def _post():
            try:
                req = urllib.request.Request(LOG_WEBHOOK_URL, data=json.dumps(row, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10).read()
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=_post, daemon=True).start()

st.divider()
st.caption(f"⚠️ 구매량은 센터 표준 레시피의 1인 분량과 통상 폐기율로 계산한 참고값입니다. 식재료 규격·업체 포장단위·실제 폐기율에 따라 조정하세요. 식단 변경은 센터 영양사 승인 후 적용합니다. · {CENTER}")
with st.sidebar:
    st.markdown(f"**👤 {USER['org']}** · {USER['name']}")
    if st.button("🚪 로그아웃", use_container_width=True):
        for k in ("user", "extra", "price_map", "waste_map", "ex_draft"):
            st.session_state.pop(k, None)
        st.rerun()
    st.divider()
    st.markdown("**사용 순서**  \n1 식단 선택 → 2 인원 → 3 기간·끼니 → 5 폐기율·단가 확인 → 7 엑셀 내려받기")
    st.caption("레시피 DB: 2026년 9월 센터 표준 레시피 (18개 식단유형, 음식 3,957개)")
