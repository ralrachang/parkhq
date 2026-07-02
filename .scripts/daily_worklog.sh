#!/usr/bin/env bash
# 매일 아침 자동 실행되는 '데일리 작업로그' 생성 드라이버.
# 동작: 어제(KST) 변경 파일 스캔 → 변경 없으면 스텁, 있으면 claude 헤드리스로 서사 작성 → git push.
# 멱등성: 해당 날짜 로그가 이미 있으면 건너뜀. Windows 작업 스케줄러에서 호출.
# 사용법: daily_worklog.sh [YYYY-MM-DD]   (기본값: 어제, KST 기준)
set -u
# 주의: 이 머신의 git-bash는 TZ=Asia/Seoul 지정 시 오히려 GMT로 깨짐.
# Windows 로컬 시간이 이미 KST이므로 TZ를 건드리지 않는다(날짜·타임스탬프 정확).
# (scan_changes.sh 는 내부에서 자체 TZ 처리 → 기존 로그와 동일한 윈도잉 유지)
# npm 전역(claude) PATH 보장 (스케줄러의 비대화형 환경 대비)
export PATH="/c/Users/wonbuilding/AppData/Roaming/npm:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$(cd "$SCRIPT_DIR/.." && pwd)"        # …/데일리 작업로그
ROOT="$(cd "$LOGDIR/.." && pwd)"              # …/claude_project
RUNLOG="$SCRIPT_DIR/worklog_run.log"

D="${1:-$(date -d 'yesterday' +%F)}"
W="$(date -d "$D" +%u)"                       # 1=월 … 7=일
case "$W" in 1) DOW=월;;2) DOW=화;;3) DOW=수;;4) DOW=목;;5) DOW=금;;6) DOW=토;;7) DOW=일;;*) DOW="";;esac
LOGFILE="$LOGDIR/$D.md"

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$RUNLOG"; }

log "=== daily_worklog start (target=$D $DOW) ==="

if [ -f "$LOGFILE" ]; then
  log "ALREADY_EXISTS: $LOGFILE — 건너뜀"
  exit 0
fi

# 1) 변경 스캔
SCANTMP="/tmp/worklog_scan_$D.txt"
bash "$SCRIPT_DIR/scan_changes.sh" "$D" > "$SCANTMP" 2>/dev/null

if grep -q '^NO_CHANGES' "$SCANTMP"; then
  log "NO_CHANGES — 스텁 작성"
  printf '# 데일리 작업로그 — %s (%s)\n\n> 전날(%s) 추적된 파일 변경이 없었습니다.\n' "$D" "$DOW" "$D" > "$LOGFILE"
else
  TOTAL="$(sed -n 's/^TOTAL_FILES=\([0-9]*\).*/\1/p' "$SCANTMP")"
  PROJ="$(sed -n 's/.*PROJECTS=\([0-9]*\).*/\1/p' "$SCANTMP" | head -1)"
  log "변경 감지: ${PROJ}개 프로젝트, ${TOTAL}개 파일 → claude 헤드리스 서사 작성"

  PROMPT="당신은 '데일리 작업로그' 자동화입니다. 대상 날짜: ${D} (${DOW}).
D:\\\\claude_project 안 여러 프로젝트에서 그날 변경된 파일을 사람이 읽는 서사형 요약으로 정리해, 로그 파일 하나를 작성하세요.

1) 그날 변경 파일 목록을 먼저 확인: \`cat ${SCANTMP}\` 실행 (프로젝트별, 각 프로젝트 최대 40개까지 표시). 총 ${PROJ}개 프로젝트, ${TOTAL}개 파일.
2) 각 프로젝트에서 '무엇을 했는지' 정확히 쓰기 위해, 변경 파일 중 정보가 많은 것 3~8개를 직접 열어보세요(Read 또는 cat): 새 .md/기획문서/README/*.log/새 소스 파일(컴포넌트·스크립트)/마이그레이션 SQL 등. 경로는 D:\\\\claude_project\\\\<프로젝트>\\\\... 입니다. node_modules/venv/.git 등은 무시. 추측하지 말고 파일이 실제로 보여주는 내용에 근거해 쓰세요.
3) 아래 경로에 파일을 작성: D:\\\\claude_project\\\\데일리 작업로그\\\\${D}.md
형식(정확히 따를 것):

# 데일리 작업로그 — ${D} (${DOW})

> 전날(${D}) 선택 폴더에서 파일 변경이 있었던 프로젝트를 자동 감지해 정리했습니다. 총 ${PROJ}개 프로젝트, ${TOTAL}개 파일 변경.

## <프로젝트> — <한 줄 핵심 요약> (<N>개 파일)
<그 프로젝트에서 한 작업을 2~4문장으로 구체적·자연스럽게 한국어로 서술>

- 파일 수가 많은 프로젝트부터 내림차순으로 각 프로젝트마다 ## 섹션 하나씩, 모든 프로젝트 포함.
- 기능명·문서명·컴포넌트명 등 구체적 고유명사를 담되 과장 없이 사실적으로.
- 이 로그는 공개 GitHub 저장소에 올라갑니다. 자격증명·API키는 물론, 협상 금액·견적가·할인단가·계약조건 같은 민감 수치는 구체 숫자 대신 일반화해 쓰세요(예: '견적 기준값과 협상 원칙을 정리'). 제3자 개인정보(고객 실명·연락처)도 금지.
- 파일 작성만 하고, 본문 전체를 출력하지는 마세요."

  cd "$ROOT" || exit 1
  if ! claude -p "$PROMPT" --allowedTools Bash Read Write Edit Glob Grep >> "$RUNLOG" 2>&1; then
    log "WARN: claude 헤드리스 실행이 실패 코드를 반환함 (로그 확인)"
  fi
fi

# 2) 결과 검증
if [ ! -f "$LOGFILE" ]; then
  log "ERROR: $LOGFILE 가 생성되지 않음 — push 건너뜀"
  exit 1
fi
log "로그 작성 완료: $LOGFILE ($(wc -c < "$LOGFILE") bytes)"

# 3) parkhq에 push
PUSHOUT="$(bash "$SCRIPT_DIR/git_push.sh" 2>&1)"
log "git_push: $(echo "$PUSHOUT" | tail -1)"

rm -f "$SCANTMP"
log "=== daily_worklog done ($D) ==="
