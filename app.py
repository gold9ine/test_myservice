import base64
import csv
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

import chatbot

# 브라우저 탭 그림: 로고(assets/imgs/logo.png)의 사슴 머리를 간단히 줄인 파비콘
st.set_page_config(
    page_title="꽃사슴",
    page_icon=str(Path(__file__).parent / "assets" / "icons" / "favicon.png"),
    layout="wide",
)


# 색 조합(배경 · 글자 · 강조): .streamlit/config.toml 의 [theme] 한 곳에만 적고 여기서 읽어 쓴다
THEME_BG = st.get_option("theme.backgroundColor") or "#FFFFFF"
THEME_TEXT = st.get_option("theme.textColor") or "#1A1A1A"
THEME_ACCENT = st.get_option("theme.primaryColor") or "#513BBD"


def mix_white(color, amount):
    # 색에 흰색을 amount(0~1) 만큼 섞은 옅은 색
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(*(round(c + (255 - c) * amount) for c in (r, g, b)))


def rgba(color, alpha):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


# 강조색을 옅게 만든 보조 색: 아주 옅게 · 옅게 · 중간 (그림 · 테두리 · 꽃잎에 쓴다)
THEME_SOFT = mix_white(THEME_ACCENT, 0.9)
THEME_LIGHT = mix_white(THEME_ACCENT, 0.78)
THEME_MID = mix_white(THEME_ACCENT, 0.5)

# 화면 이동: 지금 보여 줄 화면 이름을 session_state 에 둔다
# streamlit run app.py 로 열면 서비스를 소개하는 첫 화면이 먼저 뜬다
if "page" not in st.session_state:
    st.session_state.page = "첫 화면"

DATA_DIR = Path(__file__).parent / "data"
ENV_PATH = Path(__file__).parent / ".env"


def read_env(path):
    # .env 의 KEY=VALUE 줄만 읽는다 (# 줄은 건너뜀). 파일이 없으면 빈 값
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


def read_csv(name):
    with open(DATA_DIR / name, encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def supabase_config():
    env = read_env(ENV_PATH)
    return env.get("SUPABASE_URL", "").rstrip("/"), env.get("SUPABASE_KEY", "")


def use_supabase():
    # .env 에 주소와 키가 모두 있으면 Supabase 를 쓴다. 없으면 CSV + 이 세션 안에서만 기억
    url, key = supabase_config()
    return bool(url and key)


def supabase(method, path, body=None):
    # Supabase REST API 호출: 키를 apikey 와 Authorization 헤더에 함께 싣는다
    # 쓰기를 막아 둔 동안에는 읽기(GET)만 보낸다
    if method != "GET" and not DB_WRITE_OPEN:
        raise urllib.error.URLError(DB_WRITE_CLOSED)
    url, key = supabase_config()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Prefer"] = "return=minimal"
    request = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        text = response.read().decode("utf-8")
        return json.loads(text) if text else None


def read_table(name, order):
    # Supabase 표를 읽는다. .env 에 주소와 키가 없으면 data 폴더의 같은 이름 CSV 를 읽는다
    if not use_supabase():
        return read_csv(f"{name}.csv")
    return supabase("GET", f"{name}?select=*&order={order}")


def next_id(table, column, prefix):
    # 표에 있는 번호 중 가장 큰 것 + 1 (예: S06 다음은 S07)
    rows = supabase("GET", f"{table}?select={column}")
    numbers = [int(row[column][len(prefix):]) for row in rows if row[column][len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:02d}"


def describe(error):
    if isinstance(error, urllib.error.HTTPError):
        return f"({error.code}) {error.read().decode('utf-8')}"
    return str(error.reason)


# 지금 서비스에 보여 줄 업종: 아직 헤어샵만. 네일샵(nail) · 피부샵(skin)을 열 때 여기에 더한다
SERVICE_CATEGORIES = {"hair"}

# 새 헤어샵 등록: 지금은 막아 둔다. 다시 열 때 True 로 바꾼다
NEW_SALON_OPEN = False
NEW_SALON_CLOSED = "지금은 새 헤어샵 등록을 막아 두었어요"

# Supabase 에 쓰기(넣기 · 고치기 · 지우기): 지금은 막아 두고 읽기만 한다. 다시 열 때 True 로 바꾼다
DB_WRITE_OPEN = False
DB_WRITE_CLOSED = "지금은 데이터베이스에 저장하는 것을 막아 두었어요"


@st.cache_data(ttl=30, show_spinner=False)
def pros_table():
    # 전문가(디자이너) 표 이름: supabase_users_professionals.sql 을 실행한 뒤에는 professionals, 그 전에는 stylists
    if not use_supabase():
        return "professionals" if (DATA_DIR / "professionals.csv").exists() else "stylists"
    try:
        supabase("GET", "professionals?select=stylist_id&limit=1")
        return "professionals"
    except urllib.error.HTTPError:
        return "stylists"


def number_or(value, kind):
    # 숫자 칸: 비었거나 숫자가 아니면 None
    try:
        return kind(value) if value not in (None, "") else None
    except ValueError:
        return None


def items_of(value):
    # 목록 칸: Supabase 는 목록으로, CSV 는 글자(JSON 또는 | 로 나눔)로 온다
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip().startswith(("[", "{")) else value.split("|")
        except ValueError:
            value = []
    return [v for v in (value or []) if v]


def pro_profile(row):
    # supabase_professional_details.sql 로 더한 디자이너 칸. 비어 있으면 기본값
    return {
        "photo_url": row.get("profile_photo_url") or "",
        "job_title": row.get("job_title") or "",
        "rating_avg": number_or(row.get("rating_avg"), float),
        "review_count": number_or(row.get("review_count"), int) or 0,
        "specialties": items_of(row.get("specialties")),
        "bio": row.get("bio") or "",
        "instagram": row.get("instagram") or "",
        "review_keywords": items_of(row.get("review_keywords")),
        "service_menu": items_of(row.get("service_menu")),
    }


def salon_details(row):
    # supabase_salon_details.sql 로 더한 칸. CSV 이거나 아직 비어 있으면 기본값
    number, items = number_or, items_of
    return {
        "rating_avg": number(row.get("rating_avg"), float),
        "review_count": number(row.get("review_count"), int) or 0,
        "is_verified": str(row.get("is_verified")).lower() == "true",
        "address_detail": row.get("address_detail") or "",
        "transit_info": row.get("transit_info") or "",
        "has_parking": str(row.get("has_parking")).lower() == "true",
        "thumbnail_url": row.get("thumbnail_url") or "",
        "photo_urls": items(row.get("photo_urls")),
        "description": row.get("description") or "",
        "service_tags": items(row.get("service_tags")),
        "price_list": items(row.get("price_list")),
        "hours_weekday": row.get("hours_weekday") or "",
        "hours_weekend": row.get("hours_weekend") or "",
        "closed_days": row.get("closed_days") or "",
    }


def load_salons():
    # 헤어샵(salons 표)에 소속 디자이너(stylists 표)를 붙인다. 서비스 중인 업종의 가게만 읽는다
    try:
        stylists = read_table(pros_table(), "stylist_id")
        salons = read_table("salons", "salon_id")
    except urllib.error.HTTPError as error:
        st.error(f"Supabase 에서 헤어샵 자료를 읽지 못했습니다 ({error.code}): {error.read().decode('utf-8')}")
        st.stop()
    except urllib.error.URLError as error:
        st.error(f"Supabase 에 연결하지 못했습니다: {error.reason}")
        st.stop()
    return [
        {
            "salon_id": row["salon_id"],
            "name": row["name"],
            "phone": row["phone"],
            "location": row["address"],
            # 업종: supabase_categories.sql 을 실행하기 전이라 칸이 없거나 비어 있으면 헤어샵
            "category": row.get("category_id") or "hair",
            # 좌표 없이 등록한 헤어샵(위도·경도가 빈 값)은 지도에 찍지 않는다
            "coords": (
                (float(row["lat"]), float(row["lng"]))
                if row.get("lat") not in (None, "") and row.get("lng") not in (None, "")
                else None
            ),
            "details": salon_details(row),
            "stylists": [s["name"] for s in stylists if s["salon_id"] == row["salon_id"]],
            "designers": [
                {"id": s["stylist_id"], "name": s["name"], "career": int(s.get("career_years") or 0),
                 "profile": pro_profile(s)}
                for s in stylists
                if s["salon_id"] == row["salon_id"]
            ],
        }
        for row in salons
        if (row.get("category_id") or "hair") in SERVICE_CATEGORIES
    ]


# 헤어샵 목록: Supabase 자료로 채운다 (.env 가 비어 있으면 CSV 로 채우고 새로 등록한 것은 이 세션 안에서만 들고 있는다)
if "salons" not in st.session_state:
    st.session_state.salons = load_salons()
    st.session_state.selected = 0
# 새 칸(details)을 읽기 전에 열어 둔 화면이면 헤어샵 자료를 한 번 새로 읽는다
elif any(
    "details" not in salon or any("profile" not in d for d in salon.get("designers", []))
    for salon in st.session_state.salons
):
    st.session_state.salons = load_salons()
    st.session_state.selected = min(st.session_state.get("selected", 0), len(st.session_state.salons) - 1)

# 예전에 빈 이름으로 들어간 소속 디자이너는 지운다
for salon in st.session_state.salons:
    salon["stylists"] = [name for name in salon["stylists"] if name.strip()]


def naver_keys():
    # .streamlit/secrets.toml 에 넣은 네이버 지도 키. 없으면 빈 값
    try:
        return (
            st.secrets.get("NAVER_MAP_CLIENT_ID", ""),
            st.secrets.get("NAVER_MAP_CLIENT_SECRET", ""),
        )
    except FileNotFoundError:
        return "", ""


@st.cache_data(show_spinner=False)
def geocode(query, client_id, client_secret):
    # 지도 위치 글자를 (위도, 경도)로 바꾼다. 좌표를 직접 넣었으면 그대로 쓴다
    text = query.strip()
    if not text:
        return None
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    if not (client_id and client_secret):
        return None
    # 네이버 Geocoding: 주소 → 좌표
    request = urllib.request.Request(
        "https://maps.apigw.ntruss.com/map-geocode/v2/geocode?query="
        + urllib.parse.quote(text),
        headers={
            "x-ncp-apigw-api-key-id": client_id,
            "x-ncp-apigw-api-key": client_secret,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            addresses = json.load(response).get("addresses", [])
    except Exception:
        return None
    if not addresses:
        return None
    return float(addresses[0]["y"]), float(addresses[0]["x"])


def plain_info(salon):
    # 기본 팝업: 이름 · 연락처 · 소속 디자이너
    return "<div style='padding:8px;font-size:13px'><b>{}</b><br>{}<br>{}</div>".format(
        html.escape(salon["name"]),
        html.escape(salon["phone"]),
        "<br>".join(html.escape(name) for name in salon["stylists"]),
    )


def map_pin():
    # 지도 핀: 강조 보라 물방울 + 흰 테두리 + 가운데 흰 가위 (헤어샵 표시). 아래 끝이 정확한 위치
    return f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="38" height="48" viewBox="0 0 38 48"
         style="filter: drop-shadow(0 3px 4px {rgba(THEME_TEXT, 0.35)}); cursor: pointer;">
      <path d="M19 46C19 46 3 29 3 18a16 16 0 0 1 32 0c0 11-16 28-16 28z"
            fill="{THEME_ACCENT}" stroke="#ffffff" stroke-width="2.5"/>
      <circle cx="19" cy="18" r="11" fill="#ffffff"/>
      <g fill="none" stroke="{THEME_ACCENT}" stroke-width="2" stroke-linecap="round">
        <circle cx="14.5" cy="22.5" r="2.6"/><circle cx="23.5" cy="22.5" r="2.6"/>
        <path d="M16.3 20.6L24 11.5M21.7 20.6L14 11.5"/>
      </g>
    </svg>
    """


def naver_map(salons, height, info=plain_info):
    # 네이버 지도에 헤어샵 핀을 찍는다. 핀을 누르면 info(salon) 이 만든 팝업이 뜬다
    markers = [
        {"lat": salon["coords"][0], "lng": salon["coords"][1], "info": info(salon)}
        for salon in salons
        if salon.get("coords")
    ]
    client_id, _ = naver_keys()
    if not (client_id and markers):
        return False
    # Streamlit 의 HTML 필터는 스크립트 안에 "<글자"가 있으면 스크립트를 통째로 지운다.
    # 팝업 HTML 의 "<" 를 < 로 바꿔 넣는다 (자바스크립트에서는 똑같이 "<" 로 읽힌다)
    data = json.dumps(markers).replace("<", "\\u003c")
    pin = json.dumps(map_pin()).replace("<", "\\u003c")
    # 지도 칸 id: 내용이 바뀌면 새 칸으로 다시 그리도록 내용으로 만든다
    map_id = "map_" + hashlib.md5(f"{data}{height}".encode()).hexdigest()[:12]
    script_url = json.dumps(
        "https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId="
        + urllib.parse.quote(client_id)
    )
    # iframe 안에 그리면 네이버 인증에 about:srcdoc 주소가 넘어가 실패하므로,
    # 페이지 본문에 바로 그려 등록한 Web 서비스 URL(localhost:8501)로 인증되게 한다
    st.html(
        f"""
        <div id="{map_id}" style="width:100%;height:{height}px"></div>
        <script>
        (function () {{
            const markers = {data};
            const pin = {pin};
            function draw() {{
                const el = document.getElementById("{map_id}");
                if (!el) return;
                const map = new naver.maps.Map(el, {{
                    center: new naver.maps.LatLng(markers[0].lat, markers[0].lng),
                    zoom: 16,
                }});
                if (markers.length > 1) {{
                    const bounds = new naver.maps.LatLngBounds();
                    markers.forEach((m) => bounds.extend(new naver.maps.LatLng(m.lat, m.lng)));
                    map.fitBounds(bounds);
                }}
                markers.forEach((m) => {{
                    const marker = new naver.maps.Marker({{
                        position: new naver.maps.LatLng(m.lat, m.lng),
                        map: map,
                        // 기본 파란 핀 대신 꽃사슴 핀. anchor 는 물방울 아래 끝
                        icon: {{ content: pin, size: new naver.maps.Size(38, 48), anchor: new naver.maps.Point(19, 47) }},
                    }});
                    const info = new naver.maps.InfoWindow({{
                        content: m.info, borderWidth: 0, backgroundColor: "transparent",
                        disableAnchor: true, pixelOffset: new naver.maps.Point(0, -8),
                    }});
                    naver.maps.Event.addListener(marker, "click", () => {{
                        // 팝업은 한 번에 하나만 연다
                        if (info.getMap()) {{ info.close(); return; }}
                        if (window.__openInfo) window.__openInfo.close();
                        info.open(map, marker);
                        window.__openInfo = info;
                    }});
                }});
            }}
            // 팝업 안 「헤어샵 보기」: 숨겨 둔 같은 번호의 Streamlit 버튼을 대신 눌러 헤어샵 세부정보 화면으로 간다
            if (!window.__mapShopButton) {{
                window.__mapShopButton = true;
                document.addEventListener("click", (event) => {{
                    const button = event.target.closest(".map-card-btn");
                    if (!button) return;
                    if (window.__openInfo) window.__openInfo.close();
                    const go = document.querySelector(".st-key-mapgo_" + button.dataset.index + " button");
                    if (go) go.click();
                }}, true);  // 네이버 지도가 팝업 안 클릭을 막으므로, 먼저 받는 단계(capture)에서 잡는다
            }}
            // 지도 스크립트는 페이지에 한 번만 불러오고, 다 불러온 뒤에 그린다
            if (window.naver && window.naver.maps) {{
                draw();
                return;
            }}
            if (!window.__naverMapsLoading) {{
                window.__naverMapsLoading = new Promise((resolve, reject) => {{
                    const s = document.createElement("script");
                    s.src = {script_url};
                    s.onload = resolve;
                    s.onerror = reject;
                    document.head.appendChild(s);
                }});
            }}
            window.__naverMapsLoading.then(draw);
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )
    return True


def go(page):
    st.session_state.page = page


def open_detail(index):
    st.session_state.selected = index
    go("헤어샵 세부정보")


def reload_salons(salon_id):
    # Supabase 에 쓴 뒤 목록을 다시 읽고, 방금 다룬 헤어샵을 선택해 둔다
    st.session_state.salons = load_salons()
    ids = [salon["salon_id"] for salon in st.session_state.salons]
    st.session_state.selected = ids.index(salon_id) if salon_id in ids else 0


def register_salon():
    # 등록을 막아 둔 동안에는 아무것도 저장하지 않는다
    if not NEW_SALON_OPEN:
        st.session_state.save_error = NEW_SALON_CLOSED
        return
    coords = geocode(st.session_state.new_location, *naver_keys())
    if not use_supabase():
        st.session_state.salons.append(
            {
                "salon_id": None,
                "name": st.session_state.new_name,
                "phone": st.session_state.new_phone,
                "location": st.session_state.new_location,
                "coords": coords,
                "stylists": [],
                "category": "hair",
                "details": salon_details({}),
            }
        )
        open_detail(len(st.session_state.salons) - 1)
        return
    # salons 표에 한 줄 넣는다. 로그인이 없으므로 헤어샵 주인(owner_stylist_id)은 비워 둔다
    try:
        salon_id = next_id("salons", "salon_id", "S")
        supabase(
            "POST",
            "salons",
            {
                "salon_id": salon_id,
                "name": st.session_state.new_name,
                "phone": st.session_state.new_phone,
                "address": st.session_state.new_location,
                "lat": coords[0] if coords else None,
                "lng": coords[1] if coords else None,
            },
        )
    except urllib.error.URLError as error:
        st.session_state.save_error = f"헤어샵을 저장하지 못했습니다 {describe(error)}"
        return
    reload_salons(salon_id)
    go("헤어샵 세부정보")


def register_move():
    # 디자이너 이름이 비어 있으면 아무것도 하지 않는다
    name = st.session_state.move_name.strip()
    if not name:
        return
    salon = st.session_state.salons[st.session_state.selected]
    st.session_state.move_name = ""
    if not (use_supabase() and salon["salon_id"]):
        salon["stylists"].append(name)
        return
    try:
        matches = supabase(
            "GET", f"{pros_table()}?select=stylist_id,salon_id&name=eq.{urllib.parse.quote(name)}"
        )
        if len(matches) == 1:
            # 같은 이름의 디자이너가 한 명 있으면: 이직 기록(moves)을 남기고 소속을 이 헤어샵으로 바꾼다
            stylist = matches[0]
            if stylist["salon_id"] != salon["salon_id"]:
                supabase(
                    "POST",
                    "moves",
                    {
                        "move_id": next_id("moves", "move_id", "M"),
                        "stylist_id": stylist["stylist_id"],
                        "from_salon_id": stylist["salon_id"],
                        "to_salon_id": salon["salon_id"],
                        "moved_on": date.today().isoformat(),
                    },
                )
                supabase(
                    "PATCH",
                    f"{pros_table()}?stylist_id=eq.{urllib.parse.quote(stylist['stylist_id'])}",
                    {"salon_id": salon["salon_id"]},
                )
        else:
            # 처음 보는 이름이거나 동명이인이 여럿이면 새 디자이너로 넣는다
            supabase(
                "POST",
                pros_table(),
                {
                    "stylist_id": next_id(pros_table(), "stylist_id", "ST"),
                    "name": name,
                    "salon_id": salon["salon_id"],
                },
            )
    except urllib.error.URLError as error:
        st.session_state.save_error = f"이직 등록을 저장하지 못했습니다 {describe(error)}"
        return
    reload_salons(salon["salon_id"])


def back_button():
    st.button("← 꽃사슴", width="stretch", on_click=go, args=("꽃사슴",))


# 지도·목록 높이: 스크롤 없이 한 화면에 들어오게 맞춘 값
MAP_HEIGHT = 380
PREVIEW_HEIGHT = 320
# 오른쪽 지도 영역의 지도 높이 (사이드 영역과 나란히 길게)
BODY_MAP_HEIGHT = 560
# 세부정보 화면: 지도 아래에 탭이 오므로 지도는 조금 낮게
DETAIL_MAP_HEIGHT = 320


def page_frame():
    # 모든 기능 화면 공통 틀: 맨 위 메뉴 줄 → 그 아래 [왼쪽 사이드 영역 | 오른쪽 지도 영역]
    st.html(MAIN_STYLE)
    main_nav()
    side, body = st.columns([1, 3.2], gap="large")
    return side.container(key="side"), body


# 시도 행정구역 17개: (이름, 주소 첫 낱말로 쓰이는 다른 이름들, 대략의 가운데 좌표)
REGIONS = [
    ("서울특별시", ("서울", "서울시"), (37.5665, 126.9780)),
    ("부산광역시", ("부산", "부산시"), (35.1796, 129.0756)),
    ("대구광역시", ("대구", "대구시"), (35.8714, 128.6014)),
    ("인천광역시", ("인천", "인천시"), (37.4563, 126.7052)),
    ("광주광역시", ("광주",), (35.1595, 126.8526)),
    ("대전광역시", ("대전", "대전시"), (36.3504, 127.3845)),
    ("울산광역시", ("울산", "울산시"), (35.5384, 129.3114)),
    ("세종특별자치시", ("세종", "세종시"), (36.4800, 127.2890)),
    ("경기도", ("경기",), (37.4500, 127.3000)),
    ("강원특별자치도", ("강원", "강원도"), (37.8000, 128.3000)),
    ("충청북도", ("충북",), (36.8000, 127.7000)),
    ("충청남도", ("충남",), (36.5500, 126.8500)),
    ("전북특별자치도", ("전북", "전라북도"), (35.7200, 127.1500)),
    ("전라남도", ("전남",), (34.8500, 126.9000)),
    ("경상북도", ("경북",), (36.3500, 128.7500)),
    ("경상남도", ("경남",), (35.3500, 128.2500)),
    ("제주특별자치도", ("제주", "제주도"), (33.3800, 126.5500)),
]
DEFAULT_REGION = "전북특별자치도"


def salon_region(salon):
    # 주소 첫 낱말로 시도를 찾는다. 주소에 시도가 없으면 좌표에서 가장 가까운 시도 가운데로 정한다
    words = salon["location"].split()
    if words:
        for name, aliases, _ in REGIONS:
            if words[0] == name or words[0] in aliases:
                return name
    if salon.get("coords"):
        lat, lng = salon["coords"]
        return min(REGIONS, key=lambda r: (r[2][0] - lat) ** 2 + (r[2][1] - lng) ** 2)[0]
    return None


def remember_region():
    st.session_state.region_choice = st.session_state.region


def region_select(where):
    # 지역 고르는 칸(where 자리에 둔다): 헤어샵이 한 곳이라도 있는 지역만 보인다. 처음에는 전북특별자치도
    counts = {name: 0 for name, _, _ in REGIONS}
    for salon in st.session_state.salons:
        region = salon_region(salon)
        if region:
            counts[region] += 1
    names = [name for name, _, _ in REGIONS if counts[name]] or [DEFAULT_REGION]
    # 기억해 둔 지역이 목록에 없으면 전북특별자치도, 그것도 없으면 첫 지역으로 정한다
    choice = st.session_state.get("region_choice", DEFAULT_REGION)
    if choice not in names:
        choice = DEFAULT_REGION if DEFAULT_REGION in names else names[0]
    st.session_state.region_choice = choice
    # 다른 화면에 다녀오면 칸 값이 지워지므로 기억해 둔 지역으로 다시 채운다
    if st.session_state.get("region") not in names:
        st.session_state.region = choice
    return where.selectbox(
        "지역",
        names,
        format_func=lambda name: f"{name} ({counts[name]}곳)",
        key="region",
        on_change=remember_region,
    )


DESIGNER_IMG_DIR = Path(__file__).parent / "assets" / "imgs" / "designers"
NOT_READY = "준비 중이에요"


def image_data_uri(path):
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def designer_role(career):
    # 경력으로 직급 이름을 붙인다 (샘플 규칙)
    return "실장" if career >= 10 else "디자이너" if career >= 5 else "주니어"


def designer_photo(designer_id):
    # 디자이너 샘플 사진: assets/imgs/designers/ST01.png … 없으면 default.png
    path = DESIGNER_IMG_DIR / f"{designer_id}.png"
    return path if path.exists() else DESIGNER_IMG_DIR / "default.png"


def portfolio_titles():
    # 디자이너별 포트폴리오 제목 (전문 분야로 보여 준다). 한 번만 읽어 둔다
    if "portfolios" not in st.session_state:
        try:
            rows = read_table("portfolios", "portfolio_id")
        except urllib.error.URLError:
            rows = []
        titles = {}
        for row in rows:
            titles.setdefault(row["stylist_id"], []).append(row["title"])
        st.session_state.portfolios = titles
    return st.session_state.portfolios


@st.cache_data(show_spinner=False)
def designer_thumb(designer_id):
    # 지도 팝업용 작은 디자이너 얼굴 (64px 로 줄여 페이지를 가볍게)
    from PIL import Image
    import io

    image = Image.open(designer_photo(designer_id)).convert("RGB").resize((64, 64), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def map_card(salon):
    # 메인 지도 팝업 카드: 이름 · 「헤어샵」 표 · 지역 · 연락처 · 디자이너 얼굴(최대 3명) + 인원 · 「헤어샵 보기」
    city, gu = salon_area(salon)
    designers = salon.get("designers") or [{"id": "", "name": n} for n in salon["stylists"]]
    faces = "".join(
        f'<img src="{designer_thumb(d["id"])}" alt="{html.escape(d["name"])}">' for d in designers[:3]
    )
    more = f'<span class="map-card-more">+{len(designers) - 3}</span>' if len(designers) > 3 else ""
    people = (
        f'<div class="map-card-people"><div class="map-card-faces">{faces}{more}</div>'
        f"<span>디자이너 {len(designers)}명</span></div>"
        if designers
        else '<div class="map-card-people"><span>아직 소속 디자이너가 없어요</span></div>'
    )
    area = " ".join(x for x in (city, gu) if x)
    return f"""
    <div class="map-card">
        <div class="map-card-title">{html.escape(salon["name"])}</div>
        <div class="map-card-meta"><span class="map-card-tag">헤어샵</span>{html.escape(area)}</div>
        <div class="map-card-phone">📞 {html.escape(salon["phone"] or "연락처 정보 없음")}</div>
        {people}
        <button class="map-card-btn" data-index="{st.session_state.salons.index(salon)}">헤어샵 보기</button>
    </div>
    """


def salon_area(salon):
    # 주소에서 시·군과 구를 뽑는다 (예: 전북특별자치도 전주시 완산구 … → 전주시, 완산구)
    words = salon["location"].split()
    if words and any(words[0] == name or words[0] in aliases for name, aliases, _ in REGIONS):
        words = words[1:]
    city = words[0] if words else ""
    gu = words[1] if len(words) > 1 and words[1].endswith("구") else ""
    return city, gu


def area_select(label, options, key):
    # 「전체」 + 고를 수 있는 값. 고른 값이 목록에서 사라지면 「전체」로 돌아간다
    options = ["전체"] + sorted(o for o in set(options) if o)
    if st.session_state.get(key) not in options:
        st.session_state[key] = "전체"
    return st.selectbox(label, options, key=key)


def reset_search():
    st.session_state.search_q = ""
    st.session_state.city = "전체"
    st.session_state.gu = "전체"


def find_panel():
    # 왼쪽 사이드 영역: 헤어샵 찾기 (검색어 · 지역 선택 · 필터 · 검색하기 · 초기화)
    st.markdown("### 헤어샵 찾기")
    st.caption("내 주변 헤어샵과 디자이너를 찾아보세요")
    query = st.text_input(
        "검색", placeholder="지역, 헤어샵 이름 검색", key="search_q", label_visibility="collapsed"
    )
    st.button("◎ 내 위치", width="stretch", disabled=True, help=NOT_READY)

    st.markdown("**지역 선택**")
    region = region_select(st)
    in_region = [salon for salon in st.session_state.salons if salon_region(salon) == region]
    city = area_select("시·군", [salon_area(s)[0] for s in in_region], "city")
    gu = area_select(
        "구", [salon_area(s)[1] for s in in_region if city in ("전체", salon_area(s)[0])], "gu"
    )

    # 필터: 자리만 잡아 둔다 (아직 자료가 없다)
    st.markdown("**필터**")
    for name in ["시술 종류", "가격대", "영업 시간"]:
        with st.expander(name):
            st.caption(NOT_READY)

    # 검색어 · 지역은 고르는 즉시 반영된다. 「검색하기」는 입력을 마치고 누르는 자리
    st.button("검색하기", key="search_btn", type="primary", width="stretch")
    st.button("초기화", key="reset_btn", type="tertiary", width="stretch", on_click=reset_search)
    st.divider()
    st.warning("아직 예시 결과입니다")
    return region, city, gu, query.strip()


def matches(salon, region, city, gu, query):
    salon_city, salon_gu = salon_area(salon)
    return (
        salon_region(salon) == region
        and city in ("전체", salon_city)
        and gu in ("전체", salon_gu)
        and (not query or query in salon["name"] or query in salon["location"])
    )


def sample_login(value):
    # 샘플 로그인: 실제 인증은 없다. 로그인한 상태의 메뉴를 보여 주기 위한 자리
    st.session_state.logged_in = value


def main_nav():
    # 맨 위 메뉴 줄: 꽃사슴(누르면 첫 화면) | 가운데 주 메뉴 | 오른쪽 알림 · 로그인/회원가입 또는 마이페이지(서브메뉴)
    with st.container(key="topnav"):
        brand_col, menu_col, user_col = st.columns([1.4, 5, 2.4], vertical_alignment="center")
        with brand_col:
            st.button("꽃사슴", key="brand", type="tertiary", on_click=go, args=("첫 화면",))
        with menu_col, st.container(horizontal=True, horizontal_alignment="center", gap="large"):
            st.button("홈", key="nav_home", type="tertiary", on_click=go, args=("첫 화면",))
            st.button("헤어샵 찾기", key="nav_find", type="tertiary", on_click=go, args=("꽃사슴",))
            st.button("디자이너 찾기", key="nav_designer", type="tertiary", disabled=True, help=NOT_READY)
            st.button("스타일 추천", key="nav_style", type="tertiary", disabled=True, help=NOT_READY)
            st.button("이벤트", key="nav_event", type="tertiary", disabled=True, help=NOT_READY)
        with user_col, st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
            st.button("🔔", key="nav_bell", type="tertiary", disabled=True, help="알림 — " + NOT_READY)
            if st.session_state.get("logged_in"):
                # 로그인한 상태: 마이페이지 아래로 헤어샵 등록 · 내 대시보드 · 로그아웃
                with st.popover("👤 마이페이지", key="nav_my"), st.container(key="my_menu", gap="small"):
                    st.button("새 헤어샵 등록", key="nav_new", type="tertiary", width="stretch",
                              on_click=go, args=("새 헤어샵 등록",),
                              disabled=not NEW_SALON_OPEN, help=None if NEW_SALON_OPEN else NEW_SALON_CLOSED)
                    st.button("내 대시보드", key="nav_dash", type="tertiary", width="stretch",
                              disabled=True, help=NOT_READY)
                    st.html('<hr class="my-menu-line">')
                    st.button("로그아웃", key="nav_logout", type="tertiary", width="stretch",
                              on_click=sample_login, args=(False,))
            else:
                st.button("로그인", key="nav_login", type="tertiary", on_click=sample_login, args=(True,),
                          help="샘플 로그인 — 실제 인증은 없어요")
                st.button("회원가입", key="nav_signup", type="primary", disabled=True, help=NOT_READY)
    if "save_error" in st.session_state:
        st.error(st.session_state.pop("save_error"))


def salon_thumb_svg():
    # 헤어샵 사진 자리: 거울 · 의자 · 조명을 그린 실내 그림 (샘플)
    return f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 220">
      <rect width="320" height="220" fill="{THEME_SOFT}"/>
      <rect y="168" width="320" height="52" fill="{THEME_LIGHT}"/>
      <path d="M60 0V30M160 0V30M260 0V30" stroke="{THEME_TEXT}" stroke-width="3"/>
      <circle cx="60" cy="36" r="9" fill="#FFE9A8"/><circle cx="160" cy="36" r="9" fill="#FFE9A8"/>
      <circle cx="260" cy="36" r="9" fill="#FFE9A8"/>
      <ellipse cx="100" cy="100" rx="34" ry="46" fill="#ffffff" stroke="{THEME_MID}" stroke-width="5"/>
      <ellipse cx="220" cy="100" rx="34" ry="46" fill="#ffffff" stroke="{THEME_MID}" stroke-width="5"/>
      <rect x="80" y="130" width="40" height="34" rx="9" fill="{THEME_ACCENT}"/>
      <rect x="200" y="130" width="40" height="34" rx="9" fill="{THEME_ACCENT}"/>
      <rect x="72" y="160" width="56" height="12" rx="5" fill="{THEME_TEXT}"/>
      <rect x="192" y="160" width="56" height="12" rx="5" fill="{THEME_TEXT}"/>
      <rect x="97" y="172" width="6" height="22" fill="{THEME_TEXT}"/>
      <rect x="217" y="172" width="6" height="22" fill="{THEME_TEXT}"/>
    </svg>
    """


def designer_cards(salon):
    # 소속 디자이너 카드: 샘플 사진 · 이름 · 직급 · 경력 · 전문 분야(포트폴리오 제목) · 포트폴리오 버튼(자리만)
    known = {d["name"]: d for s in st.session_state.salons for d in s.get("designers", [])}
    titles = portfolio_titles()
    names = salon["stylists"]
    if not names:
        st.caption("아직 소속 디자이너가 없습니다.")
        return
    per_row = 5
    for row_start in range(0, len(names), per_row):
        cols = st.columns(per_row)
        for k, (col, name) in enumerate(zip(cols, names[row_start:row_start + per_row])):
            designer = known.get(name, {"id": "", "name": name, "career": 0, "profile": pro_profile({})})
            specialty = titles.get(designer["id"], [])
            key = f"{salon['salon_id']}_{row_start + k}"
            with col, st.container(border=True, key=f"dcard_{key}"):
                st.image(str(designer_photo(designer["id"])), width="stretch")
                st.html(
                    f"""
                    <div class="dcard">
                        <b>{html.escape(name)}</b><span>{html.escape(designer["profile"]["job_title"] or designer_role(designer["career"]))}</span>
                        <p class="dcard-career">{"★ " + format(designer["profile"]["rating_avg"], ".1f") + " · " if designer["profile"]["rating_avg"] is not None else ""}경력 {designer["career"]}년</p>
                        <p>{html.escape(", ".join(specialty) or "전문 분야 준비 중")}</p>
                    </div>
                    """
                )
                st.button("포트폴리오 보기", key=f"pf_{key}", width="stretch",
                          disabled=not designer["id"], on_click=open_designer, args=(designer["id"],))


def salon_sheet(index, salon):
    # 아래 상세 판: 고른 헤어샵의 사진 · 이름 · 주소 · 연락처 + 탭(디자이너 · 헤어샵 정보 · 오시는 길)
    with st.container(key="sheet"):
        photo_col, info_col, action_col = st.columns([1.3, 3, 1.3], vertical_alignment="center")
        with photo_col:
            st.html(svg_img(salon_thumb_svg(), "salon-photo"))
        with info_col:
            city, gu = salon_area(salon)
            tags = [f"소속 디자이너 {len(salon['stylists'])}명", " ".join(x for x in (city, gu) if x)]
            tag_html = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in tags if t)
            st.html(
                f"""
                <div class="sheet-info">
                    <h2>{html.escape(salon["name"])}</h2>
                    <p>📍 {html.escape(salon["location"].strip() or "주소 정보 없음")}</p>
                    <p>📞 {html.escape(salon["phone"] or "연락처 정보 없음")}</p>
                    <div>{tag_html}</div>
                </div>
                """
            )
        with action_col:
            st.button("자세히 보기", key="sheet_detail", width="stretch", on_click=open_detail, args=(index,))
            st.button(
                "이직 등록", key="sheet_move", type="primary", width="stretch", on_click=open_detail, args=(index,)
            )

        designers_tab, info_tab, way_tab = st.tabs(["디자이너", "헤어샵 정보", "오시는 길"])
        with designers_tab:
            designer_cards(salon)
        with info_tab:
            basic_col, price_col, hours_col = st.columns(3)
            with basic_col, st.container(border=True):
                st.markdown("**기본 정보**")
                st.write(f"연락처: {salon['phone'] or '-'}")
                st.write(f"소속 디자이너: {len(salon['stylists'])}명")
            with price_col, st.container(border=True):
                st.markdown("**주요 시술 가격**")
                st.caption(NOT_READY)
            with hours_col, st.container(border=True):
                st.markdown("**영업시간**")
                st.caption(NOT_READY)
        with way_tab:
            st.write(f"📍 {salon['location'].strip() or '주소 정보 없음'}")
            if salon.get("coords"):
                st.caption(f"위도 {salon['coords'][0]}, 경도 {salon['coords'][1]}")


MAIN_STYLE = f"""
<style>
[data-testid="stApp"], [data-testid="stHeader"] {{ background: {THEME_BG}; }}
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {{ display: none; }}
/* 왼쪽 사이드 영역: 흰 판 */
.st-key-side {{
    background: #ffffff; border: 1px solid {rgba(THEME_TEXT, 0.08)}; border-radius: 18px; padding: 1.2rem;
}}
.st-key-side h3 {{ color: {THEME_TEXT}; margin-bottom: 0; }}
/* 맨 위 메뉴 줄: 위에 붙어 있다 */
[data-testid="stLayoutWrapper"]:has(> .st-key-topnav) {{ position: sticky; top: 3.75rem; z-index: 999; }}
.st-key-topnav {{ background: {THEME_BG}; border-bottom: 1px solid {rgba(THEME_TEXT, 0.12)}; padding: 0.4rem 0; }}
.st-key-brand button {{ padding: 0; }}
.st-key-brand button p {{ font-size: 1.6rem !important; font-weight: 800; color: {THEME_ACCENT} !important; letter-spacing: 0.05em; }}
.st-key-topnav button p {{ font-size: 1.05rem; color: {THEME_TEXT}; font-weight: 600; }}
.st-key-topnav button:disabled p {{ color: {THEME_TEXT}; opacity: 0.85; }}
.st-key-nav_find button {{ border-bottom: 3px solid {THEME_ACCENT} !important; border-radius: 0; padding-bottom: 0.3rem; }}
.st-key-nav_signup button {{ border-radius: 10px; padding: 0.3rem 1.1rem; }}
.st-key-nav_signup button p {{ color: #ffffff !important; }}
/* 회원가입은 아직 자리만 있지만(눌리지 않음) 보라 버튼 모양은 그대로 보이게 한다 */
.st-key-nav_signup button:disabled {{ background: {THEME_ACCENT}; border-color: {THEME_ACCENT}; opacity: 0.9; }}
.st-key-nav_my button {{ border-radius: 999px; }}
/* 마이페이지 서브메뉴: 좁고 촘촘하게, 글자는 왼쪽 맞춤 */
[data-testid="stPopoverBody"]:has(.st-key-my_menu) {{ width: 190px !important; min-width: 0; padding: 0.4rem; }}
.st-key-my_menu {{ gap: 0.15rem !important; }}
.st-key-my_menu button {{ justify-content: flex-start; padding: 0.45rem 0.75rem; border-radius: 8px; min-height: 0; }}
/* 버튼 안쪽 글자 칸이 가운데 맞춤이라, 그 칸도 왼쪽 맞춤으로 */
.st-key-my_menu button > div {{ justify-content: flex-start; }}
.st-key-my_menu button p {{ font-size: 0.92rem; color: {THEME_TEXT}; }}
.st-key-my_menu button:hover:not(:disabled) {{ background: {THEME_SOFT}; }}
.st-key-my_menu button:hover:not(:disabled) p {{ color: {THEME_ACCENT}; }}
.st-key-my_menu button:disabled p {{ color: {rgba(THEME_TEXT, 0.4)}; }}
.my-menu-line {{ margin: 0.2rem 0.5rem; border: 0; border-top: 1px solid {rgba(THEME_TEXT, 0.1)}; }}
.st-key-nav_find button p {{ color: {THEME_ACCENT}; font-weight: 700; }}
/* 지도 · 결과 수 */
.result-count {{
    display: inline-block; background: #ffffff; border-radius: 10px; padding: 0.35rem 0.8rem;
    box-shadow: 0 2px 8px {rgba(THEME_TEXT, 0.08)}; color: {THEME_TEXT};
}}
.result-count b {{ color: {THEME_ACCENT}; }}
.st-key-map_area div[id^="map_"], .st-key-map_area [data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: 18px; overflow: hidden;
}}
.st-key-map_go {{ display: none; }}
/* 지도 팝업 카드 */
.map-card {{
    width: 240px; background: #ffffff; border-radius: 16px; padding: 14px 16px 16px;
    box-shadow: 0 8px 24px {rgba(THEME_TEXT, 0.18)}; color: {THEME_TEXT}; font-size: 13px;
}}
.map-card-title {{ font-size: 17px; font-weight: 800; margin-bottom: 4px; }}
.map-card-meta {{ color: {rgba(THEME_TEXT, 0.6)}; display: flex; align-items: center; gap: 6px; }}
.map-card-tag {{ background: {THEME_SOFT}; color: {THEME_ACCENT}; border-radius: 6px; padding: 1px 6px; font-size: 12px; }}
.map-card-phone {{ margin: 6px 0 10px; }}
.map-card-people {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }}
.map-card-faces {{ display: flex; }}
.map-card-faces img, .map-card-more {{
    width: 30px; height: 30px; border-radius: 50%; border: 2px solid #ffffff; margin-right: -8px;
}}
.map-card-more {{
    display: inline-flex; align-items: center; justify-content: center;
    background: {THEME_SOFT}; color: {THEME_ACCENT}; font-size: 11px; font-weight: 700;
}}
.map-card-people > span {{ margin-left: 10px; }}
.map-card-btn {{
    width: 100%; border: 0; border-radius: 10px; padding: 9px 0; cursor: pointer;
    background: {THEME_ACCENT}; color: #ffffff; font-size: 14px; font-weight: 700;
}}
.map-card-btn:hover {{ filter: brightness(0.92); }}
/* 아래 상세 판 */
.st-key-sheet {{
    background: #ffffff; border-radius: 22px; padding: 1.5rem;
    box-shadow: 0 -4px 24px {rgba(THEME_TEXT, 0.08)}; margin-top: 0.5rem;
}}
.salon-photo {{ width: 100%; border-radius: 14px; display: block; }}
.sheet-info h2 {{ margin: 0 0 0.4rem; color: {THEME_TEXT}; font-size: 1.7rem; }}
.sheet-info p {{ margin: 0.15rem 0; color: {THEME_TEXT}; }}
.tag {{
    display: inline-block; margin: 0.5rem 0.4rem 0 0; padding: 0.2rem 0.7rem; border-radius: 999px;
    background: {THEME_BG}; color: {THEME_TEXT}; font-size: 0.85rem; border: 1px solid {rgba(THEME_TEXT, 0.1)};
}}
/* 헤어샵 세부정보 */
.st-key-side [data-testid="stImage"] img {{ border-radius: 14px; }}
.detail-summary h2 {{ font-size: 1.5rem; margin: 0.2rem 0 0.3rem; color: {THEME_TEXT}; }}
.detail-summary p {{ margin: 0.25rem 0; color: {THEME_TEXT}; font-size: 0.95rem; }}
.verified {{
    font-size: 0.8rem; color: #ffffff; background: {THEME_ACCENT}; border-radius: 999px;
    padding: 0.1rem 0.55rem; vertical-align: middle; font-weight: 600;
}}
.rating .stars {{ color: #F5B301; letter-spacing: 0.05em; }}
.muted {{ color: {rgba(THEME_TEXT, 0.55)}; }}
.open-badge {{
    display: inline-block; font-size: 0.8rem; font-weight: 700; border-radius: 6px; padding: 0.05rem 0.5rem;
    background: {rgba(THEME_TEXT, 0.08)}; color: {rgba(THEME_TEXT, 0.7)};
}}
.open-badge.open {{ background: {THEME_SOFT}; color: {THEME_ACCENT}; }}
.chips {{ margin-top: 0.6rem; }}
.chip {{
    display: inline-block; margin: 0 0.35rem 0.35rem 0; padding: 0.2rem 0.65rem; border-radius: 999px;
    border: 1px solid {THEME_LIGHT}; color: {THEME_ACCENT}; font-size: 0.85rem;
}}
.chip-soft {{ background: {THEME_SOFT}; border-color: {THEME_SOFT}; color: {THEME_TEXT}; }}
.description {{ font-size: 1rem; color: {THEME_TEXT}; margin: 0.3rem 0 0.8rem; line-height: 1.6; }}
.price-row {{
    display: flex; justify-content: space-between; padding: 0.35rem 0; color: {THEME_TEXT};
    border-bottom: 1px dashed {rgba(THEME_TEXT, 0.1)};
}}
.price-row:last-child {{ border-bottom: 0; }}
.price-row b {{ font-weight: 700; }}
.closed {{ margin: 0.5rem 0 0; color: {THEME_ACCENT}; font-weight: 700; }}
/* 디자이너 상세 */
.st-key-designer_back button p {{ color: {THEME_TEXT}; }}
/* 예약하기는 아직 자리만 있지만(눌리지 않음) 보라 버튼 모양은 그대로 */
.st-key-pro_book button:disabled {{ background: {THEME_ACCENT}; border-color: {THEME_ACCENT}; opacity: 0.9; }}
.st-key-pro_book button:disabled p {{ color: #ffffff; }}
.pro-photo {{ width: 100%; aspect-ratio: 1 / 0.85; object-fit: cover; border-radius: 16px; background: {THEME_SOFT}; }}
.pro-head h2 {{ font-size: 1.6rem; margin: 0.8rem 0 0.2rem; color: {THEME_TEXT}; }}
.pro-title {{ font-size: 1rem; color: {THEME_ACCENT}; font-weight: 600; margin-left: 0.3rem; }}
.pro-head p {{ margin: 0.2rem 0; font-size: 0.95rem; }}
.star {{ color: #F5B301; }}
.pro-facts {{ margin: 0.8rem 0; display: grid; gap: 0.6rem; }}
.fact {{ display: grid; grid-template-columns: 6.5rem 1fr; font-size: 0.92rem; color: {THEME_TEXT}; line-height: 1.55; }}
.fact-label {{ color: {rgba(THEME_TEXT, 0.65)}; }}
.pro-section {{ border-top: 1px solid {rgba(THEME_TEXT, 0.1)}; padding-top: 1rem; margin-top: 0.5rem; }}
.pro-section h4 {{ margin: 0 0 0.6rem; font-size: 1.05rem; color: {THEME_TEXT}; }}
.big-rating {{ font-size: 1.8rem; font-weight: 800; margin: 0 0 0.5rem; color: {THEME_TEXT}; }}
.big-rating .star {{ font-size: 1.3rem; letter-spacing: 0.1em; }}
.kws {{ display: flex; flex-wrap: wrap; gap: 0.4rem; }}
.kw {{ background: {THEME_SOFT}; color: {THEME_TEXT}; border-radius: 999px; padding: 0.3rem 0.8rem; font-size: 0.85rem; }}
.shop-card {{ display: flex; gap: 0.8rem; align-items: center; margin-bottom: 0.4rem; }}
.shop-card img {{ width: 88px; height: 70px; object-fit: cover; border-radius: 10px; }}
.shop-card b {{ color: {THEME_TEXT}; }}
.shop-card p {{ margin: 0.2rem 0 0; font-size: 0.9rem; }}
.pf-count {{ margin: 0.4rem 0; font-size: 1.1rem; color: {THEME_TEXT}; }}
.pf-count span {{ color: {THEME_ACCENT}; margin-left: 0.3rem; }}
.pf-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }}
.pf-card {{ background: #ffffff; border: 1px solid {rgba(THEME_TEXT, 0.08)}; border-radius: 14px; overflow: hidden; }}
.pf-photo {{ position: relative; aspect-ratio: 1 / 1.05; background: {THEME_SOFT}; }}
.pf-photo img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.pf-like {{
    position: absolute; top: 10px; right: 10px; background: rgba(0, 0, 0, 0.45); color: #ffffff;
    border-radius: 999px; padding: 0.15rem 0.6rem; font-size: 0.8rem;
}}
.pf-badge {{
    position: absolute; left: 10px; bottom: 10px; background: rgba(0, 0, 0, 0.55); color: #ffffff;
    border-radius: 999px; padding: 0.15rem 0.6rem; font-size: 0.78rem;
}}
.pf-body {{ padding: 0.8rem 0.9rem 0.9rem; }}
.pf-body h5 {{ margin: 0 0 0.3rem; font-size: 1rem; color: {THEME_TEXT}; }}
.pf-body p {{ margin: 0; font-size: 0.85rem; color: {rgba(THEME_TEXT, 0.65)}; line-height: 1.5; }}
.pf-body .pf-tags {{ margin-top: 0.6rem; color: {rgba(THEME_TEXT, 0.45)}; }}
.menu-row {{
    display: grid; grid-template-columns: 1fr 5rem 8rem; padding: 0.8rem 0.2rem; color: {THEME_TEXT};
    border-bottom: 1px solid {rgba(THEME_TEXT, 0.08)};
}}
.menu-row b {{ text-align: right; }}
.kw-bar {{ display: grid; grid-template-columns: 11rem 1fr 3rem; gap: 0.8rem; align-items: center; margin: 0.5rem 0; color: {THEME_TEXT}; }}
.kw-bar .bar {{ height: 10px; background: {THEME_SOFT}; border-radius: 999px; overflow: hidden; }}
.kw-bar .bar i {{ display: block; height: 100%; background: {THEME_ACCENT}; border-radius: 999px; }}
.kw-bar b {{ text-align: right; }}
.tip {{
    display: flex; gap: 0.8rem; align-items: center; margin-top: 1.2rem; padding: 0.9rem 1.1rem;
    border: 1px solid {rgba(THEME_TEXT, 0.08)}; border-radius: 14px; background: #ffffff;
}}
.tip span {{ font-size: 1.5rem; }}
.tip b {{ color: {THEME_TEXT}; }}
.tip p {{ margin: 0.15rem 0 0; font-size: 0.88rem; color: {rgba(THEME_TEXT, 0.65)}; }}
/* 디자이너 카드 */
[class*="st-key-dcard_"] {{ background: #ffffff; border-radius: 16px !important; }}
[class*="st-key-dcard_"] img {{ border-radius: 12px; }}
.dcard b {{ font-size: 1.15rem; color: {THEME_TEXT}; margin-right: 0.4rem; }}
.dcard span {{ color: {THEME_ACCENT}; font-size: 0.9rem; }}
.dcard p {{ margin: 0.2rem 0; color: {THEME_TEXT}; font-size: 0.9rem; }}
.dcard .dcard-career {{ color: {rgba(THEME_TEXT, 0.6)}; }}
</style>
"""


def nearby_salons():
    # 메인 화면: 맨 위 메뉴 줄 → 왼쪽 헤어샵 찾기 메뉴 | 오른쪽 지도 · 고른 헤어샵 상세 판
    side, body = page_frame()
    with side:
        region, city, gu, query = find_panel()
    with body:
        salon_map_area(region, city, gu, query)


def salon_map_area(region, city, gu, query):
    # 찾기 조건에 맞는 헤어샵만 지도와 상세 판에 보인다. 번호(index)는 전체 목록 기준 그대로 쓴다
    shown = [
        (index, salon)
        for index, salon in enumerate(st.session_state.salons)
        if matches(salon, region, city, gu, query)
    ]

    st.html(f'<span class="result-count">검색 결과 <b>{len(shown)}</b>개</span>')
    with st.container(key="map_area"):
        if not naver_map([salon for _, salon in shown], BODY_MAP_HEIGHT, info=map_card):
            with st.container(
                border=True,
                height=BODY_MAP_HEIGHT,
                horizontal_alignment="center",
                vertical_alignment="center",
            ):
                st.caption("(지도 자리 — 네이버 지도 키를 넣으면 실제 지도가 보입니다)")

    # 지도 팝업 「헤어샵 보기」가 대신 누르는 숨은 버튼: 누르면 그 헤어샵 세부정보 화면으로 간다
    with st.container(key="map_go"):
        for index, _ in shown:
            st.button("헤어샵 보기", key=f"mapgo_{index}", on_click=open_detail, args=(index,))

    if not shown:
        st.info("조건에 맞는 헤어샵이 없어요. 검색어나 지역을 바꿔 보세요.")
        return

    # 헤어샵 고르기: 지도 핀에서는 화면을 바꿀 수 없어서, 지도 아래 이름 단추로 고른다
    indexes = [index for index, _ in shown]
    if st.session_state.get("pick") not in indexes:
        st.session_state.pick = st.session_state.selected if st.session_state.selected in indexes else indexes[0]
    picked = st.pills(
        "헤어샵 고르기",
        indexes,
        format_func=lambda i: st.session_state.salons[i]["name"],
        key="pick",
        label_visibility="collapsed",
    )
    if picked is None:
        picked = indexes[0]
    st.session_state.selected = picked
    salon_sheet(picked, st.session_state.salons[picked])


def new_salon():
    # 맨 위 메뉴 줄 → 왼쪽 넣는 칸(이름 · 연락처 · 지도 위치 · 등록) | 오른쪽 위치 미리보기 지도
    side, body = page_frame()
    with side:
        st.markdown("### 새 헤어샵 등록")
        st.text_input("헤어샵 이름", placeholder="예: 헤어스튜디오 봄", key="new_name")
        st.text_input("연락처", placeholder="예: 010-0000-0000", key="new_phone")
        # 지도 위치: 지도 SDK가 없으므로 주소나 좌표 텍스트로 받는다
        st.text_input(
            "지도 위치",
            placeholder="예: 서울시 ○○구 ○○로 12 또는 37.5665, 126.9780",
            key="new_location",
        )
        # 버튼: 입력값을 Supabase 에 저장하고 등록한 헤어샵의 세부정보로 이동한다
        st.button("등록", type="primary", width="stretch", on_click=register_salon,
                  disabled=not NEW_SALON_OPEN, help=None if NEW_SALON_OPEN else NEW_SALON_CLOSED)
        st.divider()
        back_button()
        st.warning("아직 예시 결과입니다")

    with body:
        # 결과 자리: 지도 위치를 입력하면 그 자리를 지도에 바로 보여 준다
        location = st.session_state.get("new_location", "")
        coords = geocode(location, *naver_keys())
        preview = {
            "name": st.session_state.get("new_name") or "새 헤어샵",
            "phone": st.session_state.get("new_phone", ""),
            "coords": coords,
            "stylists": [],
        }
        if not naver_map([preview], BODY_MAP_HEIGHT):
            with st.container(
                border=True,
                height=BODY_MAP_HEIGHT,
                horizontal_alignment="center",
                vertical_alignment="center",
            ):
                st.markdown("📍 지도에서 위치 선택")
                if coords:
                    st.caption(f"위도 {coords[0]}, 경도 {coords[1]}")
                st.caption("(지도 자리 — 네이버 지도 키를 넣으면 실제 지도가 보입니다)")
        if location.strip() and not coords:
            st.caption("입력한 위치를 지도에서 찾지 못했습니다.")


def stylist_list(salon, height):
    # 소속 디자이너 목록: 길어지면 이 칸 안에서만 스크롤
    st.markdown("**소속 디자이너**")
    with st.container(height=height):
        for name in salon["stylists"]:
            with st.container(border=True):
                st.text(name)
        if not salon["stylists"]:
            st.caption("아직 소속 디자이너가 없습니다.")


WEEKDAYS = "월화수목금토일"
KST = timezone(timedelta(hours=9))


def photo_source(url):
    # 사진 주소: http 로 시작하면 그대로, 아니면 프로젝트 안 파일 경로. 파일이 없으면 None
    if not url:
        return None
    if url.startswith("http"):
        return url
    path = Path(__file__).parent / url
    return str(path) if path.exists() else None


def open_status(details, now=None):
    # 오늘 영업시간과 지금 영업 중인지: (영업 중?, 오늘 영업시간 글, 휴무?)
    now = now or datetime.now(KST)
    today = WEEKDAYS[now.weekday()]
    if details["closed_days"] and f"{today}요일" in details["closed_days"]:
        return False, "오늘 휴무", True
    hours = details["hours_weekend"] if now.weekday() >= 5 else details["hours_weekday"]
    if not hours or "-" not in hours:
        return False, "영업시간 정보 없음", False
    start, end = (h.strip() for h in hours.split("-", 1))
    return start <= now.strftime("%H:%M") < end, f"오늘 {start} - {end}", False


def stars(rating):
    # ★★★★☆ 처럼 별 다섯 개 (반올림)
    full = int(round(rating or 0))
    return "★" * full + "☆" * (5 - full)


def detail_summary(salon):
    # 사이드 영역 위쪽: 이름 · 인증 · 별점 · 주소 · 교통 · 연락처 · 태그
    d = salon["details"]
    verified = '<span class="verified" title="인증된 헤어샵">✔ 인증</span>' if d["is_verified"] else ""
    rating = (
        f'<p class="rating"><span class="stars">{stars(d["rating_avg"])}</span> '
        f'<b>{d["rating_avg"]:.1f}</b> <span class="muted">(리뷰 {d["review_count"]})</span></p>'
        if d["rating_avg"] is not None
        else '<p class="rating muted">아직 별점이 없어요</p>'
    )
    address = " ".join(x for x in (salon["location"].strip(), d["address_detail"] or "") if x)
    lines = [f"📍 {html.escape(address or '주소 정보 없음')}"]
    if d["transit_info"]:
        lines.append(f"🚌 {html.escape(d['transit_info'])}")
    lines.append(f"📞 {html.escape(salon['phone'] or '연락처 정보 없음')}")
    chips = [f'<span class="chip">{html.escape(t)}</span>' for t in d["service_tags"]]
    if d["has_parking"]:
        chips.append('<span class="chip chip-soft">🅿 주차 가능</span>')
    is_open, today_hours, closed = open_status(d)
    badge = (
        '<span class="open-badge open">영업 중</span>' if is_open
        else '<span class="open-badge">휴무</span>' if closed
        else '<span class="open-badge">영업 전 · 후</span>'
    )
    st.html(
        f"""
        <div class="detail-summary">
            <h2>{html.escape(salon["name"])} {verified}</h2>
            {rating}
            <p class="hours-line">{badge} <span>{html.escape(today_hours)}</span></p>
            {"".join(f"<p>{line}</p>" for line in lines)}
            <div class="chips">{"".join(chips)}</div>
        </div>
        """
    )


def detail_photos(salon):
    # 사진: 크게 한 장 + 아래 작은 사진들. 작은 사진 단추로 큰 사진을 바꾼다
    sources = [s for s in (photo_source(u) for u in salon["details"]["photo_urls"]) if s]
    if not sources:
        st.html(svg_img(salon_thumb_svg(), "salon-photo"))
        return
    key = f"photo_{salon['salon_id']}"
    # 처음이거나, 고른 단추를 다시 눌러 선택이 풀렸으면(None) 첫 사진
    if st.session_state.get(key) not in range(len(sources)):
        st.session_state[key] = 0
    choice = st.session_state[key]
    st.image(sources[choice], width="stretch")
    st.caption(f"📷 {choice + 1} / {len(sources)}")
    if len(sources) > 1:
        st.segmented_control(
            "사진 고르기",
            list(range(len(sources))),
            format_func=lambda i: f"{i + 1}",
            key=key,
            label_visibility="collapsed",
        )


def price_card(details):
    with st.container(border=True, key="price_card"):
        st.markdown("**주요 시술 가격**")
        if not details["price_list"]:
            st.caption("가격 정보 준비 중이에요")
        rows = "".join(
            f'<div class="price-row"><span>{html.escape(item.get("name", ""))}</span>'
            f'<b>{int(item.get("price", 0)):,}원~</b></div>'
            for item in details["price_list"]
        )
        st.html(f'<div class="price-list">{rows}</div>')


def hours_card(details):
    with st.container(border=True, key="hours_card"):
        st.markdown("**영업시간**")
        rows = [("평일", details["hours_weekday"]), ("주말", details["hours_weekend"])]
        body = "".join(
            f'<div class="price-row"><span>{label}</span><b>{html.escape((value or "-").replace("-", " - "))}</b></div>'
            for label, value in rows
        )
        closed = f'<p class="closed">{html.escape(details["closed_days"])} 휴무</p>' if details["closed_days"] else ""
        st.html(f'<div class="price-list">{body}</div>{closed}')


def salon_detail():
    # 맨 위 메뉴 줄 → 왼쪽 사진 · 이름 · 별점 · 주소 · 태그 | 오른쪽 위치 지도 + 탭(헤어샵 정보 · 디자이너 · 이직 등록)
    salon = st.session_state.salons[st.session_state.selected]
    details = salon["details"]
    side, body = page_frame()
    with side:
        detail_photos(salon)
        detail_summary(salon)
        st.divider()
        back_button()
        st.warning("아직 예시 결과입니다 · 별점 · 가격 · 영업시간은 샘플이에요")

    with body:
        # 등록한 위치를 네이버 지도에 표시한다. 키나 좌표가 없으면 지도 자리만 보인다
        with st.container(key="map_area"):
            if not naver_map([salon], DETAIL_MAP_HEIGHT):
                with st.container(
                    border=True,
                    height=DETAIL_MAP_HEIGHT,
                    horizontal_alignment="center",
                    vertical_alignment="center",
                ):
                    st.markdown(f"📍 **{salon['name']}**")
                    st.caption(salon["location"])

        info_tab, designers_tab, move_tab = st.tabs(
            ["헤어샵 정보", f"디자이너 {len(salon['stylists'])}", "이직 등록"]
        )
        with info_tab:
            if details["description"]:
                st.html(f'<p class="description">{html.escape(details["description"])}</p>')
            price_col, hours_col = st.columns(2)
            with price_col:
                price_card(details)
            with hours_col:
                hours_card(details)
        with designers_tab:
            designer_cards(salon)
        with move_tab:
            input_col, result_col = st.columns(2)
            with input_col:
                # 넣는 자리 + 버튼: 이직 등록을 누르면 이 헤어샵 소속 디자이너 목록에 추가된다
                st.text_input("디자이너 이름", placeholder="예: 디자이너 4", key="move_name")
                move_closed = use_supabase() and not DB_WRITE_OPEN
                st.button("이직 등록", type="primary", width="stretch", on_click=register_move,
                          disabled=move_closed, help=DB_WRITE_CLOSED if move_closed else None)
            with result_col:
                # 결과 자리: 등록하자마자 이 탭에서 바로 확인할 수 있게 소속 디자이너 목록을 함께 둔다
                stylist_list(salon, 220)


PORTFOLIO_FILTERS = ["전체", "컷", "펌", "염색", "클리닉", "스타일링"]
PORTFOLIO_PAGE = 6  # 처음에 보여 줄 포트폴리오 수. 「포트폴리오 더보기」로 더 연다


@st.cache_data(show_spinner=False)
def thumb_uri(path, width):
    # 프로젝트 안 그림을 width 픽셀로 줄여 페이지 안에 바로 넣을 글자(base64)로 바꾼다
    from PIL import Image
    import io

    image = Image.open(path).convert("RGB")
    image.thumbnail((width, width * 2), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def picture(url, width):
    # 사진 주소 → 화면에 넣을 주소 (http 는 그대로, 프로젝트 안 파일은 줄여서). 없으면 None
    source = photo_source(url)
    if not source:
        return None
    return source if source.startswith("http") else thumb_uri(source, width)


def portfolio_rows():
    # 포트폴리오 전체 (supabase_portfolio_details.sql 로 더한 칸까지). 한 번만 읽어 둔다
    if "portfolio_rows" not in st.session_state:
        try:
            rows = read_table("portfolios", "portfolio_id")
        except urllib.error.URLError:
            rows = []
        st.session_state.portfolio_rows = [
            {
                "id": row["portfolio_id"],
                "stylist_id": row.get("stylist_id"),
                "title": row.get("title") or "",
                "description": row.get("description") or "",
                "photo_url": row.get("photo_url") or "",
                "service_type": row.get("service_type") or "기타",
                "style_name": row.get("style_name") or "",
                "like_count": number_or(row.get("like_count"), int) or 0,
                "hashtags": items_of(row.get("hashtags")),
                "created_at": row.get("created_at") or "",
            }
            for row in rows
        ]
    return st.session_state.portfolio_rows


def find_designer(designer_id):
    # 디자이너 번호 → (헤어샵 번호, 헤어샵, 디자이너). 없으면 (None, None, None)
    for index, salon in enumerate(st.session_state.salons):
        for designer in salon.get("designers", []):
            if designer["id"] == designer_id:
                return index, salon, designer
    return None, None, None


def open_designer(designer_id):
    # 디자이너 상세로 간다. 「목록으로 돌아가기」를 위해 지금 화면을 기억한다
    st.session_state.prev_page = st.session_state.page
    st.session_state.selected_designer = designer_id
    go("디자이너 상세")


def go_back():
    go(st.session_state.get("prev_page") or "꽃사슴")


def designer_side(salon_index, salon, designer):
    # 왼쪽: 프로필 사진 · 이름 · 직급 · 별점 · 근무 매장 · 버튼 · 경력/특기/소개/인스타그램 · 리뷰 요약 · 근무 매장 카드
    profile = designer["profile"]
    st.button("‹ 목록으로 돌아가기", key="designer_back", type="tertiary", on_click=go_back)
    photo = picture(profile["photo_url"], 520) or thumb_uri(str(designer_photo(designer["id"])), 520)
    rating = profile["rating_avg"]
    rating_html = (
        f'<p class="pro-rating"><span class="star">★</span> <b>{rating:.1f}</b> '
        f'<span class="muted">({profile["review_count"]})</span></p>'
        if rating is not None else '<p class="pro-rating muted">아직 별점이 없어요</p>'
    )
    st.html(
        f"""
        <div class="pro-head">
            <img class="pro-photo" src="{photo}" alt="{html.escape(designer["name"])}">
            <h2>{html.escape(designer["name"])} <span class="pro-title">{html.escape(profile["job_title"] or designer_role(designer["career"]))}</span></h2>
            {rating_html}
            <p class="muted">📍 {html.escape(salon["name"])}</p>
        </div>
        """
    )
    st.button("예약하기", key="pro_book", type="primary", width="stretch", disabled=True, help=NOT_READY)
    st.button("💬 1:1 상담하기", key="pro_chat", width="stretch", disabled=True, help=NOT_READY)

    instagram = f'@{html.escape(profile["instagram"])}' if profile["instagram"] else "-"
    rows = [
        ("🗓", "경력", f'{designer["career"]}년'),
        ("✂", "특기", html.escape(", ".join(profile["specialties"]) or "-")),
        ("✎", "소개", html.escape(profile["bio"] or "-")),
        ("◎", "인스타그램", instagram),
    ]
    st.html(
        '<div class="pro-facts">'
        + "".join(
            f'<div class="fact"><span class="fact-label">{icon} {label}</span><span>{value}</span></div>'
            for icon, label, value in rows
        )
        + "</div>"
    )

    # 고객 리뷰 요약: 평균 별점 + 키워드 (리뷰 목록은 아직 없다)
    keywords = "".join(
        f'<span class="kw">{html.escape(k.get("label", ""))} ({k.get("count", 0)})</span>'
        for k in profile["review_keywords"]
    )
    st.html(
        f"""
        <div class="pro-section">
            <h4>고객 리뷰 <span class="muted">({profile["review_count"]})</span></h4>
            <p class="big-rating">{f"{rating:.1f}" if rating is not None else "-"} <span class="star">{stars(rating) if rating is not None else ""}</span></p>
            <div class="kws">{keywords or '<span class="muted">아직 리뷰 키워드가 없어요</span>'}</div>
        </div>
        """
    )
    st.button("리뷰 더보기 ›", key="pro_reviews_more", type="tertiary", disabled=True, help=NOT_READY)

    # 근무 매장 카드: 헤어샵 사진 · 이름 · 별점 · 주소 · 교통 · 주차 · 「매장 정보 보기」
    d = salon["details"]
    shop_photo = picture(d["thumbnail_url"], 240)
    shop_img = f'<img src="{shop_photo}" alt="">' if shop_photo else ""
    shop_rating = (
        f'<p><span class="star">★</span> {d["rating_avg"]:.1f} <span class="muted">({d["review_count"]})</span></p>'
        if d["rating_avg"] is not None else ""
    )
    chips = []
    if d["transit_info"]:
        chips.append(f'<span class="chip chip-soft">{html.escape(d["transit_info"])}</span>')
    if d["has_parking"]:
        chips.append('<span class="chip chip-soft">주차 가능</span>')
    address = " ".join(x for x in (salon["location"].strip(), d["address_detail"]) if x)
    st.html(
        f"""
        <div class="pro-section">
            <h4>근무 매장</h4>
            <div class="shop-card">{shop_img}<div><b>{html.escape(salon["name"])}</b>{shop_rating}</div></div>
            <p class="muted">{html.escape(address)}</p>
            <div class="chips">{"".join(chips)}</div>
        </div>
        """
    )
    st.button("매장 정보 보기 ›", key="pro_shop", width="stretch", on_click=open_detail, args=(salon_index,))


def portfolio_card(item):
    photo = picture(item["photo_url"], 420)
    image = f'<img src="{photo}" alt="">' if photo else '<div class="pf-noimg"></div>'
    badge = f'<span class="pf-badge">{html.escape(item["style_name"])}</span>' if item["style_name"] else ""
    tags = " ".join(f"#{html.escape(t)}" for t in item["hashtags"])
    return f"""
    <div class="pf-card">
        <div class="pf-photo">{image}<span class="pf-like">♡ {item["like_count"]}</span>{badge}</div>
        <div class="pf-body">
            <h5>{html.escape(item["title"])}</h5>
            <p>{html.escape(item["description"])}</p>
            <p class="pf-tags">{tags}</p>
        </div>
    </div>
    """


def portfolio_tab(designer):
    mine = [p for p in portfolio_rows() if p["stylist_id"] == designer["id"]]
    key = f"pf_filter_{designer['id']}"
    if st.session_state.get(key) not in PORTFOLIO_FILTERS:
        st.session_state[key] = "전체"
    picked = st.pills("시술 종류", PORTFOLIO_FILTERS, key=key, label_visibility="collapsed") or "전체"
    shown = [p for p in mine if picked == "전체" or p["service_type"] == picked]

    count_col, sort_col = st.columns([4, 1], vertical_alignment="center")
    with count_col:
        st.html(f'<h4 class="pf-count">{html.escape(picked)} 포트폴리오 <span>{len(shown)}</span></h4>')
    with sort_col:
        order = st.selectbox("정렬", ["최신순", "인기순"], key=f"pf_sort_{designer['id']}", label_visibility="collapsed")
    if order == "인기순":
        shown.sort(key=lambda p: p["like_count"], reverse=True)
    else:
        shown.sort(key=lambda p: (p["created_at"], p["id"]), reverse=True)

    if not shown:
        st.caption("이 시술 종류의 포트폴리오가 아직 없어요.")
        return
    more_key = f"pf_more_{designer['id']}"
    limit = len(shown) if st.session_state.get(more_key) else PORTFOLIO_PAGE
    st.html('<div class="pf-grid">' + "".join(portfolio_card(p) for p in shown[:limit]) + "</div>")
    if len(shown) > limit:
        st.button("포트폴리오 더보기 ⌄", key=f"pf_more_btn_{designer['id']}", width="stretch",
                  on_click=lambda: st.session_state.update({more_key: True}))


def menu_tab(profile):
    if not profile["service_menu"]:
        st.caption("시술 메뉴 준비 중이에요")
        return
    rows = "".join(
        f'<div class="menu-row"><span>{html.escape(m.get("name", ""))}</span>'
        f'<span class="muted">{m.get("minutes", "-")}분</span><b>{int(m.get("price", 0)):,}원~</b></div>'
        for m in profile["service_menu"]
    )
    st.html(f'<div class="menu-list">{rows}</div>')


def reviews_tab(profile):
    keywords = profile["review_keywords"]
    top = max([k.get("count", 0) for k in keywords] or [1])
    bars = "".join(
        f'<div class="kw-bar"><span>{html.escape(k.get("label", ""))}</span>'
        f'<div class="bar"><i style="width:{round(100 * k.get("count", 0) / top)}%"></i></div>'
        f'<b>{k.get("count", 0)}</b></div>'
        for k in keywords
    )
    st.html(f'<div class="kw-bars">{bars or "<p>아직 리뷰가 없어요</p>"}</div>')
    st.caption("리뷰 글 목록은 " + NOT_READY)


def designer_detail():
    # 맨 위 메뉴 줄 → 왼쪽 프로필 · 리뷰 요약 · 근무 매장 | 오른쪽 탭(포트폴리오 · 시술 메뉴 · 고객 리뷰 · 시술 스타일)
    salon_index, salon, designer = find_designer(st.session_state.get("selected_designer"))
    side, body = page_frame()
    if designer is None:
        with side:
            st.button("‹ 목록으로 돌아가기", key="designer_back", type="tertiary", on_click=go_back)
        with body:
            st.info("디자이너 정보를 찾지 못했어요.")
        return
    profile = designer["profile"]
    # 이 화면에서는 위 메뉴 밑줄을 「디자이너 찾기」에 둔다
    st.html(
        f"""<style>
        .st-key-nav_find button {{ border-bottom: 0 !important; }}
        .st-key-nav_find button p {{ color: {THEME_TEXT} !important; font-weight: 600 !important; }}
        .st-key-nav_designer button {{ border-bottom: 3px solid {THEME_ACCENT} !important; border-radius: 0; }}
        .st-key-nav_designer button p {{ color: {THEME_ACCENT} !important; font-weight: 700; opacity: 1 !important; }}
        </style>"""
    )
    with side:
        designer_side(salon_index, salon, designer)
    with body:
        pf_tab, menu, reviews, styles = st.tabs(
            ["포트폴리오", "시술 메뉴", f"고객 리뷰 ({profile['review_count']})", "시술 스타일"]
        )
        with pf_tab:
            portfolio_tab(designer)
        with menu:
            menu_tab(profile)
        with reviews:
            reviews_tab(profile)
        with styles:
            st.caption("시술 스타일은 " + NOT_READY)
        st.html(
            '<div class="tip"><span>💡</span><div><b>예약 팁</b>'
            "<p>원하시는 스타일의 사진을 가지고 상담하시면 더 정확한 스타일 추천을 받으실 수 있어요!</p></div></div>"
        )


# 첫 화면에 보여 줄 하는 일 세 가지 (PRD.md 사용자 흐름·넣을 기능에서 지금 쓸 수 있는 것)
# 아이콘은 이모지 대신 강조색 선 그림(SVG)으로 그린다
LANDING_FEATURES = [
    (
        '<path d="M8 14l14-6 14 6 14-6v34l-14 6-14-6-14 6z"/><path d="M22 8v34M36 14v34"/>',
        "근처 헤어샵 둘러보기",
        "지역을 고르면 등록된 헤어샵 목록과 지도 위치를 한눈에 볼 수 있어요.",
    ),
    (
        '<path d="M29 52s-15-15-15-27a15 15 0 0 1 30 0c0 12-15 27-15 27z"/><circle cx="29" cy="25" r="5"/>',
        "새 헤어샵 등록",
        "헤어샵 이름, 연락처, 지도 위치를 넣으면 지도에 표시되고 다른 디자이너도 소속 헤어샵으로 쓸 수 있어요.",
    ),
    (
        '<circle cx="16" cy="42" r="7"/><circle cx="40" cy="42" r="7"/><path d="M21 37L44 8M35 37L12 8"/>',
        "이직 등록",
        "헤어샵 세부정보에서 이직 등록을 하면 예전 고객이 디자이너의 새 소속을 확인할 수 있어요.",
    ),
]

# 첫 화면 글씨체: 학교안심 떡볶이 (굵은 한 가지 굵기뿐). 크기가 작은 OTF 를 쓴다. 파일이 없으면 기본 글씨체
LANDING_FONT = Path(__file__).parent / "assets" / "fonts" / "학교안심 떡볶이" / "Hakgyoansim_TteokbokkiOTFB.otf"


@st.cache_data(show_spinner=False)
def font_data_uri(mtime):
    # 글씨체 파일을 페이지 안에 바로 넣을 수 있게 글자(base64)로 바꾼다
    return "data:font/otf;base64," + base64.b64encode(LANDING_FONT.read_bytes()).decode("ascii")


def landing_font_css():
    # 첫 화면 글자(제목·소개·카드·「시작하기」)에만 떡볶이체를 입힌다. 글씨체 자체가 굵어서 더 굵게 칠하지 않는다
    if not LANDING_FONT.exists():
        return ""
    src = font_data_uri(LANDING_FONT.stat().st_mtime)
    return f"""
        @font-face {{
            font-family: "Hakgyoansim Tteokbokki";
            src: url("{src}") format("opentype");
            font-display: swap;
        }}
        .landing, .landing *, .st-key-start button p {{
            font-family: "Hakgyoansim Tteokbokki", sans-serif !important;
            font-weight: normal !important;
        }}
    """


def awning_scallops():
    # 차양 아래 둥근 술: 줄무늬와 같은 색 순서(흰색 · 강조색)로 번갈아 단다
    return "".join(
        f'<circle cx="{1008 + 32 * j}" cy="140" r="16" fill="{"#ffffff" if j % 2 == 0 else THEME_ACCENT}"/>'
        for j in range(18)
    )


def svg_img(svg, css_class):
    # Streamlit 의 HTML 필터가 <svg> 를 지우므로, 그림 파일(<img>)처럼 바꿔 넣는다
    src = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img class="{css_class}" src="{src}" alt="">'


def storefront_scene(logo):
    # 히어로 배경 그림: 흰 타일 벽 + 걸린 꽃사슴 간판 + 드라이기 원형 간판 + OPEN 입간판 + 차양 달린 헤어샵 창문 + 화분
    # 그림 파일 안에서는 페이지의 글씨체·CSS 를 못 쓰므로, 움직임과 떡볶이체를 그림 안에 함께 넣는다
    font = (
        f'@font-face {{ font-family: "Hakgyoansim Tteokbokki"; '
        f'src: url("{font_data_uri(LANDING_FONT.stat().st_mtime)}") format("opentype"); }}'
        if LANDING_FONT.exists()
        else ""
    )
    return f"""
    <svg viewBox="0 0 1600 600" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg"
         xmlns:xlink="http://www.w3.org/1999/xlink">
      <style>
        {font}
        .scene-text {{ font-family: "Hakgyoansim Tteokbokki", sans-serif; }}
        .air {{ animation: air 1.6s ease-out infinite; }}
        .air:nth-of-type(2) {{ animation-delay: 0.25s; }}
        .air:nth-of-type(3) {{ animation-delay: 0.5s; }}
        @keyframes air {{ 0% {{ opacity: 0; transform: translateX(-4px); }} 40% {{ opacity: 1; }} 100% {{ opacity: 0; transform: translateX(6px); }} }}
        .swing {{ transform-origin: 150px 124px; animation: swing 5s ease-in-out infinite; }}
        @keyframes swing {{ 0%, 100% {{ transform: rotate(-1.5deg); }} 50% {{ transform: rotate(1.5deg); }} }}
      </style>
      <defs>
        <pattern id="tile" width="80" height="80" patternUnits="userSpaceOnUse">
          <rect width="80" height="80" fill="#ffffff"/>
          <path d="M0 1H80M0 41H80M40 0V40M1 40V80" stroke="{THEME_LIGHT}" stroke-width="2" fill="none"/>
        </pattern>
        <pattern id="awning" width="64" height="10" patternUnits="userSpaceOnUse">
          <rect width="32" height="10" fill="{THEME_ACCENT}"/><rect x="32" width="32" height="10" fill="#ffffff"/>
        </pattern>
        <clipPath id="logo-clip"><circle cx="150" cy="232" r="50"/></clipPath>
      </defs>
      <rect width="1600" height="600" fill="url(#tile)"/>
      <rect y="530" width="1600" height="12" fill="{THEME_LIGHT}"/>
      <rect y="542" width="1600" height="58" fill="{THEME_SOFT}"/>

      <!-- 벽에 걸린 꽃사슴 간판 -->
      <rect x="40" y="114" width="230" height="10" rx="5" fill="{THEME_TEXT}"/>
      <path d="M84 124V152M216 124V152" stroke="{THEME_TEXT}" stroke-width="4"/>
      <g class="swing">
        <rect x="60" y="150" width="180" height="204" rx="22" fill="{THEME_ACCENT}"/>
        <rect x="72" y="162" width="156" height="180" rx="16" fill="none" stroke="#ffffff" stroke-width="4"/>
        <circle cx="150" cy="232" r="56" fill="#ffffff"/>
        <image href="{logo}" xlink:href="{logo}" x="100" y="182" width="100" height="100" clip-path="url(#logo-clip)"/>
        <text x="150" y="322" text-anchor="middle" font-size="32" fill="#ffffff" class="scene-text">꽃사슴</text>
      </g>

      <!-- 드라이기 원형 간판 (바람이 살랑 나온다). 꽃사슴 간판과 붙지 않게 조금 옮겨 단다 -->
      <g transform="translate(18 14)">
      <circle cx="300" cy="166" r="5" fill="{THEME_TEXT}"/>
      <path d="M300 166L270 202M300 166L330 202" stroke="{THEME_TEXT}" stroke-width="3" fill="none"/>
      <circle cx="300" cy="250" r="58" fill="#ffffff" stroke="{THEME_ACCENT}" stroke-width="7"/>
      <circle cx="300" cy="250" r="47" fill="none" stroke="{THEME_LIGHT}" stroke-width="2"/>
      <rect x="272" y="252" width="16" height="36" rx="7" fill="{THEME_TEXT}" transform="rotate(-10 280 252)"/>
      <rect x="292" y="229" width="28" height="22" rx="5" fill="{THEME_ACCENT}"/>
      <rect x="318" y="225" width="7" height="30" rx="3" fill="{THEME_TEXT}"/>
      <circle cx="280" cy="240" r="22" fill="{THEME_ACCENT}"/>
      <circle cx="280" cy="240" r="10" fill="#ffffff"/>
      <path d="M274 240H286M280 234V246" stroke="{THEME_LIGHT}" stroke-width="2"/>
      <g fill="none" stroke="{THEME_MID}" stroke-width="3" stroke-linecap="round">
        <path class="air" d="M331 230q4 3 0 6q-4 3 0 6"/>
        <path class="air" d="M337 236q4 3 0 6q-4 3 0 6"/>
        <path class="air" d="M331 244q4 3 0 6q-4 3 0 6"/>
      </g>
      </g>

      <!-- OPEN 입간판 -->
      <path d="M96 540L136 396M224 540L184 396" stroke="{THEME_TEXT}" stroke-width="8" stroke-linecap="round"/>
      <rect x="104" y="404" width="112" height="110" rx="10" fill="{THEME_TEXT}"/>
      <rect x="112" y="412" width="96" height="94" rx="6" fill="none" stroke="#ffffff" stroke-width="2" opacity="0.6"/>
      <text x="160" y="452" text-anchor="middle" font-size="26" fill="#ffffff" class="scene-text">OPEN</text>
      <g stroke="#ffffff" stroke-width="3" fill="none">
        <circle cx="148" cy="488" r="6"/><circle cx="172" cy="488" r="6"/><path d="M152 483L176 466M168 483L144 466"/>
      </g>

      <!-- 차양 달린 헤어샵 창문 -->
      <rect x="984" y="56" width="592" height="18" rx="9" fill="{THEME_TEXT}"/>
      <rect x="992" y="72" width="576" height="68" fill="url(#awning)"/>
      {awning_scallops()}
      <rect x="1020" y="172" width="520" height="340" rx="10" fill="#ffffff"/>
      <rect x="1036" y="188" width="488" height="308" rx="6" fill="{THEME_SOFT}"/>
      <rect x="1274" y="188" width="12" height="308" fill="#ffffff"/>
      <path d="M1066 470L1150 210M1100 480L1170 270" stroke="#ffffff" stroke-width="10" opacity="0.5"/>
      <ellipse cx="1155" cy="296" rx="66" ry="86" fill="#ffffff" stroke="{THEME_MID}" stroke-width="8"/>
      <rect x="1118" y="342" width="74" height="64" rx="16" fill="{THEME_ACCENT}"/>
      <rect x="1104" y="400" width="102" height="22" rx="8" fill="{THEME_TEXT}"/>
      <rect x="1150" y="422" width="10" height="40" fill="{THEME_TEXT}"/>
      <rect x="1120" y="460" width="70" height="10" rx="5" fill="{THEME_TEXT}"/>
      <rect x="1306" y="326" width="196" height="8" rx="4" fill="#ffffff"/>
      <rect x="1322" y="276" width="24" height="50" rx="6" fill="{THEME_ACCENT}"/>
      <rect x="1356" y="292" width="20" height="34" rx="6" fill="{THEME_MID}"/>
      <rect x="1386" y="268" width="26" height="58" rx="6" fill="#ffffff"/>
      <rect x="1422" y="288" width="22" height="38" rx="6" fill="{THEME_ACCENT}" opacity="0.7"/>
      <rect x="1454" y="280" width="30" height="46" rx="8" fill="{THEME_MID}"/>
      <rect x="1306" y="426" width="196" height="8" rx="4" fill="#ffffff"/>
      <circle cx="1336" cy="408" r="18" fill="#ffffff"/><circle cx="1376" cy="408" r="18" fill="{THEME_LIGHT}"/>
      <circle cx="1416" cy="408" r="18" fill="#ffffff"/><circle cx="1456" cy="408" r="18" fill="{THEME_LIGHT}"/>
      <rect x="1010" y="508" width="540" height="16" rx="4" fill="#ffffff"/>

      <!-- 화분 -->
      <g>
        <ellipse cx="948" cy="452" rx="16" ry="38" fill="#86A98F" transform="rotate(-24 948 452)"/>
        <ellipse cx="972" cy="440" rx="16" ry="44" fill="#9BBBA2"/>
        <ellipse cx="996" cy="452" rx="16" ry="38" fill="#86A98F" transform="rotate(24 996 452)"/>
        <circle cx="952" cy="420" r="9" fill="{THEME_ACCENT}"/><circle cx="990" cy="414" r="9" fill="{THEME_MID}"/>
        <path d="M940 540L1004 540L996 478L948 478Z" fill="{THEME_ACCENT}"/>
      </g>
    </svg>
    """


def falling_petals():
    # 히어로 위로 천천히 떨어지는 꽃잎 몇 장 (CSS 애니메이션, 마우스는 통과)
    petals = [(8, 11, 0), (22, 14, 4), (37, 12, 7), (55, 16, 2), (68, 13, 9), (83, 15, 5), (93, 12, 11)]
    return "".join(
        f'<span class="petal" style="left:{left}%; animation-duration:{dur}s; animation-delay:-{delay}s"></span>'
        for left, dur, delay in petals
    )


def landing():
    # 첫 화면: 헤어샵 가게 앞 거리 그림 위에 큰 제목 · 소개 · 「시작하기」를 올리고,
    # 아래에는 하는 일 세 가지를 벽에 붙인 포스터처럼 건다. 사이드바는 숨긴다
    cards = "".join(
        f"""
        <div class="poster">
            <div class="poster-art">{svg_img(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 58 58" fill="none" stroke="{THEME_ACCENT}" '
                f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round">{icon}</svg>',
                "poster-icon",
            )}</div>
            <h3>{html.escape(title)}</h3>
            <p>{html.escape(text)}</p>
        </div>
        """
        for icon, title, text in LANDING_FEATURES
    )
    st.html(
        f"""
        <style>
        [data-testid="stApp"], [data-testid="stHeader"] {{ background: {THEME_BG}; }}
        [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {{ display: none; }}
        {landing_font_css()}
        /* 히어로 칸: 가게 앞 그림을 바닥에 깔고, 제목·소개·버튼은 간판과 창문 사이에 왼쪽 맞춤으로 올린다 */
        .st-key-hero {{
            position: relative; overflow: hidden; border-radius: 28px;
            min-height: 560px; justify-content: center; gap: 1.5rem;
            padding: 0 2rem 3rem 25%;
            box-shadow: 0 10px 30px {rgba(THEME_TEXT, 0.08)};
        }}
        .st-key-hero div:has(.hero-bg) {{ position: static !important; }}
        .st-key-hero > div:not(:has(.hero-bg)) {{ position: relative; z-index: 1; }}
        .hero-bg {{ position: absolute; inset: 0; z-index: 0; pointer-events: none; }}
        .scene {{ width: 100%; height: 100%; display: block; object-fit: cover; }}
        .petal {{
            position: absolute; top: -30px; width: 14px; height: 18px; opacity: 0.75;
            background: {THEME_MID}; border-radius: 80% 0 80% 0;
            animation-name: fall; animation-timing-function: linear; animation-iteration-count: infinite;
        }}
        @keyframes fall {{
            0% {{ transform: translate(0, 0) rotate(0deg); }}
            50% {{ transform: translate(30px, 320px) rotate(180deg); }}
            100% {{ transform: translate(-10px, 640px) rotate(360deg); }}
        }}
        .landing {{ color: {THEME_TEXT}; }}
        .hero-copy h1 {{ font-size: 3.6rem; line-height: 1.25; margin: 0; color: {THEME_TEXT}; }}
        .hero-copy h1 span {{ color: {THEME_ACCENT}; }}
        .hero-copy p {{ font-size: 1.4rem; margin: 1.1rem 0 0; color: {THEME_TEXT}; }}
        .st-key-start button {{
            background: {THEME_ACCENT}; border-color: {THEME_ACCENT}; color: #ffffff;
            padding: 0.6rem 2.6rem; border-radius: 999px; box-shadow: 0 6px 16px {rgba(THEME_ACCENT, 0.3)};
        }}
        /* 버튼 글자는 Streamlit 이 안쪽 글자(p)에 크기를 따로 정해서, 그 글자에 크기를 준다 */
        .st-key-start button p {{ font-size: 1.3rem; }}
        .st-key-start button:hover {{ filter: brightness(0.92); color: #ffffff; }}
        /* 아래 포스터: 흰 액자에 테이프로 붙인 듯 살짝 기울여 건다 */
        .posters-title {{ text-align: center; font-size: 1.6rem; margin: 3rem 0 0; color: {THEME_TEXT}; }}
        .posters {{ display: flex; gap: 2rem; justify-content: center; flex-wrap: wrap; padding: 2rem 1rem 1rem; }}
        .poster {{
            position: relative; flex: 1 1 240px; max-width: 300px; background: #ffffff;
            border: 10px solid #ffffff; outline: 1px solid {rgba(THEME_TEXT, 0.08)};
            box-shadow: 0 10px 24px {rgba(THEME_TEXT, 0.12)}; padding-bottom: 1rem;
            transform: rotate(-1.2deg); transition: transform 0.2s;
        }}
        .poster:nth-child(2) {{ transform: rotate(1deg); }}
        .poster:nth-child(3) {{ transform: rotate(-0.6deg); }}
        .poster:hover {{ transform: rotate(0) translateY(-4px); }}
        .poster::before {{
            content: ""; position: absolute; top: -18px; left: 50%; width: 90px; height: 26px;
            transform: translateX(-50%) rotate(-3deg); background: {rgba(THEME_ACCENT, 0.25)};
        }}
        .poster-art {{
            height: 140px; display: flex; align-items: center; justify-content: center;
            background: repeating-linear-gradient(0deg, {THEME_SOFT} 0 38px, {THEME_LIGHT} 38px 40px);
        }}
        .poster-icon {{ width: 72px; height: 72px; background: #ffffff; border-radius: 50%; padding: 14px; }}
        .poster h3 {{ font-size: 1.35rem; margin: 1rem 0.75rem 0.5rem; color: {THEME_TEXT}; }}
        .poster p {{ font-size: 1.05rem; line-height: 1.6; margin: 0 0.75rem; color: {THEME_TEXT}; }}
        /* 좁은 화면: 그림을 옅게 깔고 글은 왼쪽부터 */
        @media (max-width: 900px) {{
            .st-key-hero {{ padding: 2rem 1.5rem; }}
            .scene {{ opacity: 0.35; }}
            .hero-copy h1 {{ font-size: 2.4rem; }}
        }}
        </style>
        """
    )
    # 간판 속 캐릭터: 챗봇 아이콘과 같은 꽃사슴 그림(assets/icons/bot.png 얼굴 부분)을 동그랗게 잘라 쓴다
    logo = "data:image/png;base64," + base64.b64encode(
        chatbot.icon_image(chatbot.ICON_PATH.stat().st_mtime)
    ).decode("ascii")
    with st.container(key="hero"):
        st.html(f'<div class="hero-bg">{svg_img(storefront_scene(logo), "scene")}{falling_petals()}</div>')
        st.html(
            """
            <div class="landing hero-copy">
                <h1>헤어샵은 바뀌어도,<br><span>내 디자이너는 그대로.</span></h1>
                <p>단골 디자이너의 새 헤어샵, 꽃사슴에서 바로 확인하세요.</p>
            </div>
            """
        )
        st.button("시작하기", key="start", type="primary", on_click=go, args=("꽃사슴",))
    st.html(
        f"""
        <div class="landing">
            <h2 class="posters-title">꽃사슴으로 할 수 있는 일</h2>
            <div class="posters">{cards}</div>
        </div>
        """
    )

pages = {
    "첫 화면": landing,
    "꽃사슴": nearby_salons,
    "새 헤어샵 등록": new_salon,
    "헤어샵 세부정보": salon_detail,
    "디자이너 상세": designer_detail,
}
pages[st.session_state.page]()

# 저작권: 어느 화면에서든 맨 아래에 한 줄
st.caption("© 2026 gold9ine", text_alignment="center")

# 상담 챗봇: 어느 화면에서든 오른쪽 아래 아이콘으로 연다. Supabase 가 있고 쓰기가 열려 있으면 대화 기록을 남긴다
chatbot.render(
    read_env(ENV_PATH).get("ANTHROPIC_API_KEY", ""),
    supabase if use_supabase() and DB_WRITE_OPEN else None,
)
