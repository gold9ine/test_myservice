import base64
import html
import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw

# 상담 챗봇: 화면 오른쪽 아래 아이콘을 누르면 대화창이 열리고, PRD.md 를 근거로 서비스에 대해 답한다
PRD_PATH = Path(__file__).parent / "PRD.md"

# AI 에게 주는 고정 지시문 (역할·답 형식·안내 문구). 이 파일만 고치면 챗봇 말투와 규칙이 바뀐다
INSTRUCTION_PATH = Path(__file__).parent / "chatbot_instruction.md"

# 챗봇 아이콘 그림: assets/icons/bot.png 에서 사슴 얼굴 쪽을 정사각형으로 잘라 쓴다 (왼쪽, 위, 오른쪽, 아래)
ICON_PATH = Path(__file__).parent / "assets" / "icons" / "bot.png"
ICON_CROP = (190, 50, 950, 810)

# Gemini 모델과 주소 (공식 문서 ai.google.dev/gemini-api/docs/models, /api/generate-content 기준)
# 문서가 새 프로젝트에 권하는 두 모델. 앞 모델이 붐비면(503·429·시간 초과) 다음 모델로, 그래도 안 되면 처음 모델로 한 번 더
MODELS = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
ATTEMPTS = MODELS + MODELS[:1]
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
BUSY_CODES = (429, 503)

# 대화가 길어져도 최근 몇 개만 보낸다
MAX_TURNS = 20

GREETING = "안녕하세요! 근처 미용실 안내 챗봇이에요 🦌 서비스에 대해 궁금한 걸 물어보세요."

# 빈칸(공백만)으로 보냈을 때: Gemini 를 부르지 않고 이 말로 바로 답한다
BLANK_REPLY = "안녕하세요! '근처 미용실' 서비스에 대해 궁금한 점을 편하게 물어봐 주세요."

# 말투 고르는 칸: 보이는 이름 → AI 에게 알려 줄 말투 설명. 첫 번째가 기본값
TONES = {
    "친절한 존댓말": "부드럽고 친절한 해요체 존댓말 (예: ~해요, ~할 수 있어요)",
    "깔끔한 격식체": "정중하고 간결한 합니다체 (예: ~합니다, ~하실 수 있습니다)",
    "친근한 반말": "친구에게 말하듯 다정한 반말 (예: ~해, ~할 수 있어)",
    "귀여운 말투": "밝고 귀여운 해요체, 문장 끝에 이모지를 하나씩 붙임 (예: ~해요 😊)",
}


def system_instruction(tone):
    # 챗봇 고정 지시문(chatbot_instruction.md) + 고른 말투 + PRD.md 전문. 질문할 때마다 두 파일을 새로 읽는다
    instruction = INSTRUCTION_PATH.read_text(encoding="utf-8").strip()
    prd = PRD_PATH.read_text(encoding="utf-8")
    tone_rule = (
        f"## 말투\n- 이번 답은 '{tone}'로 쓴다: {TONES[tone]}.\n"
        "- 앞선 답의 말투와 달라도 지금 고른 말투를 따른다. 세 문장·줄바꿈 형식은 말투와 상관없이 그대로 지킨다.\n"
        "- '서비스 준비중'이라는 말은 그대로 쓰되, 끝맺음은 고른 말투에 맞춘다."
    )
    return instruction + "\n\n" + tone_rule + "\n\n=== PRD.md ===\n" + prd


def ask_gemini(model, history, api_key, tone):
    # history: [{"role": "user" | "model", "text": ...}] — 마지막이 방금 보낸 질문
    body = {
        "systemInstruction": {"parts": [{"text": system_instruction(tone)}]},
        "contents": [
            # 빈칸 안내처럼 앱이 직접 한 답(local)은 보내지 않는다
            {"role": turn["role"], "parts": [{"text": turn["text"]}]}
            for turn in history
            if not turn.get("local")
        ][-MAX_TURNS:],
    }
    # 키는 주소에 넣지 않고 x-goog-api-key 헤더로 보낸다
    request = urllib.request.Request(
        API_URL.format(model),
        data=json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        result = json.load(response)
    # 답 글자는 candidates[0].content.parts 안에 있다. 여러 조각이면 이어 붙인다
    parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def reply(history, api_key, tone):
    # 붐빔(503·429)이나 시간 초과면 다음 모델로 다시 보낸다. 그 밖의 오류는 바로 알린다
    # 돌려주는 값: (답, 답한 모델, 오류 문구)
    for model in ATTEMPTS:
        try:
            return ask_gemini(model, history, api_key, tone) or "(받은 답이 비어 있어요)", model, None
        except urllib.error.HTTPError as error:
            if error.code not in BUSY_CODES:
                return None, None, f"챗봇 호출 실패 ({error.code}). 잠시 뒤 다시 물어봐 주세요."
        except urllib.error.URLError as error:
            return None, None, f"챗봇에 연결하지 못했어요: {error.reason}"
        except TimeoutError:
            pass
    return None, None, "지금 Gemini 가 붐벼서 답하지 못했어요. 잠시 뒤 다시 물어봐 주세요."


# 챗봇 기록 표 (Supabase). 만드는 방법은 supabase_chatbot_logs.sql
LOG_TABLE = "chatbot_logs"
KST = timezone(timedelta(hours=9))


def save_log(db, question, answer, tone, model):
    # AI 가 답할 때마다 넣은 말과 받은 답을 한 줄 남긴다. 실패하면 오류 문구를 돌려준다 (대화는 계속된다)
    try:
        db("POST", LOG_TABLE, {"question": question, "answer": answer, "tone": tone, "model": model})
    except urllib.error.HTTPError as error:
        return f"기록을 남기지 못했어요 ({error.code}). 대화는 계속할 수 있어요."
    except (urllib.error.URLError, TimeoutError):
        return "기록을 남기지 못했어요 (연결 실패). 대화는 계속할 수 있어요."
    return None


def show_logs(db):
    # 지난 기록 목록: 최근 50개, 새 기록이 위로
    if db is None:
        st.caption(".env 에 Supabase 주소와 키를 채우면 지난 기록을 볼 수 있어요.")
        return
    try:
        rows = db("GET", f"{LOG_TABLE}?select=*&order=created_at.desc&limit=50")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            st.warning(f"Supabase 에 {LOG_TABLE} 표가 아직 없어요. supabase_chatbot_logs.sql 을 실행해 주세요.")
        else:
            st.error(f"지난 기록을 불러오지 못했어요 ({error.code}).")
        return
    except (urllib.error.URLError, TimeoutError):
        st.error("지난 기록을 불러오지 못했어요 (연결 실패).")
        return
    if not rows:
        st.caption("아직 남은 기록이 없어요.")
        return
    st.caption(f"최근 {len(rows)}개")
    for row in rows:
        when = datetime.fromisoformat(row["created_at"]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        with st.container(border=True):
            st.caption(f"{when} · {row['tone']} · {row['model']}")
            st.markdown(f"**Q.** {row['question']}")
            st.markdown(row["answer"].strip().replace("\n", "  \n"))


STYLE = """
<style>
/* 아이콘 자리: 화면 오른쪽 아래에 고정 */
.st-key-chatbot {
    position: fixed;
    right: 24px;
    bottom: 24px;
    z-index: 1000;
    width: auto !important;
}
/* 동그란 아이콘 버튼: bot.png 사슴 그림을 배경으로 깔고 글자는 숨긴다 */
.st-key-chatbot button {
    width: 68px;
    height: 68px;
    border-radius: 50%;
    border: 3px solid #ffffff;
    background: url("__ICON__") center / cover no-repeat;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
    padding: 0;
    transition: transform 0.15s;
}
.st-key-chatbot button p {
    font-size: 0;
}
.st-key-chatbot button:hover {
    transform: scale(1.08);
}
/* 답 옆 복사 버튼 */
.chatbot-copy {
    float: right;
    margin-top: 4px;
    padding: 2px 8px;
    font-size: 12px;
    color: #6b6b6b;
    background: #ffffff;
    border: 1px solid #dddddd;
    border-radius: 12px;
    cursor: pointer;
}
.chatbot-copy:hover {
    color: #333333;
    border-color: #bbbbbb;
}
/* 버튼 옆 펼침 화살표는 숨긴다 */
.st-key-chatbot button [data-testid="stIconMaterial"] {
    display: none;
}
/* 대화창 크기 */
[data-testid="stPopoverBody"]:has(.st-key-chatbot_panel) {
    width: 360px;
    max-width: calc(100vw - 32px);
}
</style>
<script>
// 복사 버튼: 누르면 data-text 에 담긴 답 전체를 클립보드에 넣는다 (페이지에 한 번만 건다)
if (!window.__chatbotCopy) {
    window.__chatbotCopy = true;
    document.addEventListener("click", (event) => {
        const button = event.target.closest(".chatbot-copy");
        if (!button) return;
        navigator.clipboard.writeText(button.dataset.text).then(() => {
            button.textContent = "✓ 복사됨";
            setTimeout(() => (button.textContent = "📋 복사"), 1500);
        });
    });
}
</script>
"""


@st.cache_data(show_spinner=False)
def icon_image(mtime):
    # bot.png 에서 얼굴 쪽을 잘라 동그랗게 만든 작은 그림 (파일이 바뀌면 mtime 이 달라져 다시 만든다)
    image = Image.open(ICON_PATH).convert("RGB").crop(ICON_CROP).resize((160, 160))
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, image.width - 1, image.height - 1), fill=255)
    icon = Image.new("RGBA", image.size)
    icon.paste(image, mask=mask)
    buffer = io.BytesIO()
    icon.save(buffer, format="PNG")
    return buffer.getvalue()


def copy_button(text):
    # 답 옆 복사 버튼. 답 글자는 속성값으로 넣어 그대로 복사되게 한다
    st.html(
        f'<button class="chatbot-copy" data-text="{html.escape(text, quote=True)}">📋 복사</button>'
    )


def render(api_key, db=None):
    # db: Supabase 를 부르는 함수 supabase(method, path, body) — 없으면 기록을 남기지 않는다
    if "chatbot_history" not in st.session_state:
        st.session_state.chatbot_history = []
    icon = icon_image(ICON_PATH.stat().st_mtime)
    icon_uri = "data:image/png;base64," + base64.b64encode(icon).decode("ascii")
    st.html(STYLE.replace("__ICON__", icon_uri), unsafe_allow_javascript=True)
    avatar = Image.open(io.BytesIO(icon))

    with st.container(key="chatbot"):
        with st.popover("챗봇", help="근처 미용실 상담 챗봇"):
            with st.container(key="chatbot_panel"):
                st.markdown("**근처 미용실 상담 챗봇**")
                chat_tab, logs_tab = st.tabs(["대화", "지난 기록"])
                # 대화를 먼저 처리해 방금 남긴 기록까지 지난 기록 목록에 보이게 한다
                with chat_tab:
                    chat(api_key, db, avatar)
                with logs_tab:
                    show_logs(db)


def chat(api_key, db, avatar):
    # 말투 고르는 칸: 고른 말투는 다음 답부터 적용된다
    tone = st.selectbox("말투", list(TONES), key="chatbot_tone")
    if not api_key:
        st.error(".env 에 GEMINI_API_KEY 를 채우면 챗봇을 쓸 수 있어요.")
        return

    # 자리 순서: 위에 대화 기록, 아래에 입력칸 (기록은 질문을 처리한 뒤에 채운다)
    messages = st.container(height=360)
    question = st.chat_input("서비스에 대해 물어보세요", key="chatbot_input")

    # 질문을 받으면 기록에 넣고 Gemini 의 답을 받아 이어 붙인다
    error = None
    log_error = None
    if question is not None and not question.strip():
        st.session_state.chatbot_history.append(
            {"role": "model", "text": BLANK_REPLY, "local": True}
        )
    elif question:
        history = st.session_state.chatbot_history
        history.append({"role": "user", "text": question})
        with st.spinner("답을 쓰는 중..."):
            answer, model, error = reply(history, api_key, tone)
        if answer:
            history.append({"role": "model", "text": answer})
            # AI 가 답했을 때만 Supabase 에 남긴다 (빈칸 안내·오류는 남기지 않음)
            if db is not None:
                log_error = save_log(db, question, answer, tone, model)
        else:
            history.pop()

    # 대화 기록: 처음엔 인사말만 보인다
    with messages:
        with st.chat_message("assistant", avatar=avatar):
            st.markdown(GREETING)
        for turn in st.session_state.chatbot_history:
            if turn["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(turn["text"])
            else:
                # AI 가 준 답에만 복사 버튼을 붙인다 (인사말·빈칸 안내는 제외)
                with st.chat_message("assistant", avatar=avatar):
                    # 마크다운은 줄바꿈 하나를 띄어쓰기로 보므로, 줄 끝에 공백 두 칸을 붙여 문장마다 줄을 바꾼다
                    st.markdown(turn["text"].strip().replace("\n", "  \n"))
                    if not turn.get("local"):
                        copy_button(turn["text"])
    if error:
        st.error(error)
    if log_error:
        st.caption(log_error)
