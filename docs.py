import base64
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="문서 보관함", layout="wide")

# 이 파일 옆 .env 에서 Supabase 주소와 키를 읽는다 (KEY=VALUE 줄만, # 줄은 건너뜀)
ENV_PATH = Path(__file__).parent / ".env"

# Supabase Storage 버킷 (비공개). 만들고 허용하는 방법은 supabase_docs_storage.sql
BUCKET = "docs"
MAX_BYTES = 20 * 1024 * 1024  # 한 개 크기 한도 (20MB, 버킷 설정과 같게)
LINK_MINUTES = 1  # 내려받기 링크가 열려 있는 시간 (분)
# 확장자 → 문서 종류. 버킷이 받는 종류(supabase_docs_storage.sql)와 맞춘다
DOC_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "hwp": "application/x-hwp",
    "hwpx": "application/vnd.hancom.hwpx",
    "txt": "text/plain",
    "csv": "text/csv",
    "md": "text/markdown",
}
KST = timezone(timedelta(hours=9))


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


# 저장 이름: "올린 시각-짧은 번호--원래이름(영문·숫자로 바꾼 것).확장자"
# Storage 는 한글·띄어쓰기 이름을 받지 않아서, 원래 이름은 영문·숫자로 바꿔 넣고 보여 줄 때 되돌린다
def storage_name(original):
    extension = original.rsplit(".", 1)[-1].lower()
    encoded = base64.urlsafe_b64encode(original.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{datetime.now(KST):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}--{encoded}.{extension}"


def original_name(name):
    # 저장 이름에서 원래 이름을 되살린다. 이 화면이 아닌 곳에서 올린 파일은 저장 이름 그대로 보여 준다
    try:
        encoded = name.split("--", 1)[1].rsplit(".", 1)[0]
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except (IndexError, ValueError):
        return name


def list_docs():
    # 버킷 맨 위의 파일을 새로 올린 것부터 모두 가져온다 (한 번에 100개씩, 폴더는 뺀다)
    docs, offset = [], 0
    while True:
        body = {"prefix": "", "limit": 100, "offset": offset, "sortBy": {"column": "created_at", "order": "desc"}}
        page = storage("POST", f"object/list/{BUCKET}", json.dumps(body).encode("utf-8"))
        docs += [item for item in page if item.get("id")]
        if len(page) < 100:
            return docs
        offset += 100


def signed_links(docs):
    # 문서마다 LINK_MINUTES 분 동안만 열리는 내려받기 링크를 한 번에 만든다
    # download= 를 붙여 누르면 원래 이름으로 내려받게 한다
    if not docs:
        return {}
    body = {"expiresIn": LINK_MINUTES * 60, "paths": [d["name"] for d in docs]}
    result = storage("POST", f"object/sign/{BUCKET}", json.dumps(body).encode("utf-8"))
    links = {}
    for item in result:
        if item.get("signedURL"):
            download = urllib.parse.quote(original_name(item["path"]))
            links[item["path"]] = f"{SUPABASE_URL}/storage/v1{item['signedURL']}&download={download}"
    return links


def upload(file):
    name = storage_name(file.name)
    storage("POST", f"object/{BUCKET}/{name}", file.getvalue(), DOC_TYPES[file.name.rsplit('.', 1)[-1].lower()])
    return name


def error_text(error):
    if isinstance(error, urllib.error.HTTPError):
        detail = error.read().decode("utf-8")
        if "Bucket not found" in detail:
            return "Supabase 에 docs 버킷이 없어요. supabase_docs_storage.sql 을 실행해 주세요."
        if "row-level security" in detail:
            return "docs 버킷 허용이 없어요. supabase_docs_storage.sql 을 실행해 주세요."
        if "mime type" in detail.lower():
            return "버킷이 받지 않는 문서 종류예요."
        return f"({error.code}) {detail}"
    return f"Supabase 에 연결하지 못했어요: {getattr(error, 'reason', error)}"


st.title("문서 보관함")
st.caption(f"Supabase Storage 의 docs 버킷(비공개)에 문서를 올리고 봅니다. 내려받기 링크는 {LINK_MINUTES}분 동안만 열려요.")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 채워 주세요.")
    st.stop()

# 올리기: 여러 개를 고른 뒤 올리기 버튼을 누른다. 다 올리면 고른 칸을 비운다
with st.form("upload", clear_on_submit=True):
    files = st.file_uploader(
        "올릴 문서 (PDF · Word · Excel · PowerPoint · 한글 · txt · csv · md, 한 개에 20MB 까지)",
        type=list(DOC_TYPES),
        accept_multiple_files=True,
    )
    submitted = st.form_submit_button("올리기", type="primary")

if submitted:
    if not files:
        st.warning("올릴 문서를 먼저 골라 주세요.")
    done, failed = [], []
    for file in files or []:
        if file.size > MAX_BYTES:
            failed.append(f"{file.name}: 20MB 가 넘어요 ({file.size / 1024 / 1024:.1f}MB)")
            continue
        try:
            upload(file)
            done.append(file.name)
        except (urllib.error.URLError, TimeoutError) as error:
            failed.append(f"{file.name}: {error_text(error)}")
    if done:
        st.success(f"{len(done)}개 올렸어요: {', '.join(done)}")
    for message in failed:
        st.error(f"올리지 못했어요 — {message}")

# 보관함: 올라와 있는 문서를 새것부터 보여 주고, 문서마다 잠깐만 열리는 내려받기 링크를 붙인다
try:
    docs = list_docs()
    links = signed_links(docs)
except (urllib.error.URLError, TimeoutError) as error:
    st.error(error_text(error))
    st.stop()

expires = datetime.now(KST) + timedelta(minutes=LINK_MINUTES)
st.subheader(f"올라와 있는 문서 {len(docs)}개")
if not docs:
    st.info("아직 올라온 문서가 없어요. 위에서 문서를 골라 올려 보세요.")
    st.stop()
st.caption(f"아래 링크는 {expires:%H:%M:%S}까지 열려요. 시간이 지나면 「새로고침」을 눌러 새 링크를 받으세요.")
# 새로고침: 목록을 다시 불러오고 내려받기 링크를 새로 만든다
# 눌렀다는 표시는 다시 그린 뒤에 띄운다 (rerun 하면 그 전에 띄운 알림이 사라지므로)
if st.button("🔄 새로고침"):
    st.session_state.refreshed = True
    st.rerun()
if st.session_state.pop("refreshed", False):
    st.toast(f"새 링크를 받았어요. {expires:%H:%M:%S}까지 열려요.", icon="🔄")

for doc in docs:
    created = datetime.fromisoformat(doc["created_at"].replace("Z", "+00:00")).astimezone(KST)
    size = (doc.get("metadata") or {}).get("size", 0)
    with st.container(border=True):
        name_col, info_col, link_col = st.columns([5, 3, 2], vertical_alignment="center")
        name_col.markdown(f"📄 **{original_name(doc['name'])}**")
        info_col.caption(f"{created:%Y-%m-%d %H:%M} · {size / 1024:,.0f}KB")
        if doc["name"] in links:
            # key 에 링크를 만든 시각을 넣어, 새로고침할 때마다 버튼을 새로 그려 새 링크가 들어가게 한다
            link_col.link_button(
                "내려받기",
                links[doc["name"]],
                key=f"download_{doc['name']}_{expires.timestamp():.0f}",
                width="stretch",
            )
        else:
            link_col.caption("링크를 만들지 못했어요")
