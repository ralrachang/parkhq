#!/usr/bin/env bash
# 전날(또는 인자로 받은 날짜) 수정된 파일을 프로젝트별로 묶어 출력.
# 사용법: scan_changes.sh [YYYY-MM-DD]   (기본값: 어제, KST 기준)
export TZ="Asia/Seoul"
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"      # <ROOT>/데일리 작업로그/.scripts/
OUTNAME="데일리 작업로그"

if [ "${1:-}" != "" ]; then D="$1"; else D="$(date -d 'yesterday' +%F)"; fi
N="$(date -d "$D +1 day" +%F)"

echo "TARGET_DATE=$D"
echo "ROOT=$ROOT"

mapfile -d '' FILES < <(find "$ROOT" \
  \( -name '.*' -o -name node_modules -o -name "$OUTNAME" \
     -o -name dist -o -name build -o -name out -o -name '.next' \
     -o -name __pycache__ -o -name venv -o -name '.venv' \
     -o -name coverage -o -name '.turbo' -o -name '.cache' \) -prune \
  -o -type f -newermt "$D 00:00:00" ! -newermt "$N 00:00:00" -print0 2>/dev/null)

if [ "${#FILES[@]}" -eq 0 ]; then echo "NO_CHANGES"; exit 0; fi

declare -A COUNT
TMP="$(mktemp)"
for f in "${FILES[@]}"; do
  rel="${f#$ROOT/}"
  if [[ "$rel" == */* ]]; then proj="${rel%%/*}"; else proj="(루트 파일)"; fi
  COUNT["$proj"]=$(( ${COUNT["$proj"]:-0} + 1 ))
  printf '%s\t%s\n' "$proj" "$rel" >> "$TMP"
done

echo "TOTAL_FILES=${#FILES[@]}  PROJECTS=${#COUNT[@]}"
echo "---"

while IFS=$'\t' read -r cnt proj; do
  [ -z "${proj:-}" ] && continue
  echo "=== PROJECT: $proj ($cnt files) ==="
  awk -F'\t' -v p="$proj" '$1==p{print "  "$2}' "$TMP" | sort | head -40
  if [ "$cnt" -gt 40 ]; then echo "  ...(외 $((cnt-40))개 파일)"; fi
done < <(for p in "${!COUNT[@]}"; do printf '%s\t%s\n' "${COUNT[$p]}" "$p"; done | sort -t$'\t' -k1,1rn)

rm -f "$TMP"
