import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="사진 보관함", layout="wide")

# 이 파일 옆 .env 에서 Supabase 주소와 키를 읽는다 (KEY=VALUE 줄만, # 줄은 건너뜀)
ENV_PATH = Path(__file__).parent / ".env"

# Supabase Storage 버킷. 만들고 허용하는 방법은 supabase_photos_storage.sql
BUCKET = "photos"
MAX_BYTES = 5 * 1024 * 1024  # 한 장 크기 한도 (5MB). 버킷에는 한도가 없어 화면에서 막는다
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
KST = timezone(timedelta(hours=9))


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


env = read_env(ENV_PATH)
SUPABASE_URL = env.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = env.get("SUPABASE_KEY", "")


def storage(method, path, data=None, content_type="application/json"):
    # Supabase Storage API 호출: 키를 apikey 와 Authorization 헤더에 함께 싣는다
    request = urllib.request.Request(
        f"{SUPABASE_URL}/storage/v1/{path}",
        data=data,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": content_type,
        },
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8")
        return json.loads(text) if text else None


def list_photos():
    # 버킷 맨 위의 파일을 새로 올린 것부터 모두 가져온다 (한 번에 100개씩)
    photos, offset = [], 0
    while True:
        body = {"prefix": "", "limit": 100, "offset": offset, "sortBy": {"column": "created_at", "order": "desc"}}
        page = storage("POST", f"object/list/{BUCKET}", json.dumps(body).encode("utf-8"))
        # 폴더(id 가 없는 줄)와 그림이 아닌 파일은 뺀다 (버킷이 그림 아닌 파일도 받기 때문)
        photos += [
            item
            for item in page
            if item.get("id") and (item.get("metadata") or {}).get("mimetype", "").startswith("image/")
        ]
        if len(page) < 100:
            return photos
        offset += 100


def upload(file):
    # 파일 이름은 "올린 시각-짧은 번호.확장자" 로 새로 붙인다 (한글·띄어쓰기 이름과 같은 이름 겹침을 피함)
    extension = file.name.rsplit(".", 1)[-1].lower()
    name = f"{datetime.now(KST):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.{extension}"
    storage("POST", f"object/{BUCKET}/{name}", file.getvalue(), IMAGE_TYPES[extension])
    return name


def public_url(name):
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{urllib.parse.quote(name)}"


def error_text(error):
    if isinstance(error, urllib.error.HTTPError):
        detail = error.read().decode("utf-8")
        if "Bucket not found" in detail:
            return "Supabase 에 photos 버킷이 없어요. supabase_photos_storage.sql 을 실행해 주세요."
        if "row-level security" in detail:
            return "photos 버킷 허용이 없어요. supabase_photos_storage.sql 을 실행해 주세요."
        return f"({error.code}) {detail}"
    return f"Supabase 에 연결하지 못했어요: {getattr(error, 'reason', error)}"


st.title("사진 보관함")
st.caption("Supabase Storage 의 photos 버킷에 그림을 올리고, 올라와 있는 그림을 모두 봅니다.")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 채워 주세요.")
    st.stop()

# 올리기: 여러 장을 고른 뒤 올리기 버튼을 누른다. 다 올리면 고른 칸을 비운다
with st.form("upload", clear_on_submit=True):
    files = st.file_uploader(
        "올릴 그림 (png · jpg · gif · webp, 한 장에 5MB 까지)",
        type=list(IMAGE_TYPES),
        accept_multiple_files=True,
    )
    submitted = st.form_submit_button("올리기", type="primary")

if submitted:
    if not files:
        st.warning("올릴 그림을 먼저 골라 주세요.")
    done, failed = [], []
    for file in files or []:
        if file.size > MAX_BYTES:
            failed.append(f"{file.name}: 5MB 가 넘어요 ({file.size / 1024 / 1024:.1f}MB)")
            continue
        try:
            upload(file)
            done.append(file.name)
        except (urllib.error.URLError, TimeoutError) as error:
            failed.append(f"{file.name}: {error_text(error)}")
    if done:
        st.success(f"{len(done)}장 올렸어요: {', '.join(done)}")
    for message in failed:
        st.error(f"올리지 못했어요 — {message}")

# 보관함: 올라와 있는 그림을 새것부터 작게, 세 칸씩 나란히 보여 준다
try:
    photos = list_photos()
except (urllib.error.URLError, TimeoutError) as error:
    st.error(error_text(error))
    st.stop()

st.subheader(f"올라와 있는 그림 {len(photos)}장")
if not photos:
    st.info("아직 올라온 그림이 없어요. 위에서 그림을 골라 올려 보세요.")
    st.stop()

# 세 칸 전체 너비를 좁게 묶어 그림 한 장이 작게(약 200px) 보이게 한다
GALLERY_WIDTH = 680
with st.container(width=GALLERY_WIDTH):
    columns = st.columns(3)
    for index, photo in enumerate(photos):
        created = datetime.fromisoformat(photo["created_at"].replace("Z", "+00:00")).astimezone(KST)
        size = (photo.get("metadata") or {}).get("size", 0)
        with columns[index % 3]:
            with st.container(border=True):
                st.image(public_url(photo["name"]), width="stretch")
                st.caption(f"{created:%m-%d %H:%M} · {size / 1024:,.0f}KB")
                st.markdown(f"[원본 열기]({public_url(photo['name'])})")
