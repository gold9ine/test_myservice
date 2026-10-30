import json
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="한 줄 방명록")

# 이 파일 옆 .env 에서 Supabase 주소와 키를 읽는다 (KEY=VALUE 줄만, # 줄은 건너뜀)
ENV_PATH = Path(__file__).parent / ".env"


def read_env(path):
    env = {}
    # 올린 곳(Community Cloud)에는 .env 가 없으므로 배포 설정 Secrets 를 먼저 담는다. .env 가 있으면 아래에서 그 값으로 덮는다
    try:
        env.update({key: value for key, value in st.secrets.items() if isinstance(value, str)})
    except Exception:
        pass  # 내 컴퓨터에 Secrets 파일이 없으면 건너뛴다
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


env = read_env(ENV_PATH)
SUPABASE_URL = env.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = env.get("SUPABASE_KEY", "")
TABLE_URL = f"{SUPABASE_URL}/rest/v1/guestbook"


def request(method, url, body=None):
    # Supabase REST API 호출: 키를 apikey 와 Authorization 헤더에 함께 싣는다
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Prefer"] = "return=minimal"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as res:
        text = res.read().decode("utf-8")
        return json.loads(text) if text else None


st.title("한 줄 방명록")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 채워 주세요.")
    st.stop()

# 글쓰기: 한 줄을 넣고 남기기를 누르면 guestbook 표에 한 줄이 쌓인다
with st.form("write", clear_on_submit=True):
    message = st.text_input("한 줄 남기기", max_chars=200)
    submitted = st.form_submit_button("남기기")

if submitted:
    if message.strip():
        try:
            request("POST", TABLE_URL, {"message": message.strip()})
            st.success("남겼어요.")
        except urllib.error.HTTPError as e:
            st.error(f"저장 실패 ({e.code}): {e.read().decode('utf-8')}")
    else:
        st.warning("내용을 입력해 주세요.")

# 글 목록: 최근 글이 위로 오게 불러온다
try:
    rows = request("GET", f"{TABLE_URL}?select=message,created_at&order=created_at.desc&limit=100")
except urllib.error.HTTPError as e:
    st.error(f"불러오기 실패 ({e.code}): {e.read().decode('utf-8')}")
    st.stop()
except urllib.error.URLError as e:
    st.error(f"Supabase 에 연결하지 못했어요: {e.reason}")
    st.stop()

st.caption(f"{len(rows)}개의 글")
for row in rows:
    st.write(f"**{row['message']}**  \n{row['created_at'][:16].replace('T', ' ')}")
