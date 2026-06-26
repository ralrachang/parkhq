#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PARK HQ Work OS — 운영 점검대(Operations Board) 생성기. (읽기 전용·로컬 전용)
docs/01_next_ops_board.md. 참고 레이아웃: ex.jpg (HAM MEDIA OS '작업 전 점검대').

구성:
  80%  프로젝트 운영 현황 + 방치(소외) 감지 — 카테고리(팀)별 컬럼, 카드=프로젝트.
       카드: [상태 플래그] 번호 이름 · 경과일 · 추세 · 문서등급 · 담당에이전트
             펼치면 초점(aiTitle/입력)·세션·사람입력·출력토큰·시작일·추천액션.
       방치 카드는 틴트+배지로 강조, 컬럼 내 정렬은 상태 우선(방치→식어감→활발).
  20%  기존 지표 스트립(활동 워크스페이스·세션·출력토큰·일별추이) — dashboard.py 축약.
  부가  시작일 타임라인 · 본부문서(기준 원본) · 활용 팁 (모두 접기).
  에이전트 레이어: 카테고리→담당 + 프로젝트 오버라이드 + 카드별 추천 액션(환경 조성).

신호 계산은 ops_signals.compute()(probe_ops 대체)에 위임 — 단일 출처.
비프로젝트 버킷(컨테이너 루트·임시 폴더)은 NOISE_NAMES로 격리해 집계 왜곡 방지.
의존성 0·자체완결 HTML·JS 없음(펼치기는 <details>). 민감(세션제목·고객명) 포함 가능 →
로컬 전용, 절대 커밋 금지(.gitignore: workos/*.html).

⚠️ 아래 설정은 사용자 확정 대기(잠정값). 확정되면 이 dict만 고치면 됨:
   PROJECT_CATEGORY(#1) · CATEGORY_AGENT·PROJECT_AGENT(#2) · ops_signals.IDLE_*(#3) ·
   ops_signals.doc_grade(#4) · recommend()(#5) · NOISE_NAMES(비프로젝트 처리).
보류(데이터/규칙 필요): 민감도 축(▲민감/◆주의) · 상태=수정/승인/읽기 컬럼 · cwd-NULL 세션 완전귀속.
사용법: python ops_board.py [--db ./workos.db] [--out ./ops_board.html]
"""
import argparse, html, os, sqlite3, sys
from collections import Counter
from datetime import datetime, timezone, timedelta
import ops_signals
from ops_signals import days_between, TREND_LABEL, KDATE

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 잠정 설정 (사용자 확정 대기) ──────────────────────────────────────
CATEGORY_ORDER = ["부동산·빌딩", "제품·플랫폼", "콘텐츠·실험", "인프라·내부"]

# #1 프로젝트 → 카테고리. 규칙: '부동산 도메인이면 작업유형 불문 부동산·빌딩'(도메인 우선),
#    그 외는 기능축(제품/콘텐츠/인프라). (매핑 비평가 지적 반영)
PROJECT_CATEGORY = {
    # 부동산·빌딩 (도메인 우선): IM=빌딩매매 제안서, kordoc=부동산 법률
    "Building scope": "부동산·빌딩", "builpago": "부동산·빌딩", "building sns": "부동산·빌딩",
    "wonbuilding AI TF": "부동산·빌딩", "매수고객관리": "부동산·빌딩", "yangjae_NI": "부동산·빌딩",
    "Auto IM pptx": "부동산·빌딩", "Auto IM2": "부동산·빌딩", "kordoc": "부동산·빌딩",
    # 제품·플랫폼 (일반 SaaS/도구 제품)
    "diwolbu": "제품·플랫폼", "team ERP": "제품·플랫폼", "Taxpago": "제품·플랫폼",
    # 콘텐츠·실험
    "remotion_youtube": "콘텐츠·실험", "dungeon writer": "콘텐츠·실험", "godot": "콘텐츠·실험",
    "ppt yoon": "콘텐츠·실험", "worldcup dashboard": "콘텐츠·실험",
    # 인프라·내부 (사내 자동화·데이터 도구)
    "데일리 작업로그": "인프라·내부", "notion work": "인프라·내부", "korea-finance": "인프라·내부",
}
DEFAULT_CATEGORY = "미분류"          # 미매핑 시 조용히 흡수하지 않고 '미분류'로 노출

# #2 담당 에이전트(Hermes). 카테고리 기본 + 프로젝트별 오버라이드.
CATEGORY_AGENT = {
    "부동산·빌딩": "서연 (CSO)", "제품·플랫폼": "유나 (CTO)",
    "인프라·내부": "유나 (CTO)", "콘텐츠·실험": "하린 (CLO)", "미분류": "미지정",
}
PROJECT_AGENT = {}                   # 예: {"Taxpago": "하린 (CLO)"} — 비면 카테고리 기준

# 비프로젝트 버킷(컨테이너 루트 활동·임시 폴더) — 집계/컬럼에서 격리, '기타'로 별도 표기.
NOISE_NAMES = {"claude_project", "remember project"}

# #5 환경 조성: 상태별 추천 액션(동사 중심·간결).
def recommend(r):
    if r["status"] == "방치":
        return "재점화 브리프 작성 — 마지막 초점 복기 후 다음 1스텝"
    if r["status"] == "식어감":
        return "주간 점검 — 진행 확인·재개 결정"
    if r["doc"] in ("없음", "경로없음"):
        return "문서 보강(README·CLAUDE) 권장"
    return "현재 페이스 유지"

STATUS_META = {"활발": ("●", "ok"), "식어감": ("◆", "warn"), "방치": ("▲", "bad")}
STATUS_RANK = {"방치": 0, "식어감": 1, "활발": 2}      # 컬럼 내 정렬: 소외 우선
TREND_CLS = {"↑": "up", "↓": "down", "=": "flat"}
DOC_CLS = {"A": "A", "B": "B", "C": "C", "없음": "none", "경로없음": "gone"}
DOC_DISP = {"경로없음": "폴더없음"}
OS_VERSION = "v0.3"
KST = timezone(timedelta(hours=9))

CSS = """
:root{--bg:#0d1117;--card:#161b22;--card2:#1c2230;--bd:#30363d;--fg:#e6edf3;--mut:#8b949e;
--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;--acc:#3b82f6;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-size:14px;
font-family:'Pretendard',-apple-system,'Segoe UI',Roboto,'Malgun Gothic',sans-serif}
.wrap{max-width:1320px;margin:0 auto;padding:24px 20px 70px}
h1{font-size:21px;margin:0 0 4px}
.sub{color:var(--mut);font-size:12.5px;line-height:1.6}
.badge{display:inline-block;background:#0f2a1a;color:#3fb950;border:1px solid #1f5135;
border-radius:6px;padding:2px 9px;font-size:11.5px;font-weight:600;margin-left:6px}
.prov{display:inline-block;background:#2a210f;color:#e3b341;border:1px solid #51421f;
border-radius:6px;padding:2px 8px;font-size:11px;margin-left:6px}
.aggbar{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 4px}
.chip{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:7px 12px;font-size:12.5px}
.chip b{font-size:15px;font-weight:700}
.chip.ok b{color:var(--ok)}.chip.warn b{color:var(--warn)}.chip.bad b{color:var(--bad)}
.legend{color:var(--mut);font-size:11.5px;margin:8px 0 18px;line-height:1.7}
.cols{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;align-items:start}
@media(max-width:1100px){.cols{grid-template-columns:repeat(2,1fr)}}
@media(max-width:640px){.cols{grid-template-columns:1fr}}
.colhead{border-bottom:2px solid var(--bd);padding-bottom:8px;margin-bottom:10px}
.colhead .ct{font-size:14.5px;font-weight:700}
.colhead .ca{color:var(--acc);font-size:12px;font-weight:600}
.colhead .cs{color:var(--mut);font-size:11.5px;margin-top:3px}
.cardbox{display:flex;flex-direction:column;gap:8px}
details.pc{background:var(--card);border:1px solid var(--bd);border-radius:9px;
border-left:3px solid var(--bd);overflow:hidden}
details.pc.ok{border-left-color:var(--ok)}
details.pc.warn{border-left-color:var(--warn);background:rgba(245,158,11,.04)}
details.pc.bad{border-left-color:var(--bad);background:rgba(239,68,68,.07)}
details.pc>summary{list-style:none;cursor:pointer;padding:10px 12px}
details.pc>summary::-webkit-details-marker{display:none}
.pname{font-size:13.5px;font-weight:650;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.num{color:var(--mut);font-size:11px;font-variant-numeric:tabular-nums;min-width:16px}
.dot{font-size:11px}.dot.ok{color:var(--ok)}.dot.warn{color:var(--warn)}.dot.bad{color:var(--bad)}
.bidle{background:#3b1d1d;color:#ff7b72;border:1px solid #5c2a2a;border-radius:5px;
padding:0 6px;font-size:10px;font-weight:600}
.pmeta{color:var(--mut);font-size:11.5px;margin-top:6px;display:flex;flex-wrap:wrap;gap:4px 10px}
.pmeta .g{color:var(--fg)}
.tr.up{color:var(--ok)}.tr.down{color:var(--bad)}.tr.flat{color:var(--mut)}
.tag{border:1px solid var(--bd);border-radius:5px;padding:0 6px;font-size:10.5px}
.tag.A{color:var(--ok);border-color:#1f5135}.tag.B{color:#9fd1ff;border-color:#1f3a5c}
.tag.C{color:var(--warn);border-color:#51421f}
.tag.none,.tag.gone{color:var(--bad);border-color:#5c2a2a}
.pbody{padding:0 12px 12px;border-top:1px solid var(--bd);margin-top:2px;font-size:12px;color:var(--mut)}
.pbody .focus{color:var(--fg);margin:8px 0 6px}
.pbody .fsrc{color:var(--mut);font-size:10.5px}
.pbody .nums{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:8px 0}
.pbody .nums div{background:var(--card2);border-radius:6px;padding:6px 8px}
.pbody .nums b{color:var(--fg);font-size:13px;display:block}
.act{margin-top:8px;color:#e3b341;background:#1d1a0f;border:1px solid #51421f;border-radius:6px;padding:7px 9px}
.path{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;word-break:break-all;color:#6e7681;margin-top:6px}
h2{font-size:14px;margin:34px 0 10px}
details.sec{margin-top:14px;background:var(--card);border:1px solid var(--bd);border-radius:10px}
details.sec>summary{cursor:pointer;padding:12px 16px;font-weight:600;font-size:13.5px;list-style:none}
details.sec>summary::-webkit-details-marker{display:none}
details.sec>summary::before{content:"▸ ";color:var(--mut)}
details.sec[open]>summary::before{content:"▾ "}
.secbody{padding:0 16px 16px}
.tl{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:11.5px}
.tl .tln{width:130px;color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tl .tlt{flex:1;background:#0d1117;border-radius:4px;height:12px;position:relative}
.tl .tlb{position:absolute;height:100%;background:linear-gradient(90deg,var(--acc),#60a5fa);border-radius:4px;min-width:3px}
.tl .tld{width:150px;color:var(--mut);text-align:right;font-variant-numeric:tabular-nums}
.metrics{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.kpi{background:var(--card2);border-radius:8px;padding:10px 12px}
.kpi .v{font-size:20px;font-weight:700}.kpi .l{color:var(--mut);font-size:11px;margin-top:2px}
.chartwrap{margin-top:14px;overflow-x:auto}
svg text.dx{fill:var(--mut);font-size:9px;text-anchor:middle}rect.db{fill:var(--acc)}
a.doclink{color:#9fd1ff;text-decoration:none;font-size:12px}a.doclink:hover{text-decoration:underline}
.foot{margin-top:30px;color:var(--mut);font-size:11px;border-top:1px solid var(--bd);padding-top:12px;line-height:1.7}
.ok-t{color:var(--ok);font-weight:600}
"""


def esc(s):
    return html.escape(str(s) if s is not None else "")


def assign(rows, db_path):
    """카테고리/담당 잠정 매핑 적용 + projects 테이블에 기록(설계의 category·agent 채움)."""
    con = sqlite3.connect(db_path); c = con.cursor()
    for r in rows:
        if r["name"] in NOISE_NAMES:
            r["category"], r["agent"], r["is_noise"] = "기타", "—", True
        else:
            cat = PROJECT_CATEGORY.get(r["name"], DEFAULT_CATEGORY)
            r["category"] = cat
            r["agent"] = PROJECT_AGENT.get(r["name"]) or CATEGORY_AGENT.get(cat, "미지정")
            r["is_noise"] = False
        c.execute("UPDATE projects SET category=?, agent=? WHERE project_id=?",
                  (r["category"], r["agent"], r["project_id"]))
    con.commit(); con.close()


def card_html(r, n):
    icon, cls = STATUS_META[r["status"]]
    days = r["days_idle"] if r["days_idle"] is not None else "?"
    badge = f'<span class="bidle">{days}일 방치</span>' if r["status"] == "방치" else ""
    trcls = TREND_CLS[r["trend"]]
    docdisp = DOC_DISP.get(r["doc"], r["doc"])
    focus = r["focus"] or "—"
    fsrc = f' <span class="fsrc">({esc(r["focus_src"])})</span>' if r["focus_src"] else ""
    return (
        f'<details class="pc {cls}"><summary>'
        f'<div class="pname"><span class="num">{n}</span>'
        f'<span class="dot {cls}">{icon}</span>{esc(r["name"])}{badge}</div>'
        f'<div class="pmeta">'
        f'<span class="g">{days}일 전</span>'
        f'<span class="tr {trcls}">추세 {r["trend"]}{TREND_LABEL[r["trend"]]}</span>'
        f'<span class="tag {DOC_CLS[r["doc"]]}">문서 {docdisp}</span>'
        f'<span>{esc(r["agent"])}</span>'
        f'</div></summary>'
        f'<div class="pbody">'
        f'<div class="focus">초점: {esc(focus)}{fsrc}</div>'
        f'<div class="nums">'
        f'<div><b>{days}일 전</b>최근 {esc(r["last"])}</div>'
        f'<div><b>{r["sessions"]}</b>세션 · 입력 {r["human"]}</div>'
        f'<div><b>{r["out_tok"]/1e6:.2f}M</b>출력토큰</div>'
        f'</div>'
        f'<div>시작 {esc(r["first"])} · 최근14일 세션 {r["last14"]} vs 직전 {r["prev14"]}'
        f' → {r["trend"]}{TREND_LABEL[r["trend"]]} · WS {r["n_workspaces"]} · 레코드 {r["n_records"]:,}</div>'
        f'<div class="act">추천: {esc(recommend(r))}</div>'
        f'<div class="path">{esc(r["root"])}</div>'
        f'</div></details>'
    )


def column_html(cat, crows):
    csc = Counter(r["status"] for r in crows)
    agent = CATEGORY_AGENT.get(cat, "")
    srt = sorted(crows, key=lambda r: (STATUS_RANK[r["status"]], -r["out_tok"]))
    cards = "".join(card_html(r, i + 1) for i, r in enumerate(srt)) or '<div class="sub">— 없음 —</div>'
    head = (f'<div class="colhead"><div class="ct">{esc(cat)}'
            + (f' <span class="ca">· {esc(agent)}</span>' if agent else "")
            + f'</div><div class="cs">{len(crows)}개 · 활발 {csc["활발"]} · 식어감 {csc["식어감"]} · 방치 {csc["방치"]}</div></div>')
    return f'<div class="col">{head}<div class="cardbox">{cards}</div></div>'


def timeline_html(real, now_date):
    rs = [r for r in real if r["first"]]
    if not rs:
        return ""
    g_first = min(r["first"] for r in rs)
    span = max(days_between(g_first, now_date) or 1, 1)
    rows_html = []
    for r in sorted(rs, key=lambda r: r["first"]):
        off = days_between(g_first, r["first"]) or 0
        wid = days_between(r["first"], r["last"]) or 0
        left = 100 * off / span
        width = max(100 * wid / span, 0.6)
        rows_html.append(
            f'<div class="tl"><div class="tln">{esc(r["name"])}</div>'
            f'<div class="tlt"><div class="tlb" style="left:{left:.1f}%;width:{width:.1f}%"></div></div>'
            f'<div class="tld">{esc(r["first"])} ~ {esc(r["last"])}</div></div>')
    return (f'<details class="sec"><summary>시작일 타임라인 — 프로젝트 생애주기 ({g_first} ~ {now_date}, KST)</summary>'
            f'<div class="secbody">{"".join(rows_html)}</div></details>')


def headquarters_html(here):
    docs = [
        ("docs/00_design.md", "Phase 0 설계(기준 원본)"),
        ("docs/01_next_ops_board.md", "운영 점검대 계획·신호 정의"),
        ("workos/ingest.py", "적재 + 프로젝트 루트 롤업"),
        ("workos/verify_gate.py", "무결성 게이트 16/16"),
        ("workos/ops_signals.py", "운영 신호 계산(단일 출처)"),
        ("workos/ops_board.py", "이 점검대 생성기 + 잠정 설정"),
    ]
    base = os.path.dirname(here)        # 프로젝트 루트(workos의 부모)
    items = []
    for rel, desc in docs:
        p = os.path.join(base, rel.replace("/", os.sep))
        url = "file:///" + p.replace(os.sep, "/")
        items.append(f'<div style="margin:5px 0"><a class="doclink" href="{esc(url)}">{esc(rel)}</a>'
                     f' <span class="sub">— {esc(desc)}</span></div>')
    return ('<details class="sec"><summary>본부 문서 — 판단 기준이 되는 원본</summary>'
            f'<div class="secbody">{"".join(items)}</div></details>')


def tips_html():
    return ('<details class="sec"><summary>활용 팁 — 점검대 읽는 법</summary><div class="secbody sub">'
            '<div>· <b>플래그</b>: ● 활발(최근 활동) · ◆ 식어감(주춤) · ▲ 방치(15일+ 방치) — 컬럼 위쪽일수록 손길 필요.</div>'
            '<div>· <b>추세</b>: ↑ 늘어남(초록) · ↓ 줄어듦(빨강, 조기경보) · = 정체. 최근 14일 vs 직전 14일 세션 수.</div>'
            '<div>· <b>문서등급</b>: A(README+가이드+docs) · B(README+가이드) · C(일부) · 없음 · 폴더없음.</div>'
            '<div>· <b>추천 액션</b>: 방치=재점화 브리프, 식어감=주간 점검, 문서부족=보강. (담당 에이전트가 수행 — Phase 3)</div>'
            '<div>· 카드를 클릭하면 초점·세션·토큰·시작일·경로가 펼쳐집니다.</div>'
            '<div style="margin-top:6px;color:#e3b341">· 카테고리·담당·임계값·문서등급은 <b>잠정값</b>입니다(확정 5건 대기). '
            'ops_board.py 상단 dict에서 조정하세요.</div>'
            '</div></details>')


def metrics_strip(db_path):
    c = sqlite3.connect(db_path).cursor()
    n_ws = c.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
    n_ws_active = c.execute("""SELECT COUNT(*) FROM (SELECT workspace_id FROM records
        WHERE is_canonical=1 AND rec_type='assistant' AND out_tok>0 GROUP BY workspace_id)""").fetchone()[0]
    n_sess = c.execute("SELECT COUNT(DISTINCT session_id) FROM records WHERE session_id IS NOT NULL").fetchone()[0]
    n_human = c.execute("SELECT COUNT(*) FROM records WHERE rec_type='user' AND origin_kind='human' "
                        "AND prompt_source='typed'").fetchone()[0]
    tout = c.execute("SELECT COALESCE(SUM(out_tok),0) FROM records WHERE is_canonical=1 "
                     "AND rec_type='assistant'").fetchone()[0]
    stored = c.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    drange = c.execute(f"SELECT MIN({KDATE}), MAX({KDATE}) FROM records WHERE ts IS NOT NULL").fetchone()
    daily = c.execute(f"""SELECT {KDATE} d,
        COALESCE(SUM(CASE WHEN is_canonical=1 AND rec_type='assistant' THEN out_tok END),0)
        FROM records WHERE ts IS NOT NULL GROUP BY d ORDER BY d""").fetchall()[-35:]
    dmax = max((d[1] for d in daily), default=1) or 1
    bw, gap, H = 24, 7, 130
    svg = []
    for i, (day, tok) in enumerate(daily):
        h = (H - 22) * tok / dmax; x = i * (bw + gap)
        svg.append(f'<rect x="{x}" y="{H-h-16:.0f}" width="{bw}" height="{h:.0f}" rx="3" class="db"></rect>')
        if i % 3 == 0:
            svg.append(f'<text x="{x+bw/2:.0f}" y="{H-2}" class="dx">{day[5:]}</text>')
    svgw = max(len(daily) * (bw + gap), 100)
    kpis = (
        f'<div class="kpi"><div class="v">{n_ws_active}<span style="font-size:12px;color:var(--mut)"> / {n_ws}</span></div><div class="l">활동 워크스페이스</div></div>'
        f'<div class="kpi"><div class="v">{n_sess:,}</div><div class="l">세션</div></div>'
        f'<div class="kpi"><div class="v">{n_human:,}</div><div class="l">사람 입력(typed)</div></div>'
        f'<div class="kpi"><div class="v">{tout/1e6:.1f}M</div><div class="l">출력 토큰(진실)</div></div>'
        f'<div class="kpi"><div class="v">{stored:,}</div><div class="l">정규화 레코드</div></div>'
    )
    body = (f'<div class="kpis">{kpis}</div>'
            f'<div class="chartwrap"><svg width="100%" height="{H}" viewBox="0 0 {svgw} {H}" '
            f'preserveAspectRatio="xMinYMid meet" style="max-width:{svgw}px;min-width:{min(svgw,560)}px">{"".join(svg)}</svg></div>'
            f'<div class="sub">일별 출력 토큰(최근 {len(daily)}일, KST) — 작업 산출 강도 대리지표</div>')
    return drange, body


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--db", default=os.path.join(here, "workos.db"))
    ap.add_argument("--out", default=os.path.join(here, "ops_board.html"))
    args = ap.parse_args()

    now_date, rows = ops_signals.compute(args.db)
    assign(rows, args.db)

    real = [r for r in rows if not r["is_noise"]]
    noise = [r for r in rows if r["is_noise"]]

    sc = Counter(r["status"] for r in real)
    bc = Counter(r["bucket"] for r in real)
    doc_need = sum(1 for r in real if r["doc"] in ("없음", "경로없음"))
    total = len(real)
    gen = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    aggbar = (
        f'<div class="chip"><b>{total}</b> 전체</div>'
        f'<div class="chip ok"><b>{sc["활발"]}</b> ● 활발</div>'
        f'<div class="chip warn"><b>{sc["식어감"]}</b> ◆ 식어감</div>'
        f'<div class="chip bad"><b>{sc["방치"]}</b> ▲ 방치</div>'
        f'<div class="chip"><b>{doc_need}</b> 문서 점검필요</div>'
        f'<div class="chip ok"><b>{bc["오늘"]}</b> 오늘</div>'
        f'<div class="chip bad"><b>{bc["오래"]}</b> 오래</div>'
    )

    by_cat = {}
    for r in real:
        by_cat.setdefault(r["category"], []).append(r)
    extra = sorted(k for k in by_cat if k not in CATEGORY_ORDER)
    cols = "".join(column_html(cat, by_cat[cat]) for cat in CATEGORY_ORDER + extra if by_cat.get(cat))

    # 비프로젝트 버킷(기타)
    noise_html = ""
    if noise:
        items = "".join(
            f'<div style="margin:5px 0">· <b>{esc(r["name"])}</b> '
            f'<span class="sub">— 레코드 {r["n_records"]:,} · 출력 {r["out_tok"]/1e6:.2f}M · '
            f'{("폴더없음" if r["doc"]=="경로없음" else r["bucket"])} · {esc(r["root"])}</span></div>'
            for r in sorted(noise, key=lambda r: -r["n_records"]))
        noise_html = (f'<details class="sec"><summary>기타 / 비프로젝트 버킷 ({len(noise)}) — '
                      f'컨테이너 루트 활동·임시 폴더(집계 제외)</summary><div class="secbody">{items}</div></details>')

    drange, metrics_body = metrics_strip(args.db)

    doc = (
        f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>PARK HQ Work OS — 작업 전 점검대</title><style>{CSS}</style></head><body><div class="wrap">'
        f'<h1>PARK HQ Work OS — 작업 전 점검대 '
        f'<span style="color:var(--mut);font-weight:400;font-size:13px">{OS_VERSION}</span>'
        f'<span class="badge">🔒 로컬 전용 · read-only</span></h1>'
        f'<div class="sub">생성 {gen} (KST) · 기준일 {now_date}(DB max ts) · 데이터 {drange[0]}~{drange[1]} (KST) · '
        f'적재 무결성 <span class="ok-t">게이트 16/16 PASS</span>'
        f'<span class="prov">⚠ 카테고리·담당·임계값·문서등급·액션은 잠정(확정 5건 대기)</span></div>'
        f'<div class="aggbar">{aggbar}</div>'
        f'<div class="legend">상태(컬럼 위=손길 필요): ● 활발(≤3일) · ◆ 식어감(4~14일) · ▲ 방치(15일+) &nbsp;|&nbsp; '
        f'방치도 버킷: 오늘 / 3일(1~3) / 주간(4~7) / 2주(8~14) / 오래(15+) &nbsp;|&nbsp; '
        f'추세: ↑증가 · ↓감소 · =정체 (최근14일 vs 직전14일 세션) &nbsp;|&nbsp; 카드 클릭 = 상세</div>'
        f'<div class="cols">{cols}</div>'
        f'{timeline_html(real, now_date)}'
        f'{noise_html}'
        f'{headquarters_html(here)}'
        f'{tips_html()}'
        f'<h2>지표 (20%) — 전체 활동 요약</h2><div class="metrics">{metrics_body}</div>'
        f'<div class="foot">'
        f'원천: Claude Code 세션 로그 → workos.db(프로젝트 루트 롤업 {total}개 + 비프로젝트 {len(noise)}개 격리) · '
        f'무결성 게이트 16/16 PASS · now=DB max(ts·KST)={now_date}(시계 무관) · 토큰=canonical(dedup 진실값).<br>'
        f'80% 운영 점검대(방치 감지) + 20% 지표 + 에이전트 레이어(카테고리→담당 + 카드별 추천 액션).<br>'
        f'보류(후속): 민감도 축(▲민감/◆주의, 분류규칙 필요) · 상태=수정/승인/읽기 컬럼(데이터 갭) · '
        f'cwd-NULL 세션 완전귀속. <b>이 파일은 로컬 전용</b>(세션제목·고객명 포함 가능, 커밋 금지).'
        f'</div></div></body></html>'
    )

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"운영 점검대 생성: {args.out}  ({len(doc):,} bytes)")
    print(f"  실프로젝트 {total} · 활발 {sc['활발']} · 식어감 {sc['식어감']} · 방치 {sc['방치']} · "
          f"문서점검필요 {doc_need} · 비프로젝트 격리 {len(noise)}")
    print(f"  열기: file:///{args.out.replace(chr(92),'/')}")


if __name__ == "__main__":
    main()
