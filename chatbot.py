import base64
import html
import io
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import streamlit as st
from PIL import Image, ImageDraw

# 상담 챗봇: 화면 오른쪽 아래 아이콘을 누르면 대화창이 열리고, PRD.md 를 근거로 서비스에 대해 답한다
PRD_PATH = Path(__file__).parent / "PRD.md"

# AI 에게 주는 고정 지시문 (역할·답 형식·안내 문구). 이 파일만 고치면 챗봇 말투와 규칙이 바뀐다
INSTRUCTION_PATH = Path(__file__).parent / "chatbot_instruction.md"

# 챗봇 아이콘 그림: assets/icons/bot.png 에서 사슴 얼굴 쪽을 정사각형으로 잘라 쓴다 (왼쪽, 위, 오른쪽, 아래)
ICON_PATH = Path(__file__).parent / "assets" / "icons" / "bot.png"
ICON_CROP = (190, 50, 950, 810)

# Claude 모델 (공식 anthropic 패키지로 부른다). 짧은 상담 답이라 effort 는 채팅에 권하는 low
MODEL = "claude-sonnet-5-5"
EFFORT = "low"
# 거절(refusal) 대비: 서버가 거절 종류에 맞는 다른 모델로 이어 답하게 한다 (Claude API 전용 베타)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# 대화가 길어져도 최근 몇 개만 보낸다
MAX_TURNS = 20

GREETING = "안녕하세요! 꽃사슴 안내 챗봇이에요 🦌 서비스에 대해 궁금한 걸 물어보세요."

# 빈칸(공백만)으로 보냈을 때: Claude 를 부르지 않고 이 말로 바로 답한다
BLANK_REPLY = "안녕하세요! '꽃사슴' 서비스에 대해 궁금한 점을 편하게 물어봐 주세요."

# 답 점검: 정확히 세 줄이고 300자 이하여야 화면에 보인다. 벗어나면 한 번 더 묻고, 또 벗어나면 이 말을 띄운다
MAX_CHARS = 300
UNSURE_PREFIX = "[확실하지 않은 내용이에요]"
RETRY_REPLY = "다시 시도해 주세요"

# AI 가 쓴 답 맨 위에 붙이는 안내 한 줄 (화면에만 보이고 Claude 에 보내거나 기록에 남기지 않는다)
DRAFT_NOTE = "AI가 쓴 초안입니다 · 확인하고 쓰세요"

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


def to_messages(history):
    # history: [{"role": "user" | "model", "text": ...}] — 마지막이 방금 보낸 질문
    # 빈칸 안내처럼 앱이 직접 한 답(local)은 보내지 않는다
    messages = [
        {"role": "user" if turn["role"] == "user" else "assistant", "content": turn["text"]}
        for turn in history
        if not turn.get("local")
    ][-MAX_TURNS:]
    # Claude 는 첫 말이 user 여야 한다. 잘라 낸 앞머리가 답이면 버린다
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def ask_claude(history, api_key, tone):
    # 대화 기록은 글자만 다시 보낸다. 말투를 바꾸면 system 이 달라져서,
    # 예전 thinking 블록을 다시 보내면 Claude 가 '앞 대화가 바뀌었다'며 거부할 수 있기 때문이다
    client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": EFFORT},
        system=system_instruction(tone),
        messages=to_messages(history),
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    # 거절이면 답 글자를 읽지 않는다
    if response.stop_reason == "refusal":
        return None, response.model
    # 답에는 thinking 블록이 섞일 수 있어서 text 블록만 이어 붙인다
    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response.model


def passes_check(answer):
    # "[확실하지 않은 내용이에요]"로 시작하면 그대로 통과. 아니면 빈 줄 없는 정확히 세 줄 + 300자 이하
    text = answer.strip()
    if text.startswith(UNSURE_PREFIX):
        return True
    lines = text.split("\n")
    return len(lines) == 3 and all(line.strip() for line in lines) and len(text) <= MAX_CHARS


def reply(history, api_key, tone):
    # 점검에 걸리면 한 번 더 묻는다. 두 번 다 걸리면 답 대신 RETRY_REPLY (답한 모델은 None)
    # 돌려주는 값: (답, 답한 모델, 오류 문구)
    for _ in range(2):
        answer, model, error = reply_once(history, api_key, tone)
        if error or passes_check(answer):
            return answer, model, error
    return RETRY_REPLY, None, None


def reply_once(history, api_key, tone):
    # 붐빔(429·529·5xx)·연결 오류는 패키지가 알아서 두 번 더 보낸다. 그래도 안 되면 안내 문구를 돌려준다
    # 돌려주는 값: (답, 답한 모델, 오류 문구)
    try:
        answer, model = ask_claude(history, api_key, tone)
    except anthropic.AuthenticationError:
        return None, None, ".env 의 ANTHROPIC_API_KEY 가 맞지 않아요. 키를 확인해 주세요."
    except anthropic.RateLimitError:
        return None, None, "지금 질문이 몰려서 답하지 못했어요. 잠시 뒤 다시 물어봐 주세요."
    except anthropic.APIStatusError as error:
        if error.status_code >= 500:
            return None, None, "지금 Claude 가 붐벼서 답하지 못했어요. 잠시 뒤 다시 물어봐 주세요."
        return None, None, f"챗봇 호출 실패 ({error.status_code}). 잠시 뒤 다시 물어봐 주세요."
    except anthropic.APIConnectionError:
        return None, None, "챗봇에 연결하지 못했어요. 인터넷 연결을 확인해 주세요."
    if answer is None:
        return None, None, "이 질문에는 답할 수 없어요. 서비스에 대해 다르게 물어봐 주세요."
    return answer or "(받은 답이 비어 있어요)", model, None


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
        with st.popover("챗봇", help="꽃사슴 상담 챗봇"):
            with st.container(key="chatbot_panel"):
                st.markdown("**꽃사슴 상담 챗봇**")
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
        st.error(".env 에 ANTHROPIC_API_KEY 를 채우면 챗봇을 쓸 수 있어요.")
        return

    # 자리 순서: 위에 대화 기록, 아래에 입력칸 (기록은 질문을 처리한 뒤에 채운다)
    messages = st.container(height=360)
    question = st.chat_input("서비스에 대해 물어보세요", key="chatbot_input")

    # 질문을 받으면 기록에 넣고 Claude 의 답을 받아 이어 붙인다
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
        if answer == RETRY_REPLY and model is None:
            # 점검에 두 번 걸린 경우: 질문과 안내를 앱이 한 말(local)로 남겨 다음 질문 때 Claude 에 보내지 않는다
            history[-1]["local"] = True
            history.append({"role": "model", "text": RETRY_REPLY, "local": True})
        elif answer:
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
                    # AI 가 쓴 답이면 안내 한 줄을 답보다 먼저 보여 준다
                    if not turn.get("local"):
                        st.caption(DRAFT_NOTE)
                    # 마크다운은 줄바꿈 하나를 띄어쓰기로 보므로, 줄 끝에 공백 두 칸을 붙여 문장마다 줄을 바꾼다
                    st.markdown(turn["text"].strip().replace("\n", "  \n"))
                    if not turn.get("local"):
                        copy_button(turn["text"])
    if error:
        st.error(error)
    if log_error:
        st.caption(log_error)
