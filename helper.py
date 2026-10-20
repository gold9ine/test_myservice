import json
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="챗봇")

# 이 파일 옆 .env 에서 GEMINI_API_KEY 를 읽는다 (KEY=VALUE 줄만, # 줄은 건너뜀)
ENV_PATH = Path(__file__).parent / ".env"


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


# Gemini 모델과 주소 (공식 문서 ai.google.dev/gemini-api/docs/models, /api/generate-content 기준)
# 문서가 새 프로젝트에 권하는 두 모델 중 하나. 더 똑똑한 답이 필요하면 "gemini-3.8-flash" 로 바꾼다
MODEL = "gemini-3.5-flash-lite"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def ask_gemini(message, api_key):
    # 키는 주소에 넣지 않고 x-goog-api-key 헤더로 보낸다
    body = {"contents": [{"parts": [{"text": message}]}]}
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    # 답 글자는 candidates[0].content.parts 안에 있다. 여러 조각이면 이어 붙인다
    parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


st.title("챗봇")

# 키 값은 화면에 보여 주지 않고, 채워져 있는지만 알려 준다
api_key = read_env(ENV_PATH).get("GEMINI_API_KEY", "")
if api_key:
    st.success("GEMINI_API_KEY 가 채워져 있습니다.")
else:
    st.error("GEMINI_API_KEY 가 비어 있습니다. .env 에 채워 주세요.")

# 넣는 자리 + 버튼: 누르면 빈칸의 말을 Gemini 에 보내고 받은 답을 아래에 보여 준다
message = st.text_input("하고 싶은 말", placeholder="예: 안녕하세요")
if st.button("보내기", disabled=not api_key):
    if not message.strip():
        st.warning("빈칸에 말을 넣어 주세요.")
    else:
        try:
            with st.spinner("Gemini 가 답을 쓰는 중..."):
                answer = ask_gemini(message.strip(), api_key)
            st.markdown(answer or "(받은 답이 비어 있습니다)")
        except urllib.error.HTTPError as error:
            st.error(f"Gemini 호출 실패 ({error.code}): {error.read().decode('utf-8')}")
        except urllib.error.URLError as error:
            st.error(f"Gemini 에 연결하지 못했습니다: {error.reason}")
        except TimeoutError:
            st.error("Gemini 가 30초 안에 답하지 않았습니다. 잠시 뒤 다시 눌러 주세요.")
