from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="연습 문의 목록", layout="wide")

# 이 파일 옆 data 폴더의 CSV 를 읽는다 (어느 폴더에서 실행해도 같은 파일을 찾는다)
CSV_PATH = Path(__file__).parent / "data" / "56_practice-inquiries.csv"

st.title("연습 문의 목록")

inquiries = pd.read_csv(CSV_PATH, encoding="utf-8")
st.caption(f"{CSV_PATH.name} · {len(inquiries)}건")

# 필터: type 열 값으로 거른다. 처음에는 전체가 보인다
type_choice = st.selectbox("유형", ["전체"] + list(inquiries["type"].unique()))
if type_choice == "전체":
    shown = inquiries
else:
    shown = inquiries[inquiries["type"] == type_choice]

# 필터: status 열 값으로 한 번 더 거른다. 두 필터가 모두 맞는 줄만 남는다
status_choice = st.selectbox("상태", ["전체"] + list(inquiries["status"].unique()))
if status_choice != "전체":
    shown = shown[shown["status"] == status_choice]

st.write(f"보이는 줄 수: {len(shown)}")

# 결과 자리: 거른 CSV 내용을 표로 보여 준다
st.dataframe(
    shown,
    hide_index=True,
    width="stretch",
    column_config={
        "date": st.column_config.TextColumn("날짜"),
        "type": st.column_config.TextColumn("유형"),
        "message": st.column_config.TextColumn("내용", width="large"),
        "status": st.column_config.TextColumn("상태"),
    },
)
