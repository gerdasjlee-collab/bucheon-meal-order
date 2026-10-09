# -*- coding: utf-8 -*-
"""센터 시장조사 단가(원/kg) → 레시피 식재료명 자동 매칭."""
import re

import pandas as pd
import streamlit as st

PLACES = ["식자재마트", "대형마트", "시장", "3곳 평균"]
# 레시피 식재료 키워드 → 물가 품목 (앞에 있는 규칙 우선)
ALIAS = [
    ("쇠고기", "쇠고기-국거리용"), ("소고기", "쇠고기-국거리용"), ("돼지고기", "돼지고기-앞다리(불고기용)"), ("돼지갈비", "돼지갈비(찜용)"),
    ("닭고기", "닭가슴살"), ("닭_", "닭가슴살"), ("닭,", "닭가슴살"), ("멸치, 대멸치", "국멸치"), ("멸치, 잔", "잔멸치"), ("멸치", "국멸치"),
    ("명태", "동태"), ("포도", "적포도"), ("토마토, 방울", "방울토마토"), ("방울토마토", "방울토마토"), ("토마토", "토마토"),
    ("파_대파", "대파"), ("파, 생것", "대파"), ("파_쪽파", "대파"), ("무, 조선무", "무"), ("무_", "무"), ("무,", "무"),
    ("호박_애호박", "애호박"), ("애호박", "애호박"), ("단호박", "단호박"), ("배추김치", "배추"), ("배추", "배추"), ("양배추", "양배추"), ("양상추", "양상추"),
]


@st.cache_data(show_spinner=False)
def load_prices():
    try:
        p = pd.read_csv("db_prices.csv")
    except FileNotFoundError:
        return pd.DataFrame()
    return p


def price_table(month: str, place: str) -> dict:
    """품목 → 원/kg (해당 월, 조사장소). 값 없으면 그 해 최근 월로 대체."""
    p = load_prices()
    if p.empty:
        return {}
    m = int(month.split("-")[1])
    cols = [f"{k}월" for k in range(m, 0, -1)]
    out = {}
    for item, g in p.groupby("품목"):
        vals = []
        for _, r in g.iterrows():
            if place != "3곳 평균" and r["조사장소"] != place:
                continue
            for c in cols:
                v = r.get(c, "")
                if pd.notna(v) and str(v).strip() not in ("", "-"):
                    try:
                        vals.append(float(v))
                        break
                    except ValueError:
                        pass
        if not vals and place != "3곳 평균":  # 해당 장소에 값이 없으면 평균으로
            for _, r in g.iterrows():
                for c in cols:
                    v = r.get(c, "")
                    if pd.notna(v) and str(v).strip() not in ("", "-"):
                        try:
                            vals.append(float(v))
                            break
                        except ValueError:
                            pass
        if vals:
            out[item] = round(sum(vals) / len(vals))
    return out


EXCLUDE = ["당면", "전분", "가루", "액젓", "젓,", "젓_", "젓갈", "주스", "떡", "소스", "통조림", "건포도", "단무지", "케찹", "케첩", "잼", "과자", "빵", "국수", "우동", "라면", "시럽",
           "즙", "음료", "피클", "장아찌", "절임", "튀김", "너겟", "햄", "소시지", "만두", "어묵", "맛살", "유부", "두부", "묵", "두유", "요구르트", "치즈", "버터", "기름", "식초", "설탕", "소금"]


def match_item(ingredient: str, items: list) -> str | None:
    """레시피 식재료명 → 물가 품목. 가공품(당면·전분·젓갈 등)은 매칭하지 않음."""
    n = str(ingredient)
    if any(x in n for x in EXCLUDE) and "김치" not in n:
        return None
    for kw, item in ALIAS:
        if kw in n and item in items:
            return item
    tokens = [t for t in re.split(r"[,_()\s/]+", n) if t]
    best = None
    for it in items:
        base = it.split("-")[0].split("(")[0].strip()
        if base and base in tokens and (best is None or len(base) > len(best.split("-")[0])):
            best = it
    return best


def auto_prices(ingredients: list, month: str, place: str) -> dict:
    """{식재료: (품목, 원/kg)} — 매칭되는 것만."""
    table = price_table(month, place)
    items = list(table.keys())
    out = {}
    for ing in ingredients:
        it = match_item(ing, items)
        if it:
            out[ing] = (it, table[it])
    return out
