#!/bin/zsh
# 리포트 자동 실행을 macOS launchd에 등록/해제한다.
#   ./scripts/schedule.sh install    등록 (기존 등록은 덮어씀)
#   ./scripts/schedule.sh uninstall  해제
#   ./scripts/schedule.sh status     등록 상태 확인
#
# 정해진 시각에 한 번 실행하는 대신, 맥이 깨어 있는 동안 5분마다 `run.py catchup`을 부른다.
# catchup은 예정 시각이 지났는데 아직 없는 리포트만 만들고, 인터넷이 안 되면 그냥 넘어간다.
# 그래서 맥이 잠들어 있던 날도 덮개를 열면 몇 분 안에 밀린 리포트가 작성된다.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
AGENTS="$HOME/Library/LaunchAgents"
LABEL="com.marketing-trend-report"
OLD_KINDS=(daily weekly monthly quarterly)  # 예전 방식(종류별 정시 실행) 등록

remove_old() {
  for kind in $OLD_KINDS; do
    launchctl bootout "gui/$(id -u)/$LABEL.$kind" 2>/dev/null || true
    rm -f "$AGENTS/$LABEL.$kind.plist"
  done
}

case "$1" in
  install)
    mkdir -p "$AGENTS" "$ROOT/logs"
    remove_old
    plist="$AGENTS/$LABEL.catchup.plist"
    launchctl bootout "gui/$(id -u)/$LABEL.catchup" 2>/dev/null || true
    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL.catchup</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$ROOT/scripts/run.py</string><string>catchup</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>$ROOT/logs/catchup.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/catchup.log</string>
</dict>
</plist>
PLIST
    plutil -lint "$plist" >/dev/null
    launchctl bootstrap "gui/$(id -u)" "$plist"
    echo "등록: 5분마다 밀린 리포트 확인"
    ;;
  uninstall)
    remove_old
    launchctl bootout "gui/$(id -u)/$LABEL.catchup" 2>/dev/null || true
    rm -f "$AGENTS/$LABEL.catchup.plist"
    echo "해제했습니다."
    ;;
  status)
    launchctl list | grep "$LABEL" || echo "등록된 일정이 없습니다."
    ;;
  *)
    echo "사용법: $0 install | uninstall | status"; exit 1 ;;
esac
