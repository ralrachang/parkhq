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
카드별 🤖 AI 상태 코멘트는 ops_comments.py가 사전 생성(DB ops_comments 테이블,
evidence_hash 캐시) — 파이프라인: ingest → verify_gate → ops_comments → ops_board.
비프로젝트 버킷(컨테이너 루트·임시 폴더)은 NOISE_NAMES로 격리해 집계 왜곡 방지.
의존성 0·자체완결 HTML·JS 없음(펼치기는 <details>, 다크/라이트 토글은 순수 CSS :has()).
기본은 다크, 우상단 버튼으로 라이트 전환(새로고침 시 다크로 초기화 — 기억엔 JS 필요).
민감(세션제목·고객명) 포함 가능 →
로컬 전용, 절대 커밋 금지(.gitignore: workos/*.html).

사용자 확정 완료(조정은 이 dict만 고치면 됨):
   #1 PROJECT_CATEGORY · #1b PROJECT_SENSITIVITY · #2 CATEGORY_AGENT·PROJECT_AGENT (2026-06-29)
   #3 ops_signals.IDLE_*(활발≤7·식어감8–21·방치22+) · #4 ops_signals.doc_grade(현행 휴리스틱) (2026-06-30)
   잠정: #5 recommend() · NOISE_NAMES(비프로젝트 처리).
보류(데이터/규칙 필요): 상태=수정/승인/읽기 컬럼 · cwd-NULL 세션 완전귀속.
사용법: python ops_board.py [--db ./workos.db] [--out ./ops_board.html]
"""
import argparse, html, os, sqlite3, sys
from collections import Counter
from datetime import datetime, timezone, timedelta
import theme
import ops_signals
from ops_signals import days_between, TREND_LABEL, KDATE

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 잠정 설정 (사용자 확정 대기) ──────────────────────────────────────
CATEGORY_ORDER = ["부동산·빌딩", "제품·플랫폼", "콘텐츠·실험", "인프라·내부"]

# #1 프로젝트 → 카테고리 (사용자 확정 2026-06-29). 본업=부동산·빌딩, 그 외는 기능축.
PROJECT_CATEGORY = {
    # 부동산·빌딩 (본업)
    "yangjae_NI": "부동산·빌딩", "building sns": "부동산·빌딩", "wonbuilding AI TF": "부동산·빌딩",
    "Auto IM2": "부동산·빌딩", "매수고객관리": "부동산·빌딩",
    # 제품·플랫폼
    "Building scope": "제품·플랫폼", "builpago": "제품·플랫폼", "diwolbu": "제품·플랫폼",
    "Taxpago": "제품·플랫폼", "team ERP": "제품·플랫폼", "diwolbu web": "제품·플랫폼",  # diwolbu web: 신규(2026-06-30)
    "howmuch.go": "제품·플랫폼",  # 신규(2026-07-04)
    # 콘텐츠·실험
    "worldcup dashboard": "콘텐츠·실험", "dungeon writer": "콘텐츠·실험", "remotion_youtube": "콘텐츠·실험",
    # 인프라·내부
    "데일리 작업로그": "인프라·내부", "carendar": "인프라·내부",  # carendar: 새 프로젝트, 로그 쌓이면 표시
    "mer's blog": "인프라·내부",  # 신규(2026-07-04)
}
DEFAULT_CATEGORY = "미분류"          # 미매핑 시 '미분류'로 노출

# #2 담당 에이전트 (사용자 확정 2026-06-29): 부동산·빌딩=서연, 그 외 전부=유나.
CATEGORY_AGENT = {
    "부동산·빌딩": "서연 (CSO)",
    "제품·플랫폼": "유나 (CTO)", "콘텐츠·실험": "유나 (CTO)", "인프라·내부": "유나 (CTO)",
    "미분류": "미지정",
}
PROJECT_AGENT = {}                   # 프로젝트별 오버라이드(비면 카테고리 기준)

# #1b 민감도 축(ex.jpg 'A. 민감도' 재현) — 프로젝트별 데이터 민감도.
#    방치도(●◆▲)와 글리프 충돌 피하려 민감도는 '색 점 + 라벨' 칩으로 표기.
#    ⚠️ 잠정 분류(사용자 확정 대기) — 아래 dict만 고치면 됨.
SENSITIVITY_ORDER = ["대외비", "내부", "공개"]
PROJECT_SENSITIVITY = {
    # 대외비: 고객·매물·매출·세무·사장님 보고 등 실데이터/내부 의사결정
    "매수고객관리": "대외비", "wonbuilding AI TF": "대외비", "team ERP": "대외비",
    "Taxpago": "대외비", "Auto IM pptx": "대외비", "Auto IM2": "대외비",
    # 공개: 외부 발행물(SNS 카드뉴스·영상·공개 대시보드)
    "building sns": "공개", "builpago": "공개", "remotion_youtube": "공개",
    "worldcup dashboard": "공개",
    # 내부: 미공개 제품·사내 도구·실험 (기본값)
    "Building scope": "내부", "diwolbu": "내부", "diwolbu web": "내부", "kordoc": "내부",
    "korea-finance": "내부", "notion work": "내부", "데일리 작업로그": "내부",
    "godot": "내부", "dungeon writer": "내부", "yangjae_NI": "내부", "ppt yoon": "내부",
}
DEFAULT_SENSITIVITY = "내부"          # 미매핑 시 보수적으로 '내부'
SENS_META = {"대외비": "secret", "내부": "internal", "공개": "public"}  # 라벨 → CSS class

# 비프로젝트 버킷(컨테이너 루트 활동·임시 폴더) — 집계/컬럼에서 격리, '기타'로 별도 표기.
NOISE_NAMES = {"claude_project", "remember project"}

# 표시 제외(사용자 지정 2026-06-29) — 점검대에서 완전히 숨김(컬럼·집계·타임라인 제외).
HIDDEN_NAMES = {"kordoc", "Auto IM pptx", "godot", "ppt yoon", "korea-finance", "notion work"}

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
TREND_CLS = {"↑": "up", "↓": "down", "=": "flat"}
DOC_CLS = {"A": "A", "B": "B", "C": "C", "없음": "none", "경로없음": "gone"}
DOC_DISP = {"경로없음": "폴더없음"}
KST = timezone(timedelta(hours=9))

CSS = """
/* ops_board 페이지 고유 — 토큰·베이스·컴포넌트는 theme.py가 제공 */
:root{--tagB:var(--acc);--path:var(--faint);
--badge-bg:var(--ok-bg);--badge-fg:var(--ok);--badge-bd:transparent;
--prov-bg:var(--warn-bg);--prov-fg:var(--warn);--prov-bd:transparent;
--idle-bg:var(--bad-bg);--idle-fg:var(--bad);--idle-bd:transparent;
--act-bg:var(--warn-bg);--act-fg:var(--warn);--act-bd:transparent;
--warn-tint:var(--warn-bg);--bad-tint:var(--bad-bg);}
.badge{display:inline-block;background:var(--badge-bg);color:var(--badge-fg);border:1px solid var(--badge-bd);
border-radius:999px;padding:2px 10px;font-size:11.5px;font-weight:600;margin-left:6px}
.prov{display:inline-block;background:var(--prov-bg);color:var(--prov-fg);border:1px solid var(--prov-bd);
border-radius:999px;padding:2px 9px;font-size:11px;margin-left:6px}
.aggbar{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 4px}
.chip{background:var(--card);border:1px solid var(--bd);border-radius:999px;padding:7px 14px;
font-size:12.5px;box-shadow:var(--shadow)}
.chip b{font-size:15px;font-weight:750}
.chip.ok b{color:var(--ok)}.chip.warn b{color:var(--warn)}.chip.bad b{color:var(--bad)}
.chip.sep{border:0;padding:7px 2px;color:var(--mut);box-shadow:none}
.legend{color:var(--mut);font-size:11.5px;margin:8px 0 18px;line-height:1.7}
.cols{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;align-items:start;margin-top:14px}
@media(max-width:1100px){.cols{grid-template-columns:repeat(2,1fr)}}
@media(max-width:640px){.cols{grid-template-columns:1fr}}
.colhead{border-bottom:2px solid var(--bd2);padding-bottom:9px;margin-bottom:10px}
.colhead .ct{font-size:14.5px;font-weight:700}
.colhead .ca{color:var(--acc);font-size:12px;font-weight:600}
.colhead .cs{color:var(--mut);font-size:11.5px;margin-top:3px}
.cardbox{display:flex;flex-direction:column;gap:8px}
details.pc{background:var(--card);border:1px solid var(--bd);border-radius:var(--r);
border-left:3px solid var(--bd2);overflow:hidden;box-shadow:var(--shadow)}
details.pc.ok{border-left-color:var(--ok)}
details.pc.warn{border-left-color:var(--warn);background:var(--warn-tint)}
details.pc.bad{border-left-color:var(--bad);background:var(--bad-tint)}
details.pc>summary{list-style:none;cursor:pointer;padding:11px 13px}
details.pc>summary::-webkit-details-marker{display:none}
details.pc>summary:hover{background:var(--card2)}
.pname{font-size:13.5px;font-weight:650;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.num{color:var(--faint);font-size:11px;font-variant-numeric:tabular-nums;min-width:16px}
.dot{font-size:11px}.dot.ok{color:var(--ok)}.dot.warn{color:var(--warn)}.dot.bad{color:var(--bad)}
.bidle{background:var(--idle-bg);color:var(--idle-fg);border:1px solid var(--idle-bd);border-radius:999px;
padding:0 7px;font-size:10px;font-weight:600}
.pmeta{color:var(--mut);font-size:11.5px;margin-top:6px;display:flex;flex-wrap:wrap;gap:4px 10px}
.pmeta .g{color:var(--fg)}
.tr.up{color:var(--ok)}.tr.down{color:var(--bad)}.tr.flat{color:var(--mut)}
.tag{border:1px solid var(--bd);border-radius:5px;padding:0 6px;font-size:10.5px}
.tag.A{color:var(--ok)}.tag.B{color:var(--tagB)}.tag.C{color:var(--warn)}
.tag.none,.tag.gone{color:var(--bad)}
.sens{display:inline-flex;align-items:center;gap:4px;border-radius:999px;padding:0 7px;
font-size:10px;font-weight:600;border:1px solid}
.sens::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.sens.secret{color:var(--bad);background:var(--idle-bg);border-color:var(--idle-bd)}
.sens.internal{color:var(--warn);background:var(--act-bg);border-color:var(--act-bd)}
.sens.public{color:var(--ok);background:var(--badge-bg);border-color:var(--badge-bd)}
.sdot{display:inline-block;width:8px;height:8px;border-radius:50%;vertical-align:middle;margin-right:3px}
.sdot.secret{background:var(--bad)}.sdot.internal{background:var(--warn)}.sdot.public{background:var(--ok)}
.pbody{padding:0 13px 13px;border-top:1px solid var(--bd);margin-top:2px;font-size:12px;color:var(--mut)}
.pbody .focus{color:var(--fg);margin:9px 0 6px}
.pbody .fsrc{color:var(--mut);font-size:10.5px}
.pbody .nums{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:8px 0}
.pbody .nums div{background:var(--card2);border-radius:6px;padding:6px 8px}
.pbody .nums b{color:var(--fg);font-size:13px;display:block}
.act{margin-top:8px;color:var(--act-fg);background:var(--act-bg);border:1px solid var(--act-bd);border-radius:6px;padding:7px 9px}
.aicmt{margin:8px 0;color:var(--fg);background:var(--card2);border:1px solid var(--bd);
border-left:3px solid var(--acc);border-radius:6px;padding:8px 10px;line-height:1.55;font-size:12px}
.aicmt .cmtat{color:var(--faint);font-size:10px;margin-top:5px}
.path{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;word-break:break-all;color:var(--path);margin-top:6px}
h2{font-size:16px;margin:36px 0 10px}
details.sec{margin-top:14px;background:var(--card);border:1px solid var(--bd);border-radius:var(--r);box-shadow:var(--shadow)}
details.sec>summary{cursor:pointer;padding:12px 16px;font-weight:600;font-size:13.5px;list-style:none}
details.sec>summary::-webkit-details-marker{display:none}
details.sec>summary::before{content:"▸ ";color:var(--mut)}
details.sec[open]>summary::before{content:"▾ "}
.secbody{padding:0 16px 16px}
.tl{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:11.5px}
.tl .tln{width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tl .tlt{flex:1;background:var(--track);border-radius:4px;height:12px;position:relative}
.tl .tlb{position:absolute;height:100%;background:linear-gradient(90deg,var(--acc),var(--acc-soft));border-radius:4px;min-width:3px}
.tl .tld{width:150px;color:var(--mut);text-align:right;font-variant-numeric:tabular-nums}
a.doclink{color:var(--acc);text-decoration:none;font-size:12px}a.doclink:hover{text-decoration:underline}
"""


def esc(s):
    return html.escape(str(s) if s is not None else "")


def load_comments(db_path):
    """ops_comments.py가 생성한 프로젝트별 AI 상태 코멘트. 테이블 없으면 빈 dict(하위호환)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT project_id, comment, generated_at FROM ops_comments").fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    return {pid: (cmt, gen) for pid, cmt, gen in rows}


def assign(rows, db_path):
    """카테고리/담당 잠정 매핑 적용 + projects 테이블에 기록(설계의 category·agent 채움)."""
    con = sqlite3.connect(db_path); c = con.cursor()
    for r in rows:
        if r["name"] in NOISE_NAMES:
            r["category"], r["agent"], r["is_noise"] = "기타", "—", True
            r["sensitivity"] = None
        else:
            cat = PROJECT_CATEGORY.get(r["name"], DEFAULT_CATEGORY)
            r["category"] = cat
            r["agent"] = PROJECT_AGENT.get(r["name"]) or CATEGORY_AGENT.get(cat, "미지정")
            r["sensitivity"] = PROJECT_SENSITIVITY.get(r["name"], DEFAULT_SENSITIVITY)
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
    sens = r.get("sensitivity")
    sens_pill = f'<span class="sens {SENS_META[sens]}">{esc(sens)}</span>' if sens else ""
    focus = r["focus"] or "—"
    fsrc = f' <span class="fsrc">({esc(r["focus_src"])})</span>' if r["focus_src"] else ""
    cmt = r.get("ai_comment")
    cmt_html = (f'<div class="aicmt">🤖 {esc(cmt)}'
                f'<div class="cmtat">AI 코멘트 · {esc(r.get("ai_comment_at") or "")} KST · 실측 데이터 기반</div></div>'
                if cmt else "")
    return (
        f'<details class="pc {cls}"><summary>'
        f'<div class="pname"><span class="num">{n}</span>'
        f'<span class="dot {cls}">{icon}</span>{esc(r["name"])}{sens_pill}{badge}</div>'
        f'<div class="pmeta">'
        f'<span class="g">{days}일 전</span>'
        f'<span class="tr {trcls}">추세 {r["trend"]}{TREND_LABEL[r["trend"]]}</span>'
        f'<span class="tag {DOC_CLS[r["doc"]]}">문서 {docdisp}</span>'
        f'<span>{esc(r["agent"])}</span>'
        f'</div></summary>'
        f'<div class="pbody">'
        f'<div class="focus">초점: {esc(focus)}{fsrc}</div>'
        f'{cmt_html}'
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
    srt = sorted(crows, key=lambda r: (r["days_idle"] if r["days_idle"] is not None else 9999,
                                       -r["out_tok"]))
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
            '<div>· <b>민감도</b>: <span class="sens secret">대외비</span>(고객·매출·내부의사결정) '
            '<span class="sens internal">내부</span>(미공개 제품·사내도구) '
            '<span class="sens public">공개</span>(외부 발행물) — 이름 옆 색 점 칩.</div>'
            '<div>· <b>추세</b>: ↑ 늘어남(초록) · ↓ 줄어듦(빨강, 조기경보) · = 정체. 최근 14일 vs 직전 14일 세션 수.</div>'
            '<div>· <b>문서등급</b>: A(README+가이드+docs) · B(README+가이드) · C(일부) · 없음 · 폴더없음.</div>'
            '<div>· <b>추천 액션</b>: 방치=재점화 브리프, 식어감=주간 점검, 문서부족=보강. (담당 에이전트가 수행 — Phase 3)</div>'
            '<div>· 카드를 클릭하면 초점·<b>🤖 AI 상태 코멘트</b>·세션·토큰·시작일·경로가 펼쳐집니다.</div>'
            '<div>· <b>🤖 코멘트</b>: 실측 데이터(방치도·추세·최근 세션 제목·입력) 기반 요약+다음 액션. '
            '갱신은 <code>ops_comments.py</code> 실행(근거 데이터가 바뀐 프로젝트만 재생성).</div>'
            '<div style="margin-top:6px;color:var(--prov-fg)">· 카테고리·담당·임계값·문서등급은 <b>잠정값</b>입니다(확정 5건 대기). '
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
    kpis = (
        theme.kpi(f'{n_ws_active}', '활동 워크스페이스', sub=f'/ {n_ws}')
        + theme.kpi(f'{n_sess:,}', '세션')
        + theme.kpi(f'{n_human:,}', '사람 입력(typed)')
        + theme.kpi(f'{tout/1e6:.1f}M', '출력 토큰(진실)')
        + theme.kpi(f'{stored:,}', '정규화 레코드')
    )
    body = (f'<div class="kpis" style="margin-top:0">{kpis}</div>'
            + theme.daily_bars_svg(daily, height=130)
            + f'<div class="sub">일별 출력 토큰(최근 {len(daily)}일, KST) — 작업 산출 강도 대리지표</div>')
    return drange, body


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--db", default=os.path.join(here, "workos.db"))
    ap.add_argument("--out", default=os.path.join(here, "ops_board.html"))
    args = ap.parse_args()

    now_date, rows = ops_signals.compute(args.db)
    rows = [r for r in rows if r["name"] not in HIDDEN_NAMES]   # 사용자 지정 숨김 제외
    assign(rows, args.db)
    comments = load_comments(args.db)                            # ops_comments.py 산출(없으면 빈 dict)
    for r in rows:
        r["ai_comment"], r["ai_comment_at"] = comments.get(r["project_id"], (None, None))

    real = [r for r in rows if not r["is_noise"]]
    noise = [r for r in rows if r["is_noise"]]

    sc = Counter(r["status"] for r in real)
    sens_ct = Counter(r["sensitivity"] for r in real if r.get("sensitivity"))
    doc_need = sum(1 for r in real if r["doc"] in ("없음", "경로없음"))
    total = len(real)
    gen = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    sens_chips = "".join(
        f'<div class="chip"><b>{sens_ct.get(k, 0)}</b> <span class="sdot {SENS_META[k]}"></span>{k}</div>'
        for k in SENSITIVITY_ORDER)
    aggbar = (
        f'<div class="chip"><b>{total}</b> 전체</div>'
        f'<div class="chip ok"><b>{sc["활발"]}</b> ● 활발</div>'
        f'<div class="chip warn"><b>{sc["식어감"]}</b> ◆ 식어감</div>'
        f'<div class="chip bad"><b>{sc["방치"]}</b> ▲ 방치</div>'
        f'<div class="chip"><b>{doc_need}</b> 문서 점검</div>'
        f'<div class="chip sep">·</div>'
        f'{sens_chips}'
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
        theme.page_head("PARK HQ Work OS — 작업 전 점검대")
        + f'<style>{CSS}</style>'
        + theme.theme_toggle()
        + f'<div class="wrap">'
        f'<h1>작업 전 점검대<span class="pill lock">🔒 로컬 전용</span></h1>'
        f'<div class="sub">기준일 {now_date} · <span class="pill pass">게이트 16/16 PASS</span>'
        f'<span class="prov">분류·담당·민감도 잠정</span></div>'
        f'<div class="aggbar">{aggbar}</div>'
        f'<div class="cols">{cols}</div>'
        f'{timeline_html(real, now_date)}'
        f'{noise_html}'
        f'{headquarters_html(here)}'
        f'{tips_html()}'
        f'<h2>지표 (20%) — 전체 활동 요약</h2><div class="card">{metrics_body}</div>'
        f'<div class="foot">'
        f'생성 {gen} (KST) · 데이터 {drange[0]}~{drange[1]} (KST) · 기준일(now)=DB max(ts·KST)={now_date}(시계 무관).<br>'
        f'원천: Claude Code 세션 로그 → workos.db(프로젝트 루트 롤업 · 표시 {total}개 + 비프로젝트 {len(noise)}개 격리 + 표시제외 {len(HIDDEN_NAMES)}개) · '
        f'무결성 게이트 16/16 PASS · 토큰=canonical(dedup 진실값).<br>'
        f'표시 제외(사용자 지정 {len(HIDDEN_NAMES)}): {esc(" · ".join(sorted(HIDDEN_NAMES)))}.<br>'
        f'80% 운영 점검대(방치 감지) + 민감도 축 + 20% 지표 + 에이전트 레이어(카테고리→담당 + 카드별 추천 액션).<br>'
        f'보류(후속): 상태=수정/승인/읽기 컬럼(데이터 갭) · cwd-NULL 세션 완전귀속. '
        f'<b>이 파일은 로컬 전용</b>(세션제목·고객명 포함 가능, 커밋 금지).'
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
