#!/usr/bin/env bash
# 데일리 작업로그의 .md 파일을 parkhq 저장소에 commit+push.
# 마운트 폴더에선 git이 깨지므로, /tmp(샌드박스 로컬)에 clone 후 파일 복사→push.
# 토큰은 저장소 working tree 밖의 보호 파일에서만 읽고, 절대 커밋/노출하지 않음.
set -u
export TZ="Asia/Seoul"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$(cd "$SCRIPT_DIR/.." && pwd)"     # …/데일리 작업로그
ROOT="$(cd "$LOGDIR/.." && pwd)"           # …/claude_project
TOKEN_FILE="$ROOT/.worklog-git-token.txt"
HOSTPATH="github.com/ralrachang/parkhq.git"

if [ ! -f "$TOKEN_FILE" ]; then
  echo "SKIP_NO_TOKEN  ($TOKEN_FILE 없음 → push 건너뜀, 로컬 파일은 그대로 보존)"; exit 2; fi
TOKEN="$(tr -d ' \t\r\n' < "$TOKEN_FILE")"
[ -z "$TOKEN" ] && { echo "SKIP_EMPTY_TOKEN"; exit 2; }

WORK="$(mktemp -d /tmp/parkhq.XXXXXX)"; trap 'cd /; rm -rf "$WORK"' EXIT
cd "$WORK" || exit 1
if git clone --depth 1 "https://${TOKEN}@${HOSTPATH}" repo 2>/dev/null; then cd repo
else mkdir repo && cd repo && git init -b main >/dev/null 2>&1 && git remote add origin "https://${TOKEN}@${HOSTPATH}"; fi
git config user.name "Park"; git config user.email "ralrachang@gmail.com"
cat > .gitignore <<'G'
.worklog-git-token.txt
*.token
*.pat
.env*
G
cp -f "$LOGDIR"/*.md ./ 2>/dev/null
git add -A
if git diff --cached --quiet; then echo "NO_CHANGES_TO_PUSH"; exit 0; fi
git commit -m "작업로그 업데이트 ($(date +%F))" >/dev/null 2>&1
if git push -u origin main 2>/tmp/push_err.txt; then
  echo "PUSH_OK  ($(date +%F))  files=$(ls *.md 2>/dev/null | wc -l)"
else
  echo "PUSH_FAIL:"; sed "s/${TOKEN}/***TOKEN***/g" /tmp/push_err.txt | tail -4; exit 1
fi
