import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="전주 객사 맛집", layout="wide")

# 이 파일 옆 .env 에서 KAKAO_REST_API_KEY 를 읽는다 (KEY=VALUE 줄만, # 줄은 건너뜀)
ENV_PATH = Path(__file__).parent / ".env"

# 카카오 로컬 API: 키워드로 장소 검색 (공식 문서 developers.kakao.com/docs/ko/local/dev-guide 기준)
# 키는 "Authorization: KakaoAK {키}" 헤더로 보낸다. 한 번에 15개, 최대 45개(3쪽)까지 받을 수 있다
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
# 주소 검색(주소로 좌표 변환): 동네·도로 주소 이름을 좌표로 바꾼다
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
FOOD = "FD6"  # 카테고리 그룹 코드: 음식점 (카페는 따로 CE7 이라 여기엔 안 나온다)
PAGE_SIZE = 15

# 찾을 음식 고르는 칸. 카카오에 그대로 검색어로 보낸다
FOODS = ["맛집", "한식", "중식", "일식", "양식", "분식", "국밥", "고기", "치킨", "술집"]

# 반경 고르는 칸 (m). 카카오는 최대 20000m 까지 받는다
RADII = [100, 200, 300, 500, 700, 1000, 1500, 2000]


def read_env(path):
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def kakao(params, api_key, url=KEYWORD_URL):
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={"Authorization": f"KakaoAK {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def find_center(place, api_key):
    # 기준 장소를 카카오에서 찾는다. 화면에 보여 줄 이름·주소는 카카오가 돌려준 값만 쓴다
    # 1) 동네·도로 주소 이름(예: 서신동, 전주객사3길 22)은 주소 검색으로 찾는다
    result = kakao({"query": place, "size": 5}, api_key, ADDRESS_URL)
    if result["documents"]:
        top = result["documents"][0]
        return {
            "name": top["address_name"],
            "address": top["address_name"],
            "how": "주소 검색",
            "matches": result["meta"]["total_count"],
            "x": top["x"],
            "y": top["y"],
        }
    # 2) 역·건물·명소 이름(예: 전주역, 전주 객사)은 키워드 검색으로 찾는다
    result = kakao({"query": place, "size": 5}, api_key)
    if not result["documents"]:
        return None
    top = result["documents"][0]
    return {
        "name": top["place_name"],
        "address": top["road_address_name"] or top["address_name"],
        "how": "장소 검색",
        "matches": result["meta"]["total_count"],
        "x": top["x"],
        "y": top["y"],
    }


def search_food(keyword, center, radius, sort, count, api_key):
    # 기준 좌표 반경 안의 음식점(FD6)을 검색한다. 15개씩 쪽을 넘기며 count 개까지 모은다
    rows = []
    for page in range(1, count // PAGE_SIZE + 1):
        result = kakao(
            {
                "query": keyword,
                "category_group_code": FOOD,
                "x": center["x"],
                "y": center["y"],
                "radius": radius,
                "sort": sort,
                "page": page,
                "size": PAGE_SIZE,
            },
            api_key,
        )
        rows += result["documents"]
        if result["meta"]["is_end"]:
            break
    # 반경 밖 가게가 섞여 와도 걸러 낸다 (거리는 카카오가 준 값)
    return [d for d in rows if d.get("distance") and int(d["distance"]) <= radius]


def to_table(documents):
    # 카카오 응답을 표로 바꾼다. 종류는 "음식점 > 한식 > 국밥" 에서 두 번째 칸(한식)
    table = pd.DataFrame(
        {
            "이름": [d["place_name"] for d in documents],
            "종류": [
                (d["category_name"].split(" > ") + ["기타"])[1] for d in documents
            ],
            "세부 종류": [d["category_name"].split(" > ")[-1] for d in documents],
            "거리(m)": [int(d["distance"]) if d.get("distance") else None for d in documents],
            "전화": [d["phone"] for d in documents],
            "주소": [d["road_address_name"] or d["address_name"] for d in documents],
            "카카오맵": [d["place_url"] for d in documents],
            "lat": [float(d["y"]) for d in documents],
            "lon": [float(d["x"]) for d in documents],
        }
    )
    return table.drop_duplicates(subset=["이름", "주소"])


st.title("전주 객사 맛집 대시보드")
st.caption("카카오 로컬 API 로 기준 장소 근처 음식점을 찾아 봅니다. 검색 버튼을 눌렀을 때만 카카오를 부릅니다.")

api_key = read_env(ENV_PATH).get("KAKAO_REST_API_KEY", "")
if not api_key:
    st.error(".env 에 KAKAO_REST_API_KEY 를 채우면 검색할 수 있어요.")

# 검색 조건: form 안의 값은 검색 버튼을 누를 때만 반영되고, 그때만 카카오를 부른다
with st.form("search"):
    place_col, food_col, own_food_col = st.columns([2, 1, 1])
    with place_col:
        place = st.text_input(
            "기준 장소",
            value="전주 객사",
            help="역이나 동네 이름을 넣으면 카카오에서 그 장소를 찾아 기준으로 씁니다. 예: 전주역, 서신동",
        )
    with food_col:
        food = st.selectbox("찾을 음식", FOODS)
    with own_food_col:
        own_food = st.text_input("직접 입력", placeholder="예: 비빔밥", help="채우면 왼쪽에서 고른 음식 대신 이 말로 찾습니다. 음식점 안에서만 찾습니다.")
    radius_col, sort_col, count_col = st.columns(3)
    with radius_col:
        radius = st.select_slider("반경 (m)", options=RADII, value=500)
    with sort_col:
        sort_label = st.radio("카카오 정렬", ["정확도순", "거리순"], horizontal=True)
    with count_col:
        count = st.select_slider("가져올 개수", options=[15, 30, 45], value=45)
    submitted = st.form_submit_button("검색", type="primary", disabled=not api_key)

if submitted:
    sort = "distance" if sort_label == "거리순" else "accuracy"
    keyword = own_food.strip() or food
    try:
        with st.spinner("카카오에서 찾는 중..."):
            center = find_center(place.strip(), api_key) if place.strip() else None
            if center is None:
                st.warning(f"카카오에서 '{place}' 를 찾지 못했어요. 역이나 동네 이름을 바꿔 보세요.")
            else:
                documents = search_food(keyword, center, radius, sort, count, api_key)
                # 새로 검색하면 지난 뽑기 결과는 지운다
                st.session_state.pop("lunch_pick", None)
                st.session_state.lunch = {
                    "center": center,
                    "keyword": keyword,
                    "radius": radius,
                    "table": to_table(documents),
                }
    except urllib.error.HTTPError as error:
        st.error(f"카카오 호출 실패 ({error.code}): {error.read().decode('utf-8')}")
    except (urllib.error.URLError, TimeoutError) as error:
        st.error(f"카카오에 연결하지 못했어요: {getattr(error, 'reason', error)}")

# 결과: 마지막 검색 결과를 세션에 들고 있어서, 아래 거르기·정렬은 카카오를 다시 부르지 않는다
if "lunch" not in st.session_state:
    st.info("조건을 정하고 검색 버튼을 눌러 주세요.")
    st.stop()

lunch = st.session_state.lunch
table = lunch["table"]
st.subheader(f"{lunch['center']['name']} 반경 {lunch['radius']}m · '{lunch['keyword']}' 검색 결과")

# 기준 장소: 카카오가 실제로 돌려준 이름·주소를 그대로 보여 준다
center = lunch["center"]
place_text = center["name"] if center["name"] == center["address"] else f"{center['name']} · {center['address']}"
st.markdown(f"📍 **기준 장소** : {place_text}  (카카오 {center['how']} 첫 번째 결과)")
# 같은 이름의 동네가 여러 곳이면 알려 준다 (장소 검색은 주변 관련 장소까지 세어서 안내하지 않음)
if center["how"] == "주소 검색" and center["matches"] > 1:
    st.caption(f"같은 이름의 지역이 {center['matches']}곳 있어 첫 번째를 썼어요. 다른 곳이면 시·구 이름까지 넣어 다시 검색해 주세요. (예: 전주 효자동)")
if table.empty:
    st.warning("조건에 맞는 음식점이 없어요. 반경을 넓히거나 찾을 음식을 바꿔 보세요.")
    st.stop()

# 거르기·정렬: 한 줄에 모아 둔다
name_col, kind_col, order_col = st.columns([2, 3, 2])
with name_col:
    name_filter = st.text_input("이름으로 거르기", placeholder="예: 국밥")
with kind_col:
    kinds = sorted(table["종류"].unique())
    kind_filter = st.multiselect("종류", kinds, default=kinds)
with order_col:
    order = st.selectbox("정렬", ["가까운 순", "먼 순", "이름순", "종류순"])

shown = table[table["종류"].isin(kind_filter)]
if name_filter.strip():
    shown = shown[shown["이름"].str.contains(name_filter.strip(), case=False, regex=False)]
order_by = {
    "가까운 순": (["거리(m)"], [True]),
    "먼 순": (["거리(m)"], [False]),
    "이름순": (["이름"], [True]),
    "종류순": (["종류", "거리(m)"], [True, True]),
}[order]
shown = shown.sort_values(order_by[0], ascending=order_by[1])

# 한눈에: 개수 · 가장 가까운 곳 · 평균 거리
count_tile, nearest_tile, average_tile = st.columns(3)
count_tile.metric("보이는 음식점", f"{len(shown)}곳", help=f"검색 결과 {len(table)}곳 중")
if not shown.empty:
    nearest = shown.sort_values("거리(m)").iloc[0]
    nearest_tile.metric(f"가장 가까운 곳 ({nearest['거리(m)']}m)", nearest["이름"])
    average_tile.metric("평균 거리", f"{int(shown['거리(m)'].mean())}m")

if shown.empty:
    st.warning("거르기 조건에 맞는 음식점이 없어요.")
    st.stop()

# 맛집 뽑기: 지금 표에 보이는 가게 안에서 한 곳을 무작위로 고른다 (카카오를 다시 부르지 않음)
if st.button("🎲 맛집 뽑기", help="지금 표에 보이는 가게 중 한 곳을 골라 드려요"):
    st.session_state.lunch_pick = shown.sample(1).iloc[0].to_dict()
pick = st.session_state.get("lunch_pick")
if pick:
    with st.container(border=True):
        st.caption("오늘은 여기 어때요?")
        st.markdown(f"## {pick['이름']}")
        st.markdown(f"### {pick['종류']} · {pick['거리(m)']}m")
        st.markdown(f"{pick['세부 종류']} · {pick['주소']} · [카카오맵에서 보기]({pick['카카오맵']})")

# 차트: 종류별 개수(많은 순) · 거리 구간별 개수(가까운 구간부터)
kind_chart, distance_chart = st.columns(2)
with kind_chart:
    st.markdown("**종류별 음식점 수**")
    by_kind = shown["종류"].value_counts().rename_axis("종류").reset_index(name="음식점 수")
    st.bar_chart(by_kind, x="종류", y="음식점 수", horizontal=True, sort="-음식점 수")
with distance_chart:
    st.markdown("**거리 구간별 음식점 수 (100m 단위)**")
    step = 100
    bins = (shown["거리(m)"] // step * step).astype(int)
    by_distance = (
        bins.value_counts()
        .sort_index()
        .rename_axis("start")
        .reset_index(name="음식점 수")
    )
    by_distance["거리"] = by_distance["start"].map(lambda s: f"{s}~{s + step}m")
    st.bar_chart(by_distance, x="거리", y="음식점 수", sort=False)

# 지도와 표
map_col, table_col = st.columns([2, 3])
with map_col:
    st.markdown("**지도**")
    st.map(shown[["lat", "lon"]], size=12)
with table_col:
    st.markdown("**목록**")
    # 네이버 지도 링크: 가게 이름과 도로명 주소를 띄어 이어 붙여 네이버 지도 검색 주소로 만든다 (주소 칸은 도로명, 없으면 지번)
    listing = shown.drop(columns=["lat", "lon"])
    listing["네이버지도"] = (
        "https://map.naver.com/p/search/"
        + (listing["이름"] + " " + listing["주소"]).map(lambda text: urllib.parse.quote(text, safe=""))
    )
    st.dataframe(
        listing,
        hide_index=True,
        width="stretch",
        column_config={
            "거리(m)": st.column_config.NumberColumn(format="%d m"),
            "카카오맵": st.column_config.LinkColumn(display_text="열기"),
            "네이버지도": st.column_config.LinkColumn(display_text="열기"),
        },
    )
