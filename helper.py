from pathlib import Path

import anthropic
import streamlit as st

st.set_page_config(page_title="챗봇")

# 이 파일 옆 .env 에서 ANTHROPIC_API_KEY 를 읽는다 (KEY=VALUE 줄만, # 줄은 건너뜀)
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


# Claude 모델 (공식 anthropic 패키지로 부른다). 한 마디 주고받기라 effort 는 채팅에 권하는 low
MODEL = "claude-sonnet-5-5"
EFFORT = "low"
# 거절(refusal) 대비: 서버가 거절 종류에 맞는 다른 모델로 이어 답하게 한다 (Claude API 전용 베타)
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def ask_claude(message, api_key):
    client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": message}],
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    # 거절이면 답 글자를 읽지 않는다
    if response.stop_reason == "refusal":
        return None
    # 답에는 thinking 블록이 섞일 수 있어서 text 블록만 이어 붙인다
    return "".join(block.text for block in response.content if block.type == "text")


st.title("챗봇")

# 키 값은 화면에 보여 주지 않고, 채워져 있는지만 알려 준다
api_key = read_env(ENV_PATH).get("ANTHROPIC_API_KEY", "")
if api_key:
    st.success("ANTHROPIC_API_KEY 가 채워져 있습니다.")
else:
    st.error("ANTHROPIC_API_KEY 가 비어 있습니다. .env 에 채워 주세요.")

# 넣는 자리 + 버튼: 누르면 빈칸의 말을 Claude 에 보내고 받은 답을 아래에 보여 준다
message = st.text_input("하고 싶은 말", placeholder="예: 안녕하세요")
if st.button("보내기", disabled=not api_key):
    if not message.strip():
        st.warning("빈칸에 말을 넣어 주세요.")
    else:
        try:
            with st.spinner("Claude 가 답을 쓰는 중..."):
                answer = ask_claude(message.strip(), api_key)
            if answer is None:
                st.warning("이 말에는 답할 수 없다고 합니다. 다르게 물어봐 주세요.")
            else:
                st.markdown(answer or "(받은 답이 비어 있습니다)")
        except anthropic.AuthenticationError:
            st.error(".env 의 ANTHROPIC_API_KEY 가 맞지 않습니다. 키를 확인해 주세요.")
        except anthropic.RateLimitError:
            st.error("지금 요청이 몰려서 답하지 못했습니다. 잠시 뒤 다시 눌러 주세요.")
        except anthropic.APIStatusError as error:
            st.error(f"Claude 호출 실패 ({error.status_code}): {error.message}")
        except anthropic.APIConnectionError:
            st.error("Claude 에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.")
