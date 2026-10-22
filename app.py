import csv
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import streamlit as st

import chatbot

st.set_page_config(page_title="근처 미용실", layout="wide")

# 사이드바: 서비스 설명 한 줄 (PRD.md 목표 문장)
st.sidebar.write("미용사가 새 미용실 이름과 연락처를 등록하면 예전 고객이 미용사의 새 소속을 확인할 수 있게 해 줍니다.")

# 화면 이동: 지금 보여 줄 화면 이름을 session_state 에 둔다
if "page" not in st.session_state:
    st.session_state.page = "근처 미용실"

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


def load_salons():
    # 미용실(salons 표)에 소속 미용사(stylists 표)를 붙인다
    try:
        stylists = read_table("stylists", "stylist_id")
        salons = read_table("salons", "salon_id")
    except urllib.error.HTTPError as error:
        st.error(f"Supabase 에서 미용실 자료를 읽지 못했습니다 ({error.code}): {error.read().decode('utf-8')}")
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
            "coords": (float(row["lat"]), float(row["lng"])),
            "stylists": [s["name"] for s in stylists if s["salon_id"] == row["salon_id"]],
        }
        for row in salons
    ]


# 미용실 목록: Supabase 자료로 채운다 (.env 가 비어 있으면 CSV 로 채우고 새로 등록한 것은 이 세션 안에서만 들고 있는다)
if "salons" not in st.session_state:
    st.session_state.salons = load_salons()
    st.session_state.selected = 0

# 예전에 빈 이름으로 들어간 소속 미용사는 지운다
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


def naver_map(salons, height):
    # 네이버 지도에 미용실 핀을 찍는다. 핀을 누르면 이름·연락처·소속 미용사가 뜬다
    markers = [
        {
            "lat": salon["coords"][0],
            "lng": salon["coords"][1],
            "info": "<div style='padding:8px;font-size:13px'><b>{}</b><br>{}<br>{}</div>".format(
                html.escape(salon["name"]),
                html.escape(salon["phone"]),
                "<br>".join(html.escape(name) for name in salon["stylists"]),
            ),
        }
        for salon in salons
        if salon.get("coords")
    ]
    client_id, _ = naver_keys()
    if not (client_id and markers):
        return False
    # Streamlit 의 HTML 필터는 스크립트 안에 "<글자"가 있으면 스크립트를 통째로 지운다.
    # 팝업 HTML 의 "<" 를 < 로 바꿔 넣는다 (자바스크립트에서는 똑같이 "<" 로 읽힌다)
    data = json.dumps(markers).replace("<", "\\u003c")
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
                    }});
                    const info = new naver.maps.InfoWindow({{ content: m.info }});
                    naver.maps.Event.addListener(marker, "click", () => {{
                        info.getMap() ? info.close() : info.open(map, marker);
                    }});
                }});
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
    go("미용실 세부정보")


def reload_salons(salon_id):
    # Supabase 에 쓴 뒤 목록을 다시 읽고, 방금 다룬 미용실을 선택해 둔다
    st.session_state.salons = load_salons()
    ids = [salon["salon_id"] for salon in st.session_state.salons]
    st.session_state.selected = ids.index(salon_id) if salon_id in ids else 0


def register_salon():
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
            }
        )
        open_detail(len(st.session_state.salons) - 1)
        return
    # salons 표에 한 줄 넣는다. 로그인이 없으므로 미용실 주인(owner_stylist_id)은 비워 둔다
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
        st.session_state.save_error = f"미용실을 저장하지 못했습니다 {describe(error)}"
        return
    reload_salons(salon_id)
    go("미용실 세부정보")


def register_move():
    # 미용사 이름이 비어 있으면 아무것도 하지 않는다
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
            "GET", f"stylists?select=stylist_id,salon_id&name=eq.{urllib.parse.quote(name)}"
        )
        if len(matches) == 1:
            # 같은 이름의 미용사가 한 명 있으면: 이직 기록(moves)을 남기고 소속을 이 미용실로 바꾼다
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
                    f"stylists?stylist_id=eq.{urllib.parse.quote(stylist['stylist_id'])}",
                    {"salon_id": salon["salon_id"]},
                )
        else:
            # 처음 보는 이름이거나 동명이인이 여럿이면 새 미용사로 넣는다
            supabase(
                "POST",
                "stylists",
                {
                    "stylist_id": next_id("stylists", "stylist_id", "ST"),
                    "name": name,
                    "salon_id": salon["salon_id"],
                },
            )
    except urllib.error.URLError as error:
        st.session_state.save_error = f"이직 등록을 저장하지 못했습니다 {describe(error)}"
        return
    reload_salons(salon["salon_id"])


def back_button():
    st.button("← 근처 미용실", on_click=go, args=("근처 미용실",))


def header(title):
    # 머리: 왼쪽 위 로고 자리 + 가운데 화면 제목 (와이어프레임과 같은 배치)
    logo_col, title_col, _ = st.columns([1, 6, 1], vertical_alignment="center")
    with logo_col:
        with st.container(border=True, horizontal_alignment="center"):
            st.caption("로고")
    with title_col:
        st.title(title, text_alignment="center")
    st.divider()
    # 저장 실패 알림: 버튼을 누른 뒤 한 번만 보여 준다
    if "save_error" in st.session_state:
        st.error(st.session_state.pop("save_error"))


def nearby_salons():
    st.warning("아직 예시 결과입니다")
    header("근처 미용실")

    left, right = st.columns([1, 2])

    with left:
        # 넣는 자리: 지도 SDK가 없으므로 위치는 주소나 좌표 텍스트로 받는다
        st.text_input("내 위치", placeholder="예: 서울시 ○○구 ○○로 12 또는 37.5665, 126.9780")

        # 버튼
        st.button("새 미용실", width="stretch", on_click=go, args=("새 미용실 등록",))
        st.button("사용자 대시보드", width="stretch", on_click=go, args=("사용자 대시보드",))

        # 결과 자리: 등록한 미용실 목록 — 항목을 누르면 그 미용실 세부정보로 간다
        st.subheader("등록된 미용실 목록")
        for index, salon in enumerate(st.session_state.salons):
            st.button(
                f"**{salon['name']}**",
                key=f"list_{index}",
                width="stretch",
                on_click=open_detail,
                args=(index,),
            )
        st.caption("(지도 범위 내 목록)")

    with right:
        # 지도: 네이버 지도 키가 있으면 실제 지도에 핀을 찍는다
        if naver_map(st.session_state.salons, 420):
            # 지도 안 핀에서는 화면을 옮길 수 없어서, 자세히 보기는 지도 아래 핀 목록에 둔다
            with st.container(horizontal=True):
                salon_popovers()
        else:
            # 지도 자리: 핀을 누르면 미용실 정보가 지도 위에 겹쳐 뜬다
            with st.container(
                border=True,
                height=420,
                horizontal_alignment="center",
                vertical_alignment="center",
            ):
                salon_popovers()
                st.caption("(지도 자리 — 네이버 지도 키를 넣으면 실제 지도가 보입니다)")


def salon_popovers():
    for index, salon in enumerate(st.session_state.salons):
        with st.popover(salon["name"], icon="📍", type="tertiary"):
            st.markdown(f"**{salon['name']}**")
            st.write(salon["phone"])
            for name in salon["stylists"]:
                st.text(name)
            st.button(
                "자세히 보기",
                key=f"detail_{index}",
                width="stretch",
                on_click=open_detail,
                args=(index,),
            )


def new_salon():
    st.warning("아직 예시 결과입니다")
    header("새 미용실 등록")
    back_button()

    # 넣는 자리
    name_col, phone_col = st.columns(2)
    with name_col:
        st.text_input("미용실 이름", placeholder="예: 헤어스튜디오 봄", key="new_name")
    with phone_col:
        st.text_input("연락처", placeholder="예: 010-0000-0000", key="new_phone")

    # 지도 위치: 지도 SDK가 없으므로 주소나 좌표 텍스트로 받는다
    st.text_input(
        "지도 위치",
        placeholder="예: 서울시 ○○구 ○○로 12 또는 37.5665, 126.9780",
        key="new_location",
    )
    # 지도 위치를 입력하면 그 자리를 지도에 바로 보여 준다
    location = st.session_state.get("new_location", "")
    coords = geocode(location, *naver_keys())
    preview = {
        "name": st.session_state.get("new_name") or "새 미용실",
        "phone": st.session_state.get("new_phone", ""),
        "coords": coords,
        "stylists": [],
    }
    if not naver_map([preview], 240):
        with st.container(
            border=True,
            height=240,
            horizontal_alignment="center",
            vertical_alignment="center",
        ):
            st.markdown("📍 지도에서 위치 선택")
            if coords:
                st.caption(f"위도 {coords[0]}, 경도 {coords[1]}")
            st.caption("(지도 자리 — 네이버 지도 키를 넣으면 실제 지도가 보입니다)")
    if location.strip() and not coords:
        st.caption("입력한 위치를 지도에서 찾지 못했습니다.")

    # 버튼: 입력값을 Supabase 에 저장하고 등록한 미용실의 세부정보로 이동한다
    _, button_col, _ = st.columns([2, 1, 2])
    with button_col:
        st.button("등록", width="stretch", on_click=register_salon)


def salon_detail():
    st.warning("아직 예시 결과입니다")
    salon = st.session_state.salons[st.session_state.selected]
    header(f"{salon['name']} 세부정보")
    back_button()

    map_col, info_col = st.columns(2)

    with map_col:
        # 등록한 위치를 네이버 지도에 표시한다. 키나 좌표가 없으면 지도 자리만 보인다
        if not naver_map([salon], 480):
            with st.container(
                border=True,
                height=480,
                horizontal_alignment="center",
                vertical_alignment="center",
            ):
                st.markdown(f"📍 **{salon['name']}**")
                st.caption(salon["location"])

    # 결과 자리: 선택한 미용실 정보
    with info_col:
        st.subheader(salon["name"])
        # key 에 미용실 번호를 붙여, 다른 미용실로 바꿔도 값이 새로 그려지게 한다
        st.text_input(
            "상세주소",
            value=salon["location"],
            disabled=True,
            key=f"location_{st.session_state.selected}",
        )
        st.text_input(
            "전화번호",
            value=salon["phone"],
            disabled=True,
            key=f"phone_{st.session_state.selected}",
        )

        st.markdown("**소속 미용사**")
        for name in salon["stylists"]:
            with st.container(border=True):
                st.text(name)
        if not salon["stylists"]:
            st.caption("아직 소속 미용사가 없습니다.")

        # 넣는 자리 + 버튼: 이직 등록을 누르면 이 미용실 소속 미용사 목록에 추가된다
        st.text_input("미용사 이름", placeholder="예: 미용사 4", key="move_name")
        st.button("이직 등록", on_click=register_move)


def user_dashboard():
    # 사용자 대시보드: 지금은 화면 자리와 돌아가는 버튼만 있다
    st.warning("아직 예시 결과입니다")
    header("사용자 대시보드")
    back_button()


pages = {
    "근처 미용실": nearby_salons,
    "새 미용실 등록": new_salon,
    "미용실 세부정보": salon_detail,
    "사용자 대시보드": user_dashboard,
}
pages[st.session_state.page]()

# 저작권: 어느 화면에서든 맨 아래에 한 줄
st.caption("© 2026 gold9ine", text_alignment="center")

# 상담 챗봇: 어느 화면에서든 오른쪽 아래 아이콘으로 연다. Supabase 가 있으면 대화 기록을 남긴다
chatbot.render(read_env(ENV_PATH).get("ANTHROPIC_API_KEY", ""), supabase if use_supabase() else None)
