import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="구독 정리함", layout="wide")

# 이 파일 옆 .env 에서 Supabase 주소와 키를 읽는다 (KEY=VALUE 줄만, # 줄은 건너뜀)
ENV_PATH = Path(__file__).parent / ".env"
TABLE = "subscriptions"  # 만드는 방법은 supabase_subscriptions.sql
COLUMNS = ["name", "category", "monthly_fee", "last_used"]


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


def supabase(method, path, body=None):
    # Supabase REST API 호출: 키를 apikey 와 Authorization 헤더에 함께 싣는다
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}", data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        text = response.read().decode("utf-8")
        return json.loads(text) if text else None


def load():
    # 요금이 비싼 것부터 (요금이 빈 줄은 맨 아래, 요금이 같으면 먼저 넣은 순)
    rows = supabase("GET", f"{TABLE}?select=*&order=monthly_fee.desc.nullslast,id.asc")
    table = pd.DataFrame(rows, columns=["id"] + COLUMNS)
    table["monthly_fee"] = table["monthly_fee"].astype("Int64")
    table["last_used"] = pd.to_datetime(table["last_used"]).dt.date
    return table


def clean(row):
    # 표 한 줄을 Supabase 에 보낼 값으로 바꾼다. 빈칸은 null
    def value(v):
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return None
        if isinstance(v, date):
            return v.isoformat()
        if hasattr(v, "item"):
            return v.item()
        return str(v).strip() if isinstance(v, str) else v
    return {c: value(row.get(c)) for c in COLUMNS}


def save(before, after):
    # 고치기 전과 후를 견주어 지운 줄 · 고친 줄 · 새 줄을 Supabase 에 보낸다
    before_rows = {int(r["id"]): clean(r) for _, r in before.iterrows()}
    after_ids = set()
    added, changed = [], []
    for _, row in after.iterrows():
        values = clean(row)
        if row.get("id") is None or pd.isna(row.get("id")):
            if any(v not in (None, "") for v in values.values()):
                added.append(values)
            continue
        row_id = int(row["id"])
        after_ids.add(row_id)
        if values != before_rows.get(row_id):
            changed.append((row_id, values))
    removed = [i for i in before_rows if i not in after_ids]

    if any(not v["name"] for v in added) or any(not v["name"] for _, v in changed):
        raise ValueError("이름이 빈 줄이 있어요. 이름을 채워 주세요.")
    for row_id in removed:
        supabase("DELETE", f"{TABLE}?id=eq.{row_id}")
    for row_id, values in changed:
        supabase("PATCH", f"{TABLE}?id=eq.{row_id}", values)
    if added:
        supabase("POST", TABLE, added)
    return len(added), len(changed), len(removed)


st.title("구독 정리함")
st.caption("Supabase subscriptions 표를 바로 고칩니다. 표에서 고치고 아래 「저장」을 눌러야 Supabase 에 반영돼요.")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 채워 주세요.")
    st.stop()

try:
    table = load()
except urllib.error.HTTPError as error:
    detail = error.read().decode("utf-8")
    if error.code == 404:
        st.error("Supabase 에 subscriptions 표가 아직 없어요. supabase_subscriptions.sql 을 실행해 주세요.")
    else:
        st.error(f"불러오기 실패 ({error.code}): {detail}")
    st.stop()
except (urllib.error.URLError, TimeoutError) as error:
    st.error(f"Supabase 에 연결하지 못했어요: {getattr(error, 'reason', error)}")
    st.stop()

# 한눈에: 구독 수 · 한 달 합계 · 30일 넘게 안 쓴 구독
today = date.today()
unused = table[table["last_used"].apply(lambda d: d is not None and not pd.isna(d) and (today - d).days > 30)]
count_tile, total_tile, unused_tile = st.columns(3)
count_tile.metric("구독 수", f"{len(table)}개")
total_tile.metric("한 달 합계", f"{int(table['monthly_fee'].fillna(0).sum()):,}원")
unused_tile.metric(
    "30일 넘게 안 쓴 구독",
    f"{len(unused)}개",
    help=", ".join(unused["name"]) if len(unused) else None,
)

# 표: 칸을 눌러 고치고, 맨 아래 빈 줄에 새 구독을 넣고, 줄 왼쪽을 골라 지운다
st.markdown("**구독 목록** — 칸을 눌러 고치기 · 맨 아래 「+」로 더하기 · 줄을 골라 휴지통으로 지우기")
edited = st.data_editor(
    table,
    key=f"editor_{st.session_state.get('saved', 0)}",
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    column_order=["name", "category", "monthly_fee", "last_used"],
    column_config={
        "name": st.column_config.TextColumn("이름", required=True),
        "category": st.column_config.TextColumn("분류"),
        "monthly_fee": st.column_config.NumberColumn("한 달 요금", min_value=0, step=100, format="%d원"),
        "last_used": st.column_config.DateColumn("마지막으로 쓴 날", format="YYYY-MM-DD"),
    },
)

save_col, reset_col, _ = st.columns([1, 1, 4])
with save_col:
    if st.button("저장", type="primary", width="stretch"):
        try:
            added, changed, removed = save(table, edited)
            st.session_state.saved = st.session_state.get("saved", 0) + 1
            st.session_state.notice = f"저장했어요 — 더한 줄 {added} · 고친 줄 {changed} · 지운 줄 {removed}"
            st.rerun()
        except ValueError as error:
            st.error(str(error))
        except urllib.error.HTTPError as error:
            st.error(f"저장 실패 ({error.code}): {error.read().decode('utf-8')}")
        except (urllib.error.URLError, TimeoutError) as error:
            st.error(f"Supabase 에 연결하지 못했어요: {getattr(error, 'reason', error)}")
with reset_col:
    # 저장하기 전 고친 내용을 버리고 Supabase 에 있는 그대로 다시 보여 준다
    if st.button("고친 것 취소", width="stretch"):
        st.session_state.saved = st.session_state.get("saved", 0) + 1
        st.rerun()

if "notice" in st.session_state:
    st.success(st.session_state.pop("notice"))
