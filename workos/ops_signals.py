#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PARK HQ Work OS — 운영 신호 계산 (probe_ops 대체, 프로젝트 단위).
docs/01_next_ops_board.md §운영신호. projects 테이블(루트 롤업)을 기준으로
각 프로젝트의 운영 신호를 계산한다. ops_board.py가 이 모듈을 단일 출처로 사용.

신호:
  - 방치도(idle): now(=DB 전체 max ts, KST) 기준 마지막 활동 경과일
                  → 오늘(0) / 3일(1~3) / 주간(4~7) / 2주(8~14) / 오래(15+).
                  now를 DB의 max(ts)로 잡아 PC 시계와 무관하게 견고(설계 원칙).
  - 추세(trend): 최근 14일 활동 세션 vs 직전 14일 → ↑증가 / ↓감소 / =정체.
                 각 세션은 '마지막 활동일'이 속한 한쪽 창에만 귀속(상호배타).
  - 문서등급(doc): 프로젝트 폴더 실측(README / CLAUDE·AGENTS / docs·specs)
                  → A / B / C / 없음 / 경로없음.
  - 현재 초점(focus): 가장 최근 세션의 aiTitle. 없으면 그 세션의 최근 입력으로 폴백.
  - 시작일(first) · 세션 수 · 사람입력(typed) 수 · 출력토큰(canonical, 진실값).

날짜는 전부 KST(+9h)의 날짜부로 계산·표기 — ts(데이터) 기반이라 PC 시계 무관,
동시에 한국 사용자의 '오늘' 감각과 정합(검증자 지적 반영: UTC off-by-one 제거).
사용법: python ops_signals.py [--db ./workos.db]
"""
import argparse, json, os, sqlite3, sys
from datetime import date
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# KST 날짜부 추출식 — now/last/first/추세 윈도우 모두 이걸로 통일.
KDATE = "substr(datetime(ts,'+9 hours'),1,10)"

# 방치 임계값(일) — 사용자 확정 #3 대기(잠정). [경계는 '이하' 포함]
IDLE_TODAY, IDLE_FEW, IDLE_WEEK, IDLE_TWOWK = 0, 3, 7, 14

def idle_bucket(days):
    if days is None:        return "오래"
    if days <= IDLE_TODAY:  return "오늘"
    if days <= IDLE_FEW:    return "3일"
    if days <= IDLE_WEEK:   return "주간"
    if days <= IDLE_TWOWK:  return "2주"
    return "오래"

# 운영 상태(플래그) = 순수 방치도. 추세는 별도 신호로 분리 표기(글리프 충돌 제거).
#   활발 ●(오늘/3일) · 식어감 ◆(주간/2주) · 방치 ▲(오래)
def op_status(bucket):
    if bucket == "오래":          return "방치"
    if bucket in ("주간", "2주"): return "식어감"
    return "활발"

def doc_grade(root):
    """프로젝트 폴더 실측 → 문서등급. 사용자 확정 #4 대기(잠정 정의)."""
    if not root or not os.path.isdir(root):
        return "경로없음"
    try:
        names = os.listdir(root)
    except Exception:
        return "경로없음"
    low = {n.lower(): n for n in names}
    has_readme = any(n.startswith("readme") for n in low)
    has_guide  = any(n in low for n in ("claude.md", "agents.md", "gemini.md"))
    has_docs   = any(d in low and os.path.isdir(os.path.join(root, low[d]))
                     for d in ("docs", "specs"))
    if has_readme and has_guide and has_docs: return "A"
    if has_readme and has_guide:              return "B"
    if has_readme or has_guide or has_docs:   return "C"
    return "없음"

def days_between(d1, d2):
    """문자열 날짜(YYYY-MM-DD) d2 - d1 의 일수. None 방어."""
    if not d1 or not d2:
        return None
    try:
        y1, m1, dd1 = map(int, d1.split("-")); y2, m2, dd2 = map(int, d2.split("-"))
        return (date(y2, m2, dd2) - date(y1, m1, dd1)).days
    except Exception:
        return None

def _first_text(raw):
    """raw_json(user 입력)에서 첫 텍스트를 추출(폴백 초점용)."""
    try:
        m = (json.loads(raw).get("message") or {})
        c = m.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            for b in c:
                if isinstance(b, str):
                    return b
                if isinstance(b, dict) and b.get("type") == "text":
                    return b.get("text", "")
    except Exception:
        pass
    return ""

def _oneline(s, n=80):
    s = " ".join((s or "").split())
    return s[:n] + ("…" if len(s) > n else "")

def compute(db_path):
    con = sqlite3.connect(db_path); c = con.cursor()
    now_date = c.execute(f"SELECT MAX({KDATE}) FROM records WHERE ts IS NOT NULL").fetchone()[0]

    projs = c.execute("SELECT project_id, project_name, project_root, n_workspaces, n_records, "
                      "category, agent FROM projects").fetchall()

    # 프로젝트별 집계: 시작·마지막활동·세션수·사람입력·출력토큰 (모두 KST 날짜)
    agg = {}
    for pid, first_d, last_d, nsess, nhuman, tout in c.execute(f"""
        SELECT project_id, MIN({KDATE}), MAX({KDATE}),
               COUNT(DISTINCT session_id),
               SUM(CASE WHEN rec_type='user' AND origin_kind='human'
                        AND prompt_source='typed' THEN 1 ELSE 0 END),
               COALESCE(SUM(CASE WHEN is_canonical=1 AND rec_type='assistant'
                        THEN out_tok END),0)
        FROM records WHERE project_id IS NOT NULL AND ts IS NOT NULL GROUP BY project_id"""):
        agg[pid] = dict(first=first_d, last=last_d, sessions=nsess,
                        human=nhuman or 0, out_tok=tout or 0)

    # 추세: 각 (프로젝트, 세션)을 '세션 마지막 활동일'이 속한 한 창에만 귀속(상호배타).
    win = {}
    for pid, last14, prev14 in c.execute(f"""
        WITH ses AS (
          SELECT project_id, session_id, MAX({KDATE}) ld
          FROM records WHERE project_id IS NOT NULL AND ts IS NOT NULL
          GROUP BY project_id, session_id)
        SELECT project_id,
          SUM(CASE WHEN ld > date(?, '-14 days') THEN 1 ELSE 0 END),
          SUM(CASE WHEN ld <= date(?, '-14 days') AND ld > date(?, '-28 days')
                   THEN 1 ELSE 0 END)
        FROM ses GROUP BY project_id""", (now_date, now_date, now_date)):
        win[pid] = (last14 or 0, prev14 or 0)

    # 세션→프로젝트(세션 내 레코드 최다 프로젝트, 단 컨테이너 루트는 마지막 수단) + 세션 최종활동
    sess_proj, sess_proj_n = {}, {}
    rootlike = set(p[0] for p in projs if p[1] in ("claude_project",))
    for sid, pid, n in c.execute("""SELECT session_id, project_id, COUNT(*) n FROM records
        WHERE session_id IS NOT NULL AND project_id IS NOT NULL
        GROUP BY session_id, project_id"""):
        prev = sess_proj.get(sid)
        # 실제 프로젝트를 루트 버킷보다 우선
        better = (prev is None
                  or (sess_proj[sid] in rootlike and pid not in rootlike)
                  or (not (pid in rootlike and sess_proj[sid] not in rootlike) and n > sess_proj_n[sid]))
        if better:
            sess_proj[sid] = pid; sess_proj_n[sid] = n
    sess_last = dict(c.execute(f"SELECT session_id, MAX({KDATE}) FROM records "
                               "WHERE session_id IS NOT NULL GROUP BY session_id").fetchall())

    # 세션→aiTitle(있으면). ai-title 레코드는 ts=NULL이므로 rowid(도착순)로 최신 결정.
    sess_title = {}
    for sid, title in c.execute("""SELECT session_id, json_extract(raw_json,'$.aiTitle') t
        FROM records WHERE rec_type='ai-title' AND t IS NOT NULL ORDER BY rowid"""):
        sess_title[sid] = title

    # 프로젝트별 현재초점 — 3단 폴백으로 커버리지 확보:
    #   ① 최근 세션의 제목  ② 최근 '제목 있는' 세션의 제목(이전)  ③ 최근 typed 입력
    latest_sess, titled_focus = {}, {}
    for sid, pid in sess_proj.items():
        when = sess_last.get(sid, "")
        if pid not in latest_sess or when > latest_sess[pid][1]:
            latest_sess[pid] = (sid, when)
        if sid in sess_title and (pid not in titled_focus or when > titled_focus[pid][1]):
            titled_focus[pid] = (sess_title[sid], when)
    fallback = {}
    for pid, raw in c.execute("""SELECT project_id, raw_json FROM records
        WHERE rec_type='user' AND origin_kind='human' AND prompt_source='typed'
          AND project_id IS NOT NULL AND ts IS NOT NULL ORDER BY ts"""):
        t = _oneline(_first_text(raw))
        if t:
            fallback[pid] = t           # ts 오름차순 → 마지막 = 최신
    focus, focus_src = {}, {}
    for pid, (sid, _when) in latest_sess.items():
        if sid in sess_title:
            focus[pid], focus_src[pid] = sess_title[sid], "제목"
        elif pid in titled_focus:
            focus[pid], focus_src[pid] = titled_focus[pid][0], "제목·이전"
        elif pid in fallback:
            focus[pid], focus_src[pid] = fallback[pid], "최근입력"

    rows = []
    for pid, name, root, n_ws, n_rec, cat, agent in projs:
        a = agg.get(pid, dict(first=None, last=None, sessions=0, human=0, out_tok=0))
        days = days_between(a["last"], now_date)
        bucket = idle_bucket(days)
        l14, p14 = win.get(pid, (0, 0))
        trend = "↑" if l14 > p14 else ("↓" if l14 < p14 else "=")
        rows.append(dict(
            project_id=pid, name=name, root=root, category=cat, agent=agent,
            n_workspaces=n_ws, n_records=n_rec,
            first=a["first"], last=a["last"], days_idle=days, bucket=bucket,
            sessions=a["sessions"], human=a["human"], out_tok=a["out_tok"],
            last14=l14, prev14=p14, trend=trend,
            doc=doc_grade(root), focus=focus.get(pid, ""), focus_src=focus_src.get(pid, ""),
            status=op_status(bucket),
        ))
    con.close()
    rows.sort(key=lambda r: r["out_tok"], reverse=True)
    return now_date, rows

TREND_LABEL = {"↑": "증가", "↓": "감소", "=": "정체"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "workos.db"))
    args = ap.parse_args()
    now_date, rows = compute(args.db)
    print(f"now(기준일, DB max ts·KST)={now_date}  projects={len(rows)}")
    print("=" * 104)
    print(f"{'상태':<5}{'방치':<5}{'추세':<4}{'문서':<5}{'경과':>4}{'세션':>5}{'입력':>5}"
          f"{'출력토큰':>13}  프로젝트 / 현재초점")
    print("-" * 104)
    for r in rows:
        flag = {"방치": "▲", "식어감": "◆", "활발": "●"}[r["status"]]
        days = str(r["days_idle"]) if r["days_idle"] is not None else "?"
        print(f"{flag}{r['status']:<4}{r['bucket']:<5}{r['trend']+TREND_LABEL[r['trend']]:<4}"
              f"{r['doc']:<5}{days:>4}{r['sessions']:>5}{r['human']:>5}{r['out_tok']:>13,}  "
              f"{r['name']}  ·  {(r['focus'] or '—')[:38]}")
    print("-" * 104)
    from collections import Counter
    sc = Counter(r["status"] for r in rows); bc = Counter(r["bucket"] for r in rows)
    dc = Counter(r["doc"] for r in rows)
    print(f"상태: 활발 {sc['활발']} · 식어감 {sc['식어감']} · 방치 {sc['방치']}")
    print("방치도: " + " · ".join(f"{k} {bc[k]}" for k in ("오늘", "3일", "주간", "2주", "오래") if bc[k]))
    print("문서등급: " + " · ".join(f"{k} {dc[k]}" for k in ("A", "B", "C", "없음", "경로없음") if dc[k]))

if __name__ == "__main__":
    main()
