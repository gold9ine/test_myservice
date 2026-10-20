# -*- coding: utf-8 -*-
# 이 파일 설명: 무엇을 막는 훅인지 적은 문서 문자열
"""백업 자물쇠: AI가 99_backup/ 아래 파일을 Write/Edit/MultiEdit 하거나 Bash/PowerShell 명령으로 고치려 하면 막는다 (PreToolUse 훅)."""
# Claude Code 가 보내 주는 JSON 입력을 읽고, 결과를 JSON 으로 내보내는 도구
import json
# 파일 경로를 합치고 비교하는 도구
import os
# 명령 글자에서 패턴을 찾는 정규식 도구
import re
# 경고창을 별도 프로그램으로 띄우는 도구
import subprocess
# 입력·출력과 실행 인자를 다루는 도구
import sys

# 경고창 제목
TITLE = "백업 자물쇠"
# 경고창 안에 보일 문구
MESSAGE = "[백업 폴더는 고칠 수 없습니다]"
# 막을 때 Claude 에게 전하는 이유
REASON = "99_backup/ 은 잠겨 있으니 고치지 말라"

# 지킬 폴더 이름
BACKUP_DIR = "99_backup"


# 경고창을 실제로 화면에 띄우는 함수
def show_popup():
    # Windows 기본 메시지 상자: 경고 아이콘 + 항상 맨 앞 + 포커스 가져오기
    # Windows 화면 기능을 부르는 도구
    import ctypes
    # Windows 알림 소리를 내는 도구
    import winsound
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)  # 알림 소리 한 번
    # 확인 버튼 하나만 보이게
    MB_OK = 0x0
    # 노란 느낌표 경고 아이콘
    MB_ICONWARNING = 0x30
    # 다른 창보다 먼저 답해야 하는 창으로
    MB_SYSTEMMODAL = 0x1000
    # 창을 앞으로 가져와 포커스 주기
    MB_SETFOREGROUND = 0x10000
    # 항상 맨 위에 보이게
    MB_TOPMOST = 0x40000
    # 메시지 상자를 띄운다
    ctypes.windll.user32.MessageBoxW(
        # 부모 창 없음, 내용, 제목
        None, MESSAGE, TITLE,
        # 위에서 정한 모양을 모두 합쳐 적용
        MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST,
    # 메시지 상자 호출 끝
    )


# 경고창을 따로 떼어 낸 프로그램으로 띄우는 함수
def launch_popup_detached():
    # 경고창은 별도 프로세스로 띄워 훅이 창이 닫힐 때까지 기다리지 않게 한다
    # 지금 이 훅을 돌리는 python 실행 파일
    exe = sys.executable
    # 같은 폴더의 창 없는 python(pythonw.exe) 위치
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    # pythonw.exe 가 있으면
    if os.path.exists(pythonw):
        # 검은 명령 창이 뜨지 않도록 그것을 쓴다
        exe = pythonw
    # 부모 명령 창과 떨어진 프로세스로 만드는 옵션
    DETACHED_PROCESS = 0x00000008
    # 새 프로세스 묶음으로 만드는 옵션
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    # 이 스크립트를 --popup 인자로 한 번 더 실행한다
    subprocess.Popen(
        # 실행할 프로그램, 이 파일 경로, 경고창 모드 인자
        [exe, os.path.abspath(__file__), "--popup"],
        # 입력은 연결하지 않음
        stdin=subprocess.DEVNULL,
        # 출력은 버림 (훅의 JSON 출력과 섞이지 않게)
        stdout=subprocess.DEVNULL,
        # 오류 출력도 버림
        stderr=subprocess.DEVNULL,
        # 열린 파일 연결을 넘겨주지 않음
        close_fds=True,
        # 위의 두 옵션을 적용
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
    # 실행 호출 끝
    )


# 프로젝트 폴더 위치를 알아내는 함수
def project_dir():
    # Claude Code 가 알려 주는 프로젝트 폴더 환경 변수
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    # 환경 변수가 있으면
    if env:
        # 그 값을 쓴다
        return env
    # .claude/hooks/block-backup.py 기준으로 두 단계 위가 프로젝트 폴더
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 경로를 비교하기 좋게 다듬는 함수
def norm(path):
    # 실제 경로로 바꾸고 대소문자·구분자를 통일한다
    return os.path.normcase(os.path.realpath(path))


# 명령 속 99_backup 언급 (old_99_backup, 99_backup2 같은 다른 이름은 제외)
BACKUP_REF = r"(?<![\w.-])" + BACKUP_DIR + r"(?![\w.-])"

# 명령 한 토막 안에 99_backup 과 함께 있으면 '고치는 명령'으로 보는 패턴
WRITE_PATTERNS = [
    r">{1,2}\s*[\"']?[^\s\"';&|]*" + BACKUP_REF,                 # > 99_backup/x, >> 99_backup/x
    # tee: 내용을 파일에 써 넣는 명령
    r"\btee\b",
    r"\bsed\b[^;&|]*\s-[a-zA-Z]*i",                              # sed -i
    r"\bperl\b[^;&|]*\s-[a-zA-Z]*i",                             # perl -i
    # 지우기·옮기기·비우기·만들기 명령 (bash 와 Windows 명령)
    r"\b(rm|rmdir|mv|truncate|dd|del|erase|ren|move|touch|mkdir)\b",
    # PowerShell 의 쓰기·지우기·옮기기·만들기 명령
    r"\b(Set-Content|Add-Content|Out-File|Clear-Content|Remove-Item|Move-Item|Rename-Item|New-Item)\b",
    # .NET·Node·Python 코드로 파일에 쓰는 함수 이름
    r"\b(WriteAllText|WriteAllLines|AppendAllText|AppendAllLines|writeFileSync|appendFileSync|write_text|write_bytes)\b",
    r"\bopen\s*\([^)]*[\"'][wax+]",                                # open('99_backup/x', 'w')
    r"\b(cp|copy|Copy-Item)\b.*" + BACKUP_REF + r"[^\s;&|]*[\"']?\s*$",  # 복사 대상이 99_backup
# 패턴 목록 끝
]


# 명령이 99_backup 을 고치는지 가르는 함수
def command_writes_backup(command):
    # ; && || | 줄바꿈으로 나눈 토막마다 검사한다. 99_backup 을 읽기만 하면 통과
    for seg in re.split(r"[;&|\n]+", command):
        # 이 토막에 99_backup 이 없으면
        if not re.search(BACKUP_REF, seg, re.IGNORECASE):
            # 다음 토막으로 넘어간다
            continue
        # 고치는 명령 패턴이 하나라도 있으면
        if any(re.search(p, seg, re.IGNORECASE) for p in WRITE_PATTERNS):
            # 막아야 한다고 알린다
            return True
    # 어느 토막도 걸리지 않으면 통과
    return False


# Write/Edit 대상 파일이 99_backup 안인지 가르는 함수
def file_in_backup(tool_input, cwd):
    # 도구가 고치려는 파일 경로
    file_path = tool_input.get("file_path")
    # 경로가 없으면
    if not file_path:
        # 막을 대상이 아니다
        return False
    # 상대 경로이면
    if not os.path.isabs(file_path):
        # 작업 폴더(없으면 프로젝트 폴더) 기준의 전체 경로로 바꾼다
        file_path = os.path.join(cwd or project_dir(), file_path)
    # 지킬 폴더의 전체 경로
    backup = norm(os.path.join(project_dir(), BACKUP_DIR))
    # 고치려는 파일의 전체 경로
    target = norm(file_path)
    # 폴더 자신이거나 그 안의 파일이면 True
    return target == backup or target.startswith(backup + os.sep)


# 훅이 실행될 때 처음 도는 함수
def main():
    # --popup 인자로 실행됐으면 (경고창 전용 실행)
    if "--popup" in sys.argv:
        # 경고창만 띄우고
        show_popup()
        # 끝낸다
        return 0

    # Claude Code 가 보낸 입력을 읽어 본다
    try:
        # 표준 입력의 JSON 을 UTF-8 로 읽는다
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    # 읽다가 문제가 생기면
    except Exception:
        return 0  # 입력을 못 읽으면 막지 않는다

    # 도구에 넘어간 입력값 (없으면 빈 묶음)
    tool_input = data.get("tool_input") or {}
    # 명령 창 도구이면
    if data.get("tool_name") in ("Bash", "PowerShell"):
        # 명령 글자를 보고 가른다
        blocked = command_writes_backup(tool_input.get("command") or "")
    # Write/Edit/MultiEdit 이면
    else:
        # 대상 파일 경로를 보고 가른다
        blocked = file_in_backup(tool_input, data.get("cwd"))
    # 막을 것이 아니면
    if not blocked:
        return 0  # 99_backup 을 고치는 게 아니면 통과

    # 경고창을 띄워 본다
    try:
        # 따로 떼어 낸 프로그램으로 경고창을 띄운다
        launch_popup_detached()
    # 경고창을 못 띄워도
    except Exception:
        pass  # 경고창이 실패해도 차단은 유지

    # Claude Code 에 돌려줄 '막기' 결과
    out = {
        # 훅 종류별 결과 묶음
        "hookSpecificOutput": {
            # 도구 실행 전에 도는 훅이라고 알림
            "hookEventName": "PreToolUse",
            # 이 도구 실행을 거부
            "permissionDecision": "deny",
            # 거부 이유
            "permissionDecisionReason": REASON,
        # 결과 묶음 끝
        }
    # 돌려줄 결과 끝
    }
    # 결과를 JSON 으로 내보낸다
    sys.stdout.write(json.dumps(out))
    # 정상 종료 (막을지는 위 JSON 으로 알림)
    return 0


# 이 파일을 직접 실행했을 때만
if __name__ == "__main__":
    # main() 을 돌리고 그 값으로 끝낸다
    sys.exit(main())
