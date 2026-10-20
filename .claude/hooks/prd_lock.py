# -*- coding: utf-8 -*-
"""PRD 자물쇠: AI가 PRD.md 를 Write/Edit/MultiEdit 하거나 Bash/PowerShell 명령으로 고치려 하면 막는다 (PreToolUse 훅)."""
import json
import os
import re
import subprocess
import sys

TITLE = "PRD 자물쇠"
MESSAGE = "[기획서는 직접 고쳐 주세요]"
REASON = "PRD.md 는 잠겨 있으니 고치지 말고 바꿀 내용을 제안만 하라"


def show_popup():
    # Windows 기본 메시지 상자: 경고 아이콘 + 항상 맨 앞 + 포커스 가져오기
    import ctypes
    import winsound
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)  # 알림 소리 한 번
    MB_OK = 0x0
    MB_ICONWARNING = 0x30
    MB_SYSTEMMODAL = 0x1000
    MB_SETFOREGROUND = 0x10000
    MB_TOPMOST = 0x40000
    ctypes.windll.user32.MessageBoxW(
        None, MESSAGE, TITLE,
        MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST,
    )


def launch_popup_detached():
    # 경고창은 별도 프로세스로 띄워 훅이 창이 닫힐 때까지 기다리지 않게 한다
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        [exe, os.path.abspath(__file__), "--popup"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
    )


def project_dir():
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return env
    # .claude/hooks/prd_lock.py 기준으로 두 단계 위가 프로젝트 폴더
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def norm(path):
    return os.path.normcase(os.path.realpath(path))


# 명령 속 PRD.md 언급 (PRD.md.bak, MyPRD.md 같은 다른 파일은 제외)
PRD_REF = r"(?<![\w.-])PRD\.md(?![\w.-])"

# 명령 한 토막 안에 PRD.md 와 함께 있으면 '고치는 명령'으로 보는 패턴
WRITE_PATTERNS = [
    r">{1,2}\s*[\"']?[^\s\"';&|]*" + PRD_REF,              # > PRD.md, >> PRD.md
    r"\btee\b",
    r"\bsed\b[^;&|]*\s-[a-zA-Z]*i",                        # sed -i
    r"\bperl\b[^;&|]*\s-[a-zA-Z]*i",                       # perl -i
    r"\b(rm|mv|truncate|dd|del|erase|ren|move)\b",
    r"\b(Set-Content|Add-Content|Out-File|Clear-Content|Remove-Item|Move-Item|Rename-Item|New-Item)\b",
    r"\b(WriteAllText|WriteAllLines|AppendAllText|AppendAllLines|writeFileSync|appendFileSync|write_text|write_bytes)\b",
    r"\bopen\s*\([^)]*[\"'][wax+]",                          # open('PRD.md', 'w')
    r"\b(cp|copy|Copy-Item)\b.*" + PRD_REF + r"[\"']?\s*$",  # 복사 대상이 PRD.md
]


def command_writes_prd(command):
    # ; && || | 줄바꿈으로 나눈 토막마다 검사한다. PRD.md 를 읽기만 하면 통과
    for seg in re.split(r"[;&|\n]+", command):
        if not re.search(PRD_REF, seg, re.IGNORECASE):
            continue
        if any(re.search(p, seg, re.IGNORECASE) for p in WRITE_PATTERNS):
            return True
    return False


def file_is_prd(tool_input, cwd):
    file_path = tool_input.get("file_path")
    if not file_path:
        return False
    if not os.path.isabs(file_path):
        file_path = os.path.join(cwd or project_dir(), file_path)
    return norm(file_path) == norm(os.path.join(project_dir(), "PRD.md"))


def main():
    if "--popup" in sys.argv:
        show_popup()
        return 0

    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return 0  # 입력을 못 읽으면 막지 않는다

    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") in ("Bash", "PowerShell"):
        blocked = command_writes_prd(tool_input.get("command") or "")
    else:
        blocked = file_is_prd(tool_input, data.get("cwd"))
    if not blocked:
        return 0  # PRD.md 를 고치는 게 아니면 통과

    try:
        launch_popup_detached()
    except Exception:
        pass  # 경고창이 실패해도 차단은 유지

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
