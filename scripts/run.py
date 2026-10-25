#!/usr/bin/env python3
"""마케팅 트렌드 리포트를 한 편 생성한다.

사용법:
    python3 scripts/run.py daily                # 오늘자 데일리
    python3 scripts/run.py weekly               # 지난주 (월~일)
    python3 scripts/run.py monthly              # 지난달
    python3 scripts/run.py quarterly            # 지난 분기
    python3 scripts/run.py weekly --date 2026-10-05   # 기준일 지정 (백필/테스트)
    python3 scripts/run.py render               # 에이전트 실행 없이 HTML만 다시 만들기
    python3 scripts/run.py publish              # GitHub Pages에 지금 상태를 올리기
"""
import argparse
import datetime as dt
import fcntl
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import render  # noqa: E402

CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TYPES = ("daily", "weekly", "monthly", "quarterly")
WEEKDAYS = "월화수목금토일"
ALLOWED_TOOLS = ["WebSearch", "WebFetch", "Read", "Glob", "Grep", "Write"]
# office.html의 팀원과 같은 이름
TEAM = {"daily": "하루 사원", "weekly": "주디 대리", "monthly": "달래 과장", "quarterly": "쿼터 차장"}


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def find_claude():
    """launchd는 PATH가 짧아서 확장 프로그램 안의 CLI까지 직접 찾는다."""
    if CONFIG.get("claude_bin"):
        return CONFIG["claude_bin"]
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = []
    for pattern in (
        ".antigravity-ide/extensions/anthropic.claude-code-*/resources/native-binary/claude",
        ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude",
        ".cursor/extensions/anthropic.claude-code-*/resources/native-binary/claude",
        ".claude/local/claude",
        ".local/bin/claude",
    ):
        candidates += glob.glob(str(home / pattern))
    for p in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if os.path.exists(p):
            candidates.append(p)
    if not candidates:
        sys.exit("claude CLI를 찾지 못했습니다. config.json의 claude_bin에 경로를 적어주세요.")
    return max(candidates, key=os.path.getmtime)


def period(kind, today):
    """(period_id, period_label, start, end) — start/end는 date."""
    if kind == "daily":
        return (today.isoformat(),
                f"{today.year}년 {today.month}월 {today.day}일 ({WEEKDAYS[today.weekday()]})",
                today - dt.timedelta(days=2), today)
    if kind == "weekly":
        end = today - dt.timedelta(days=today.weekday() + 1)  # 지난 일요일
        start = end - dt.timedelta(days=6)
        y, w, _ = start.isocalendar()
        return (f"{y}-W{w:02d}",
                f"{y}년 {w}주차 ({start.month}/{start.day} ~ {end.month}/{end.day})",
                start, end)
    if kind == "monthly":
        end = today.replace(day=1) - dt.timedelta(days=1)
        start = end.replace(day=1)
        return (f"{start:%Y-%m}", f"{start.year}년 {start.month}월", start, end)
    if kind == "quarterly":
        q_start_month = 3 * ((today.month - 1) // 3) + 1
        end = today.replace(month=q_start_month, day=1) - dt.timedelta(days=1)
        q = (end.month - 1) // 3 + 1
        start = end.replace(month=3 * (q - 1) + 1, day=1)
        return (f"{end.year}-Q{q}", f"{end.year}년 {q}분기 ({start.month}~{end.month}월)", start, end)
    raise ValueError(kind)


def data_files(kind):
    return sorted((ROOT / "data" / kind).glob("*.json"))


def file_start(kind, path):
    """저장된 리포트 파일명에서 기간 시작일을 구한다."""
    stem = path.stem
    if kind == "daily":
        return dt.date.fromisoformat(stem)
    if kind == "weekly":
        y, w = stem.split("-W")
        return dt.date.fromisocalendar(int(y), int(w), 1)
    if kind == "monthly":
        return dt.date.fromisoformat(stem + "-01")
    return None


def inputs_for(kind, start, end):
    """상위 리포트가 읽을 하위 리포트 목록."""
    sources = {"weekly": ["daily"], "monthly": ["weekly", "daily"], "quarterly": ["monthly"]}.get(kind, [])
    for sub in sources:
        files = [p for p in data_files(sub) if start <= file_start(sub, p) <= end]
        if files:
            return "\n".join(f"- {p.relative_to(ROOT)}" for p in files)
    return "- (저장된 하위 리포트가 없음 — 웹 검색만으로 작성)"


def recent_titles(today):
    titles = []
    for p in data_files("daily")[-7:]:
        if dt.date.fromisoformat(p.stem) >= today:
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for s in doc.get("sections", []):
            titles += [f"- ({p.stem}) {it.get('title', '')}" for it in s.get("items", [])]
    if not titles:
        return ""
    return "## 최근 다룬 항목 (새 전개가 없으면 반복하지 말 것)\n" + "\n".join(titles)


def is_weekend(kind, today):
    return kind == "daily" and today.weekday() >= 5


INSTA_DAYS = (1, 4)  # 화·금 데일리에 인스타그램 섹션을 붙인다
INSTA_SECTION = "인스타"  # 섹션 제목에 들어가야 하는 말


def is_insta_day(kind, today):
    return kind == "daily" and today.weekday() in INSTA_DAYS


def validate_insta(path):
    """인스타 섹션이 있는 날의 추가 검증. 문제 목록을 돌려준다."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []  # render.validate가 이미 잡는다
    secs = [s for s in doc.get("sections", []) if INSTA_SECTION in s.get("title", "")]
    if not secs:
        return ["'인스타 캐러셀·릴스 트렌드' 섹션이 없습니다"]
    items = [it for s in secs for it in s.get("items", [])]
    errors = [] if len(items) >= 3 else [f"인스타 섹션 항목이 {len(items)}개뿐입니다 (최소 3개)"]
    for it in items:
        ins = it.get("insta") or {}
        if len(ins.get("breakdown") or []) < 2:
            errors.append(f"'{it.get('title', '(제목 없음)')}' 항목의 insta.breakdown이 비어 있습니다")
        for post in ins.get("posts") or []:
            if "instagram.com/" not in str(post.get("url", "")):
                errors.append(f"'{it.get('title', '(제목 없음)')}' 항목의 insta.posts에 instagram.com 주소가 아닌 링크가 있습니다")
    return errors


def build_prompt(kind, today, out_path, extra=""):
    pid, label, start, end = period(kind, today)
    name = "daily_weekend" if is_weekend(kind, today) else kind
    text = (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    for key, val in {
        "PERIOD_ID": pid, "PERIOD_LABEL": label,
        "START": start.isoformat(), "END": end.isoformat(),
        "OUTPUT": str(out_path.relative_to(ROOT)),
        "INPUTS": inputs_for(kind, start, end),
        "RECENT": recent_titles(today) if kind == "daily" else "",
        "INSTA": (ROOT / "prompts" / "insta_section.md").read_text(encoding="utf-8")
                 if is_insta_day(kind, today) else "",
    }.items():
        text = text.replace("{{" + key + "}}", val)
    return text + extra


def has_network(host="api.anthropic.com"):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def wait_for_network(max_hours=6):
    """맥이 잠자기 중 잠깐 깨어난(DarkWake) 상태에서 실행되면 네트워크가 없다.
    인터넷이 연결될 때까지 기다렸다가 에이전트를 실행한다."""
    deadline = time.time() + max_hours * 3600  # 벽시계 기준 — 잠자기 시간도 포함
    if has_network():
        return
    log("네트워크 연결 대기 중 (맥이 잠자기 상태일 수 있음)...")
    while not has_network():
        if time.time() > deadline:
            log(f"{max_hours}시간 동안 네트워크에 연결되지 않아 중단합니다.")
            return
        time.sleep(30)
    log("네트워크 연결됨, 계속 진행합니다.")


class AuthExpired(Exception):
    """claude 로그인이 만료됐다. 다시 시도해도 소용없으므로 바로 멈추고 알린다."""


def run_agent(prompt):
    wait_for_network()
    cmd =[find_claude(), "-p", "--output-format", "text", "--allowedTools", *ALLOWED_TOOLS]
    if CONFIG.get("model"):
        cmd += ["--model", CONFIG["model"]]
    log(f"에이전트 실행: {cmd[0]}")
    proc = subprocess.run(cmd, input=prompt, text=True, cwd=ROOT,
                          capture_output=True, timeout=CONFIG.get("timeout_minutes", 40) * 60)
    if proc.stdout.strip():
        log("에이전트 응답 마지막 부분:\n" + proc.stdout.strip()[-1500:])
    if proc.returncode != 0:
        log(f"에이전트 종료 코드 {proc.returncode}: {proc.stderr.strip()[-1500:]}")
        if "Failed to authenticate" in proc.stdout + proc.stderr:
            raise AuthExpired()


def notify(title, message):
    if not CONFIG.get("notify", True):
        return
    def quote(s):  # AppleScript 문자열 — json.dumps는 한글을 \uXXXX로 바꿔서 쓸 수 없다
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    script = f"display notification {quote(message)} with title {quote(title)}"
    subprocess.run(["osascript", "-e", script], check=False)


def publish(message):
    """GitHub Pages 저장소로 push한다. config.json의 publish가 true일 때만."""
    if not CONFIG.get("publish") or not (ROOT / ".git").exists():
        return
    env = dict(os.environ, PATH="/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", ""))
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode == 0:
        log("올릴 변경 사항이 없습니다.")
        return
    git("commit", "-m", message)
    res = git("push", "origin", "HEAD")
    if res.returncode != 0:
        log("GitHub 업로드 실패: " + res.stderr.strip()[-800:])
        notify("🏢 휴대폰용 오피스 업데이트 실패", "logs 폴더를 확인해주세요.")
    else:
        log(f"GitHub Pages에 올렸습니다: {CONFIG.get('site_url', '')}")


def set_status(kind, pid, state):
    """office.html이 읽는 작성 상태. state: running · failed · None(지우기)"""
    path = ROOT / "assets" / "run-status.js"
    try:
        data = json.loads(path.read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
    except (OSError, IndexError, json.JSONDecodeError):
        data = {}
    if state:
        data[kind] = {"id": pid, "state": state, "at": dt.datetime.now().isoformat(timespec="seconds")}
    else:
        data.pop(kind, None)
    path.write_text("window.RUN_STATUS = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")


def auth_expired_notice():
    """로그인 만료 알림. catchup이 몇 분마다 돌아도 알림은 하루에 한 번만."""
    log("claude 로그인이 만료되어 멈춥니다. 터미널에서 claude를 실행해 다시 로그인하면 밀린 리포트를 이어서 씁니다.")
    flag = ROOT / "logs" / "auth-notified"
    today = dt.date.today().isoformat()
    try:
        if flag.read_text().strip() == today:
            return
    except OSError:
        pass
    flag.write_text(today)
    notify("🏢 Claude 로그인이 만료됐어요", "터미널에서 claude를 실행해 다시 로그인해주세요. 밀린 리포트는 자동으로 이어서 써요.")


def generate(kind, today, notify_fail=True):
    """성공하면 True."""
    pid = period(kind, today)[0]
    out_path = ROOT / "data" / kind / f"{pid}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.rename(out_path.with_suffix(".json.bak"))

    set_status(kind, pid, "running")
    extra = ""
    for attempt in (1, 2):
        log(f"{kind} {pid} 생성 시도 {attempt}")
        try:
            run_agent(build_prompt(kind, today, out_path, extra))
        except AuthExpired:
            set_status(kind, pid, "failed")
            raise
        errors = render.validate(out_path)
        if is_insta_day(kind, today) and out_path.exists():
            errors += validate_insta(out_path)
        if not errors:
            break
        log("검증 실패: " + "; ".join(errors))
        extra = ("\n\n## 이전 시도에서 생긴 문제 (반드시 고칠 것)\n"
                 + "\n".join(f"- {e}" for e in errors)
                 + f"\n기존 파일이 있으면 읽고 고쳐서 {out_path.relative_to(ROOT)}에 다시 저장한다.")
    else:
        set_status(kind, pid, "failed")
        if notify_fail:
            notify(f"🏢 {TEAM[kind]}의 리포트 작성이 실패했어요", "logs 폴더를 확인해주세요.")
        return False

    if is_weekend(kind, today):
        doc = json.loads(out_path.read_text(encoding="utf-8"))
        doc["edition"] = "weekend"
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    backup = out_path.with_suffix(".json.bak")
    if backup.exists():
        backup.unlink()
    html_path = render.render_file(out_path)
    render.build_index()
    set_status(kind, pid, None)
    log(f"완료: {html_path}")
    publish(f"{render.NAMES[kind]} 리포트 {pid}")
    headline = json.loads(out_path.read_text(encoding="utf-8")).get("headline", "")
    who = TEAM[kind]
    notify(f"🏢 {who}의 {render.NAMES[kind]} 보고가 도착했어요", headline or "오피스에서 확인해보세요.")
    if CONFIG.get("open_on_complete"):
        subprocess.run(["open", str(ROOT / "office.html")], check=False)
    return True


# 종류별 예정 시각 (office.html의 출근 시각과 같다)
SCHEDULE = {"daily": dt.time(9, 0), "weekly": dt.time(9, 10), "monthly": dt.time(9, 20), "quarterly": dt.time(9, 30)}
MAX_FAILS = 3  # 같은 리포트는 하루에 이 횟수까지만 다시 시도


def last_due_date(kind, d):
    """d 이전(포함)의 가장 최근 예정일."""
    if kind == "weekly":
        return d - dt.timedelta(days=d.weekday())
    if kind == "monthly":
        return d.replace(day=1)
    if kind == "quarterly":
        return d.replace(month=3 * ((d.month - 1) // 3) + 1, day=1)
    return d


def missing_reports(now):
    """예정 시각이 지났는데 아직 없는 리포트의 (종류, 기준일) — 오래된 것부터.
    최근 catchup_days일 안에 예정됐던 것만 챙긴다."""
    days = CONFIG.get("catchup_days", 3)
    oldest = now.date() - dt.timedelta(days=days - 1)
    due = []
    for kind in TYPES:
        d = now.date()
        while d >= oldest:
            d = last_due_date(kind, d)
            if d < oldest:
                break
            if dt.datetime.combine(d, SCHEDULE[kind]) <= now:
                pid = period(kind, d)[0]
                if not (ROOT / "data" / kind / f"{pid}.json").exists():
                    due.append((d, kind))
            d -= dt.timedelta(days=1)
    due.sort(key=lambda x: (x[0], TYPES.index(x[1])))  # 하위 리포트(데일리)부터
    return [(kind, d) for d, kind in due]


def catchup():
    """launchd가 몇 분마다 부른다. 맥이 깨어 있고 인터넷이 될 때만 밀린 리포트를 만든다."""
    lock = open(ROOT / "logs" / "catchup.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # 이미 다른 실행이 작성 중
    todo = missing_reports(dt.datetime.now())
    if not todo or not has_network():
        return
    state_path = ROOT / "logs" / "catchup-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    today = dt.date.today().isoformat()
    state = {k: v for k, v in state.items() if v.get("day") == today}  # 실패 횟수는 하루 단위
    for kind, d in todo:
        key = f"{kind}/{period(kind, d)[0]}"
        fails = state.get(key, {}).get("fails", 0)
        if fails >= MAX_FAILS:
            continue
        log(f"밀린 리포트 작성: {key}")
        try:
            ok = generate(kind, d, notify_fail=fails + 1 >= MAX_FAILS)
        except AuthExpired:  # 실패 횟수로 세지 않는다: 다시 로그인하면 같은 날 바로 이어서 쓴다
            auth_expired_notice()
            return
        if not ok:
            state[key] = {"day": today, "fails": fails + 1}
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=(*TYPES, "catchup", "render", "publish"))
    ap.add_argument("--date", help="기준일 YYYY-MM-DD (기본: 오늘)")
    args = ap.parse_args()
    if args.kind == "publish":
        publish("수동 업데이트")
        return
    if args.kind == "render":
        for kind in TYPES:
            for p in data_files(kind):
                render.render_file(p)
        render.build_index()
        log("HTML을 다시 만들었습니다.")
        return
    if args.kind == "catchup":
        catchup()
        return
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    try:
        ok = generate(args.kind, today)
    except AuthExpired:
        auth_expired_notice()
        ok = False
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
