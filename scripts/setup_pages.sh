#!/bin/zsh
# 이 폴더를 GitHub 저장소로 만들고 GitHub Pages를 켠다. `gh auth login`을 먼저 해야 한다.
#   ./scripts/setup_pages.sh [저장소 이름]   (기본: marketing-trend-office)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
REPO="${1:-marketing-trend-office}"

gh auth status >/dev/null 2>&1 || { echo "먼저 터미널에서 'gh auth login'으로 GitHub에 로그인해주세요."; exit 1; }
OWNER="$(gh api user -q .login)"
ID="$(gh api user -q .id)"
gh auth setup-git   # 자동 실행(launchd)에서도 push할 수 있게 gh를 git 인증 도우미로 등록

if [ ! -d .git ]; then
  git init -q -b main
fi
# 공개 저장소이므로 개인 이메일 대신 GitHub noreply 주소로 커밋한다
git config user.name "$OWNER"
git config user.email "$ID+$OWNER@users.noreply.github.com"

git add -A
git diff --cached --quiet || git commit -q -m "마케팅팀 오피스 첫 업로드"

if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create "$REPO" --public --source . --remote origin --push \
    --description "매일 아침 마케팅 트렌드를 보고하는 픽셀 오피스"
else
  git push -u origin main
fi

gh api -X POST "repos/$OWNER/$REPO/pages" -f "source[branch]=main" -f "source[path]=/" >/dev/null 2>&1 \
  || echo "(Pages가 이미 켜져 있어요)"
URL="https://$OWNER.github.io/$REPO/office.html"

python3 - "$URL" <<'PY'
import json, sys
p = "config.json"; c = json.load(open(p))
c["publish"] = True; c["site_url"] = sys.argv[1]
json.dump(c, open(p, "w"), ensure_ascii=False, indent=2); open(p, "a").write("\n")
PY
git add config.json && git commit -q -m "GitHub Pages 설정" && git push -q

echo ""
echo "완료! 1~2분 뒤 휴대폰에서 이 주소를 여세요:"
echo "  $URL"
