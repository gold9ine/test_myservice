from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Claude 키 확인")

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


st.title("Claude 키 확인")

# 키 값은 화면에 보여 주지 않고, 채워져 있는지만 알려 준다
if read_env(ENV_PATH).get("ANTHROPIC_API_KEY"):
    st.success("ANTHROPIC_API_KEY 가 채워져 있습니다.")
else:
    st.error("ANTHROPIC_API_KEY 가 비어 있습니다. .env 에 채워 주세요.")
