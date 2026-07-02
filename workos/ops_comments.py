#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PARK HQ Work OS — 프로젝트별 AI 상태 코멘트 생성기.
점검대 카드를 클릭(펼침)하면 보이는 '지금 상황' 요약 2~3문장 + 다음 액션 1개.

원칙:
- 근거는 전부 실측: ops_signals 신호(방치도·추세·세션·토큰) + 최근 세션 제목(aiTitle)
  + 최근 typed 사용자 입력. 추측 금지를 프롬프트에 명시.
- 생성은 claude -p 헤드리스 **1회 배치 호출**(표시 프로젝트 전체 → JSON 한 번에).
- 캐시: workos.db의 ops_comments 테이블. 프로젝트별 evidence_hash(근거 데이터의
  sha256)가 그대로면 재생성하지 않음 → 재실행 비용 0.
- 산출물은 DB(gitignore)에만 저장 — 세션 제목 등 민감 가능, 커밋 금지.

파이프라인 순서: ingest → verify_gate → **ops_comments** → ops_board
사용법: python ops_comments.py [--db ./workos.db] [--force] [--dry-run] [--timeout 300]
"""
import argparse, hashlib, json, os, shutil, sqlite3, subprocess, sys
from datetime import datetime, timezone, timedelta
import ops_signals
from ops_signals import KDATE
from ops_board import HIDDEN_NAMES, NOISE_NAMES, PROJECT_CATEGORY, DEFAULT_CATEGORY

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))

DDL = """
CREATE TABLE IF NOT EXISTS ops_comments (
  project_id    TEXT PRIMARY KEY,
  project_name  TEXT,
  evidence_hash TEXT,
  comment       TEXT,
  generated_at  TEXT
);
"""

N_TITLES, N_INPUTS = 5, 3


def gather_evidence(db_path, rows):
    """표시 프로젝트별 근거 텍스트(실측만). {pid: evidence_str}"""
    con = sqlite3.connect(db_path); c = con.cursor()
    # 세션→프로젝트(레코드 다수결, 단 컨테이너 루트는 마지막 수단 — ops_signals와 동일 규칙)
    rootlike = {pid for pid, nm in c.execute("SELECT project_id, project_name FROM projects")
                if nm in NOISE_NAMES}
    sess_proj, sess_n = {}, {}
    for sid, pid, n in c.execute("""SELECT session_id, project_id, COUNT(*) FROM records
        WHERE session_id IS NOT NULL AND project_id IS NOT NULL
        GROUP BY session_id, project_id"""):
        prev = sess_proj.get(sid)
        better = (prev is None
                  or (prev in rootlike and pid not in rootlike)
                  or (not (pid in rootlike and prev not in rootlike) and n > sess_n[sid]))
        if better:
            sess_proj[sid] = pid; sess_n[sid] = n
    sess_last = dict(c.execute(f"SELECT session_id, MAX({KDATE}) FROM records "
                               "WHERE session_id IS NOT NULL GROUP BY session_id").fetchall())
    # 세션당 최신 aiTitle(rowid=도착순) → 프로젝트별 최근 세션 제목
    sess_title = {}
    for sid, t in c.execute("""SELECT session_id, json_extract(raw_json,'$.aiTitle') t
        FROM records WHERE rec_type='ai-title' AND t IS NOT NULL ORDER BY rowid"""):
        sess_title[sid] = t
    titles = {}                                   # pid -> [(last_date, title)]
    for sid, t in sess_title.items():
        pid = sess_proj.get(sid)
        if pid:
            titles.setdefault(pid, []).append((sess_last.get(sid) or "", t))
    # 프로젝트별 최근 typed 입력(ts 오름차순 → 뒤가 최신)
    inputs = {}
    for pid, raw in c.execute("""SELECT project_id, raw_json FROM records
        WHERE rec_type='user' AND origin_kind='human' AND prompt_source='typed'
          AND project_id IS NOT NULL AND ts IS NOT NULL ORDER BY ts"""):
        t = ops_signals._oneline(ops_signals._first_text(raw), 90)
        if t:
            inputs.setdefault(pid, []).append(t)
    con.close()

    ev = {}
    for r in rows:
        pid = r["project_id"]
        tt = sorted(titles.get(pid, []), reverse=True)[:N_TITLES]
        ii = inputs.get(pid, [])[-N_INPUTS:]
        lines = [
            f"이름: {r['name']} (카테고리 {PROJECT_CATEGORY.get(r['name'], DEFAULT_CATEGORY)})",
            f"상태: {r['status']} · 마지막 활동 {r['days_idle']}일 전({r['last']}) · "
            f"추세 최근14일 세션 {r['last14']} vs 직전 {r['prev14']}",
            f"규모: 기간 {r['first']}~{r['last']} · 세션 {r['sessions']} · 사람입력 {r['human']} · "
            f"출력 {r['out_tok']/1e6:.1f}M토큰 · 문서등급 {r['doc']}",
            "최근 세션 제목: " + (" | ".join(t for _, t in tt) if tt else "(없음)"),
            "최근 입력: " + (" | ".join(ii) if ii else "(없음)"),
        ]
        ev[pid] = "\n".join(lines)
    return ev


def build_prompt(items):
    """items = [(key, name, evidence)] → 배치 프롬프트. 키는 숫자(모델 echo 오류 방지)."""
    blocks = "\n\n".join(f"[{k}] {name}\n{evd}" for k, name, evd in items)
    return (
        "[중요] 이 작업에 도구·파일 접근은 필요 없고 전부 거부됩니다. 시도하지 마세요.\n"
        "아래 제공된 데이터만 근거로 순수 텍스트 JSON 객체 하나만 출력하세요.\n"
        "응답의 첫 문자는 '{', 마지막 문자는 '}' 여야 하며 그 외 어떤 텍스트도 금지합니다.\n\n"
        "당신은 PARK HQ Work OS 운영 점검대의 상태 코멘트 작성자입니다.\n"
        "아래는 프로젝트별 실측 데이터(방치도·추세·최근 세션 제목·최근 사용자 입력)입니다.\n"
        "각 프로젝트의 '지금 상황'을 2~3문장으로 요약하고, 마지막에 다음 액션 1개를 제안하세요.\n"
        "규칙:\n"
        "- 데이터에 나온 사실만 사용, 추측·과장 금지. 한국어, 존댓말 없이 간결한 보고체.\n"
        "- 세션 제목·입력에서 실제 작업 내용을 구체적으로 짚을 것(예: 어떤 기능/문서/조사).\n"
        "- 방치·식어감 프로젝트는 '언제부터 왜 멈췄는지 보이는 단서'가 있으면 언급.\n"
        "- 출력은 JSON 하나만. 코드펜스·설명·주석 금지. 형식: {\"1\": \"코멘트\", \"2\": \"코멘트\", ...}\n\n"
        f"[프로젝트 데이터]\n\n{blocks}"
    )


def call_claude(prompt, timeout):
    exe = shutil.which("claude") or os.path.expanduser("~/AppData/Roaming/npm/claude.cmd")
    if not exe or not os.path.exists(exe):
        raise RuntimeError("claude CLI를 찾을 수 없음 (npm 전역 설치 필요)")
    # 프롬프트는 stdin으로 전달 — .CMD 셔틀이 cmd.exe를 거치며 argv는 8,191자에서
    # 잘린다(배치 프롬프트 ~10KB, 2026-07-02 실측: 본문 소실 후 "어떤 작업을?" 응답).
    r = subprocess.run([exe, "-p"], input=prompt, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p 실패(exit {r.returncode}): {(r.stderr or '')[:300]}")
    return r.stdout or ""


def parse_json(s):
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        raise ValueError(f"응답에서 JSON을 찾지 못함: {s[:200]!r}")
    return json.loads(s[i:j + 1])


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--db", default=os.path.join(here, "workos.db"))
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 전체 재생성")
    ap.add_argument("--dry-run", action="store_true", help="AI 호출 없이 근거·대상만 출력")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    _, rows = ops_signals.compute(args.db)
    rows = [r for r in rows if r["name"] not in HIDDEN_NAMES and r["name"] not in NOISE_NAMES]

    con = sqlite3.connect(args.db)
    con.executescript(DDL)
    cached = {pid: h for pid, h in con.execute("SELECT project_id, evidence_hash FROM ops_comments")}

    evidence = gather_evidence(args.db, rows)
    stale = []
    for r in rows:
        pid = r["project_id"]
        h = hashlib.sha256(evidence[pid].encode("utf-8")).hexdigest()
        r["_ehash"] = h
        if args.force or cached.get(pid) != h:
            stale.append(r)

    print(f"표시 프로젝트 {len(rows)}개 · 코멘트 재생성 대상 {len(stale)}개 (캐시 유지 {len(rows)-len(stale)})")
    if args.dry_run:
        for r in stale:
            print(f"\n--- {r['name']} ---\n{evidence[r['project_id']]}")
        con.close(); return
    if not stale:
        con.close(); print("모두 최신 — AI 호출 없음"); return

    items = [(str(i + 1), r["name"], evidence[r["project_id"]]) for i, r in enumerate(stale)]
    prompt = build_prompt(items)
    out = call_claude(prompt, args.timeout)
    try:
        parsed = parse_json(out)
    except (ValueError, json.JSONDecodeError):
        print("  ⚠️ 1차 응답이 JSON 형식이 아님 — 1회 재시도")
        out = call_claude(prompt + "\n\n[재시도] 직전 응답이 JSON이 아니었습니다. "
                          "설명·사과·도구 언급 없이 JSON 객체 하나만 출력하세요.", args.timeout)
        parsed = parse_json(out)

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    ok = missing = 0
    for i, r in enumerate(stale):
        v = parsed.get(str(i + 1))
        cmt = (v if isinstance(v, str) else "").strip()   # 비문자열(숫자·객체) 방어
        if cmt:
            con.execute("INSERT OR REPLACE INTO ops_comments "
                        "(project_id, project_name, evidence_hash, comment, generated_at) "
                        "VALUES (?,?,?,?,?)",
                        (r["project_id"], r["name"], r["_ehash"], cmt, now))
            ok += 1
        else:
            missing += 1
            print(f"  ⚠️ 응답 누락: {r['name']} (기존 코멘트 유지)")
    if ok == 0:
        # 전량 누락 = 응답 형식 회귀 의심 — 조용히 매번 재호출(비용 누수)하는 대신 크게 실패.
        con.close()
        raise SystemExit(f"ERROR: 코멘트를 하나도 파싱하지 못함 — 응답 형식 확인 필요. 앞부분: {out[:200]!r}")
    con.commit(); con.close()
    print(f"코멘트 저장 {ok}건" + (f" · 누락 {missing}건" if missing else "") + f" · 생성시각 {now} KST")


if __name__ == "__main__":
    main()
