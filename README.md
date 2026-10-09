# 급식 식단·레시피·구매량 계산기 (부천시어린이·사회복지급식관리지원센터)

식단(센터 표준 레시피)을 고르고 대상별 인원을 넣으면 식재료 구매량·발주서·레시피 카드·식단표가 자동으로 나오는 Streamlit 앱.

- `app.py` 화면 · `calc.py` 계산 엔진·엑셀 · `pricing.py` 시장조사 단가 매칭 · `waste.py` 폐기율 기본값
- `db_dishes.csv` / `db_ingredients.csv` 2026-09 표준 레시피 DB (18개 식단유형, 음식 3,957개)
- `db_prices.csv` 센터 시장조사 단가(원/kg) — 새 물가 파일이 오면 `python build_prices.py <엑셀> 2026` 로 갱신
- Secrets: `ACCESS_CODE`(기관 코드, 쉼표 구분) · `ADMIN_CODE` · `GEMINI_API_KEY`(선택, AI 레시피 초안) · `LOG_WEBHOOK_URL`(선택)
