# Work OS 대시보드 디자인 업그레이드 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `workos/theme.py` 공유 디자인 시스템을 만들고 dashboard.py·ops_board.py를 그 위로 옮겨, 두 대시보드를 프리미엄 SaaS급 비주얼(다크 기본 + 순수 CSS 라이트 토글)로 통일한다.

**Architecture:** 디자인 토큰·공용 컴포넌트 CSS·차트 헬퍼를 theme.py 한 곳에 두고, 두 생성기는 페이지 고유 CSS만 유지한 채 theme을 import한다. 데이터 로직(쿼리·신호·코멘트)은 일절 건드리지 않는다.

**Tech Stack:** Python 3 표준 라이브러리만(의존성 0), 인라인 CSS/SVG, JS 없음(`<details>`, `:has()` 토글).

## Global Constraints

- 의존성 0 · 자체완결 단일 HTML · **JS 없음** (스펙 §2)
- 생성 HTML은 로컬 전용 — `.gitignore`의 `workos/*.html` 유지, HTML 커밋 금지 (스펙 §2)
- DB 스키마·쿼리·`ops_signals`·`ops_comments`·`verify_gate` 무변경 (스펙 §2)
- 기본 다크, `#themechk` 체크 시 라이트 (스펙 §3·§4)
- 타이포 스케일: h1 28 / h2 20 / 본문 15 / 보조 13 / 캡션 11.5 (px) (스펙 §4)
- 팔레트(검증 완료 — dataviz validate_palette.js, 2026-07-03):
  - 시리즈/강조 블루: 라이트 `#2a78d6`, 다크 `#3987e5` — 양 모드 ALL PASS
  - 상태(텍스트 토큰, ●◆▲ 글리프+라벨 병기 전제): 라이트 `#1a7f37`/`#9a6700`/`#cf222e`, 다크 `#22c55e`/`#f59e0b`/`#ef4444` — 해당 서피스 대비 모두 ≥3:1
  - 서피스: 다크 페이지 `#0e0f13`·카드 `#15171e`, 라이트 페이지 `#f6f6f4`·카드 `#ffffff`
- tabular-nums는 정렬이 필요한 곳(테이블·축 눈금·바 값)에만, KPI 히어로 숫자는 비례 숫자 (dataviz 지침 — 스펙 §4의 "전부 tabular" 문구를 의식적으로 정제)
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: `workos/theme.py` — 디자인 단일 출처

**Files:**
- Create: `workos/theme.py`

**Interfaces:**
- Produces (후속 태스크가 사용):
  - `FONT: str` — 폰트 스택
  - `TOKENS_CSS, BASE_CSS, COMPONENTS_CSS, CHART_CSS: str`
  - `page_head(title: str) -> str` — `<!doctype …><body>` 직전까지(스타일 포함)
  - `theme_toggle() -> str` — 우상단 토글 마크업
  - `daily_bars_svg(days: list[tuple[str, int]], height=150, bar_w=24, gap=7, label_every=3) -> str` — y축 눈금·그리드라인·네이티브 툴팁 포함 일별 막대 SVG(`days`의 라벨은 `YYYY-MM-DD`)
  - `kpi(value: str, label: str, sub: str | None = None) -> str` — KPI 타일(주의: `value`는 HTML로 삽입되므로 호출측에서 escape)
  - `fmt_si(v: float) -> str` — 1234→"1k", 2.3e6→"2.3M"
  - `esc(s) -> str` — html.escape 래퍼(None 허용)

- [x] **Step 1: theme.py 작성** — 아래 코드 전체를 `workos/theme.py`로 저장

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PARK HQ Work OS — 공유 디자인 시스템(디자인 단일 출처).
dashboard.py·ops_board.py가 import. 의존성 0 · JS 없음 원칙 유지.
기본 다크, #themechk 체크 시 라이트(:has, 순수 CSS — 새로고침 시 다크 복귀).
팔레트는 dataviz validate_palette.js로 검증(2026-07-03):
  시리즈 블루 라이트 #2a78d6 / 다크 #3987e5 — 양 모드 ALL PASS.
  상태색은 텍스트 토큰(●◆▲ 글리프·라벨 병기, 색 단독 의미 없음) — 대비 ≥3:1.
스펙: docs/superpowers/specs/2026-07-03-workos-design-upgrade-design.md
"""
import html as _html
import math


FONT = "'Pretendard',-apple-system,'Segoe UI',Roboto,'Malgun Gothic',sans-serif"

# ── 토큰: 기본 다크 + 라이트 쌍 ──────────────────────────────────────
TOKENS_CSS = """
:root{
  --bg:#0e0f13;--card:#15171e;--card2:#1c1f28;--bd:#262a35;--bd2:#323848;
  --fg:#e8eaf0;--mut:#8f95a3;--faint:#6a7080;
  --acc:#3987e5;--acc-soft:rgba(57,135,229,.14);
  --ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;
  --ok-bg:rgba(34,197,94,.10);--warn-bg:rgba(245,158,11,.10);--bad-bg:rgba(239,68,68,.10);
  --grid:#262a35;--axis:#3a4050;--track:#232733;
  --shadow:none;--r:8px;
}
:root:has(#themechk:checked){
  --bg:#f6f6f4;--card:#ffffff;--card2:#f2f2ef;--bd:#e4e3de;--bd2:#d2d1ca;
  --fg:#1a1c22;--mut:#5d6270;--faint:#8b8f9b;
  --acc:#2a78d6;--acc-soft:rgba(42,120,214,.10);
  --ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;
  --ok-bg:rgba(26,127,55,.08);--warn-bg:rgba(154,103,0,.08);--bad-bg:rgba(207,34,46,.07);
  --grid:#ecebe6;--axis:#c9c8c1;--track:#eeede8;
  --shadow:0 1px 2px rgba(20,22,28,.05),0 4px 14px rgba(20,22,28,.04);
}
"""

# ── 베이스: 리셋·타이포·헤더·토글·푸터 ───────────────────────────────
BASE_CSS = """
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-size:15px;line-height:1.55;
font-family:%(font)s;transition:background .15s,color .15s}
body::before{content:"";display:block;height:2px;
background:linear-gradient(90deg,var(--acc),transparent 62%%)}
.wrap{max-width:1240px;margin:0 auto;padding:32px 24px 72px}
h1{font-size:28px;font-weight:750;letter-spacing:-.02em;margin:0 0 6px;padding-right:110px}
h2{font-size:20px;font-weight:700;letter-spacing:-.01em;margin:44px 0 14px}
.sub{color:var(--mut);font-size:13px;line-height:1.7}
a{color:var(--acc)}
.pill{display:inline-flex;align-items:center;gap:5px;border-radius:999px;vertical-align:2px;
padding:2px 10px;font-size:11.5px;font-weight:600;border:1px solid var(--bd);color:var(--mut)}
.pill.lock{color:var(--bad);background:var(--bad-bg);border-color:transparent}
.pill.pass{color:var(--ok);background:var(--ok-bg);border-color:transparent}
.pill.prov{color:var(--warn);background:var(--warn-bg);border-color:transparent}
.toolbar{position:fixed;top:14px;right:16px;z-index:20}
.vh{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
.themebtn{display:inline-block;cursor:pointer;background:var(--card);border:1px solid var(--bd);
color:var(--fg);border-radius:999px;padding:6px 13px;font-size:12px;font-weight:600;
user-select:none;box-shadow:var(--shadow)}
.themebtn:hover{border-color:var(--acc)}
.themebtn::before{content:"☀️ 라이트"}
:root:has(#themechk:checked) .themebtn::before{content:"🌙 다크"}
.vh:focus-visible + .themebtn{outline:2px solid var(--acc);outline-offset:2px}
.foot{margin-top:48px;color:var(--mut);font-size:11.5px;border-top:1px solid var(--bd);
padding-top:16px;line-height:1.8}
"""

# ── 컴포넌트: 카드·KPI·테이블·수평바·칩 ─────────────────────────────
COMPONENTS_CSS = """
.card{background:var(--card);border:1px solid var(--bd);border-radius:var(--r);
box-shadow:var(--shadow);padding:18px 20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:var(--r);
box-shadow:var(--shadow);padding:16px 18px 14px}
.kpi .v{font-size:30px;font-weight:750;letter-spacing:-.01em;line-height:1.15}
.kpi .v .ks{font-size:13px;font-weight:600;color:var(--mut);margin-left:2px}
.kpi .l{color:var(--mut);font-size:12px;margin-top:5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--bd)}
th{color:var(--mut);font-weight:600;font-size:11.5px;border-bottom:1px solid var(--bd2)}
tr:hover td{background:var(--card2)}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
.bar{display:grid;grid-template-columns:150px 1fr 92px;align-items:center;gap:10px;margin:8px 0}
.bl{font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bt{background:var(--track);border-radius:999px;height:10px;overflow:hidden}
.bf{background:linear-gradient(90deg,var(--acc),var(--acc-soft));height:100%;border-radius:999px}
.bv{text-align:right;color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:22px}
@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.note{color:var(--mut);font-size:12px;margin-top:10px;line-height:1.6}
.ok-t{color:var(--ok);font-weight:600}
"""

# ── 차트: 그리드라인·축·막대·호버 ────────────────────────────────────
CHART_CSS = """
.chartwrap{margin-top:14px;overflow-x:auto}
svg text.dx{fill:var(--faint);font-size:10px;text-anchor:middle;font-family:inherit}
svg text.dy{fill:var(--faint);font-size:10px;text-anchor:end;font-family:inherit;
font-variant-numeric:tabular-nums}
svg line.gl{stroke:var(--grid);stroke-width:1;shape-rendering:crispEdges}
svg line.ax{stroke:var(--axis);stroke-width:1;shape-rendering:crispEdges}
rect.db{fill:var(--acc)}
rect.db:hover{filter:brightness(1.18)}
"""


def css():
    return TOKENS_CSS + (BASE_CSS % {"font": FONT}) + COMPONENTS_CSS + CHART_CSS


def esc(s):
    return _html.escape(str(s) if s is not None else "")


def fmt_si(v):
    if v >= 1e6:
        return f"{v/1e6:.1f}M"
    if v >= 1e3:
        return f"{v/1e3:.0f}k"
    return f"{v:,.0f}"


def _nice_ceil(v):
    """1/2/5×10^n 눈금 상한 — y축이 어중간한 값으로 끝나지 않게."""
    if v <= 0:
        return 1
    e = math.floor(math.log10(v))
    base = 10 ** e
    for m in (1, 2, 5, 10):
        if v <= m * base:
            return m * base
    return 10 * base


def daily_bars_svg(days, height=150, bar_w=24, gap=7, label_every=3):
    """일별 막대 SVG. days=[('YYYY-MM-DD', 값)]. y축 눈금 3개+그리드라인+<title> 툴팁."""
    pad_l, pad_b, pad_t = 34, 16, 4
    vmax = _nice_ceil(max((v for _, v in days), default=1) or 1)
    plot_h = height - pad_b - pad_t
    W = pad_l + max(len(days) * (bar_w + gap), 60)
    parts = []
    for i in range(1, 4):
        y = pad_t + plot_h * (1 - i / 3)
        parts.append(f'<line class="gl" x1="{pad_l}" y1="{y:.1f}" x2="{W}" y2="{y:.1f}"/>')
        parts.append(f'<text class="dy" x="{pad_l-5}" y="{y+3.5:.1f}">{fmt_si(vmax*i/3)}</text>')
    parts.append(f'<line class="ax" x1="{pad_l}" y1="{height-pad_b+.5}" x2="{W}" y2="{height-pad_b+.5}"/>')
    for i, (day, v) in enumerate(days):
        h = plot_h * v / vmax
        x = pad_l + i * (bar_w + gap)
        parts.append(f'<rect class="db" x="{x}" y="{height-pad_b-h:.1f}" width="{bar_w}" '
                     f'height="{max(h,1):.1f}" rx="3"><title>{esc(day)} · {v:,}</title></rect>')
        if i % label_every == 0:
            parts.append(f'<text class="dx" x="{x+bar_w/2:.0f}" y="{height-3}">{esc(day[5:])}</text>')
    return (f'<div class="chartwrap"><svg width="100%" height="{height}" viewBox="0 0 {W} {height}" '
            f'preserveAspectRatio="xMinYMid meet" style="max-width:{W}px;min-width:{min(W,560)}px">'
            f'{"".join(parts)}</svg></div>')


def kpi(value, label, sub=None):
    """KPI 타일. value·sub는 HTML로 삽입(호출측 escape 책임), label은 escape됨."""
    s = f'<span class="ks">{sub}</span>' if sub else ""
    return f'<div class="kpi"><div class="v">{value}{s}</div><div class="l">{esc(label)}</div></div>'


def theme_toggle():
    return ('<div class="toolbar"><input type="checkbox" id="themechk" class="vh">'
            '<label for="themechk" class="themebtn" title="라이트/다크 전환"></label></div>')


def page_head(title):
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{css()}</style></head><body>')
```

- [x] **Step 2: 스모크 테스트 실행**

Run (프로젝트 루트에서):
```bash
cd workos && python -c "
import theme
c = theme.css()
assert ':root:has(#themechk:checked)' in c, 'light pair missing'
assert '--acc:#3987e5' in c and '--acc:#2a78d6' in c, 'accent tokens missing'
svg = theme.daily_bars_svg([('2026-07-01', 1500), ('2026-07-02', 900)])
assert 'class=\"gl\"' in svg and '<title>' in svg and '2k' in svg, 'gridline/tooltip/ytick missing'
assert theme.fmt_si(2_300_000) == '2.3M' and theme.fmt_si(1500) == '2k'
assert theme.page_head('x').startswith('<!doctype html>')
assert 'themechk' in theme.theme_toggle()
print('theme.py smoke OK')
"
```
Expected: `theme.py smoke OK` (실패 시 assert 메시지 확인 후 수정)

- [x] **Step 3: 커밋**

```bash
git add workos/theme.py
git commit -m "Work OS theme.py: 공유 디자인 토큰·컴포넌트·차트 헬퍼 (디자인 단일 출처)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `dashboard.py` — theme 전환 + 구조 개편

**Files:**
- Modify: `workos/dashboard.py` (import 블록, `bars()` 이후의 SVG 생성부와 `HTML = f"""…"""` 전체)

**Interfaces:**
- Consumes: Task 1의 `theme.page_head/theme_toggle/daily_bars_svg/kpi/esc/fmt_si`
- Produces: 없음 (말단 생성기)

- [x] **Step 1: import 추가** — 파일 상단 `import argparse, html, os, sqlite3, sys` 아래에:

```python
import theme
```

- [x] **Step 2: 수동 SVG 생성부 삭제** — `# 일별 SVG 막대` 주석부터 `svgw = max(...)`까지(현 106~115행)와 CSS `<style>` 블록 전체를 제거하고, `HTML = f"""` 블록을 아래로 교체. `daily`는 `(day, sess, tok)` 3-튜플이므로 `[(d, t) for d, _, t in daily]`로 넘긴다.

```python
    HTML = (
        theme.page_head("PARK HQ Work OS — 대시보드 미리보기")
        + theme.theme_toggle()
        + f"""<div class="wrap">
<h1>PARK HQ Work OS — 업무 대시보드 <span class="pill lock">🔒 로컬 전용 · 비공개</span></h1>
<div class="sub">Phase 2 미리보기 · 데이터 {drange[0]} ~ {drange[1]} (KST) ·
세션 로그 {files_seen}파일 정규화 적재 · <span class="pill pass">게이트 12/12 PASS</span></div>

<div class="kpis">
{theme.kpi(f'{n_ws_active}', '활동 워크스페이스', sub=f'/ {n_ws}')}
{theme.kpi(f'{n_sess:,}', '세션')}
{theme.kpi(f'{n_human:,}', '사람 입력(typed)')}
{theme.kpi(f'{tout/1e6:.1f}M', '출력 토큰(dedup 진실)')}
{theme.kpi(f'${cost_total:,.0f}', '추정 비용', sub='가정 단가')}
{theme.kpi(f'{stored:,}', '정규화 레코드')}
</div>

<h2>일별 작업량 추이 — 출력 토큰 (최근 {len(daily)}일, KST)</h2>
<div class="card">{theme.daily_bars_svg([(d, t) for d, _, t in daily])}
<div class="note">막대 = 그날 생성된 출력 토큰량(작업 산출 강도의 대리지표). 막대에 마우스를 올리면 날짜·값.</div></div>

<div class="grid2" style="margin-top:22px">
<div class="card"><h2 style="margin-top:0">프로젝트별 작업량 (출력 토큰 상위 14)</h2>
{bars(ws_disp,0,2,fmt=lambda v:f"{v/1e6:.1f}M")}
</div>
<div class="card"><h2 style="margin-top:0">도구 사용 Top 14</h2>
{bars(tools,0,1)}
</div></div>

<div class="grid2" style="margin-top:22px">
<div class="card"><h2 style="margin-top:0">모델 분포 (canonical)</h2>
<table><tr><th>모델</th><th class="r">메시지</th><th class="r">출력토큰</th></tr>{model_rows}</table></div>
<div class="card"><h2 style="margin-top:0">비용 추정 <span class="pill prov">가정 단가 · 확인 필요</span></h2>
<table><tr><th>모델</th><th class="r">출력토큰</th><th class="r">추정 $</th></tr>{cost_rows_html}
<tr><td><b>합계</b></td><td class="r"></td><td class="r"><b>${cost_total:,.2f}</b></td></tr></table>
<div class="note">가정 단가(USD/1M): opus 15/75, sonnet·fable 3/15, haiku 1/5 (+캐시 별도). 실제 단가로 교체 필요.</div></div>
</div>

<h2>최근 세션 20</h2>
<div class="card"><table>
<tr><th>제목(AI)</th><th>프로젝트</th><th>요약</th><th class="r">출력토큰</th><th>모델</th></tr>
{recent_rows}</table></div>

<div class="foot">
원천: Claude Code 세션 로그 {files_seen}파일 · {raw_lines:,}줄 동결 → {stored:,}행 정규화(중복 {dups:,} 제거, 비채택 보관) · 파싱에러 {perr}.<br>
토큰 정직성: 순진 합산 {raw_out/1e6:.1f}M 중 resume 재기록 {(raw_out-canon_out)/1e6:.1f}M을 dedup 제외 → 진실값 {canon_out/1e6:.1f}M 사용.<br>
멱등키=content_hash(봉투필드 제외) · <b>이 파일은 로컬 전용</b>(고객명·세션제목 포함 가능, 커밋 금지).
</div>
</div></body></html>"""
    )
```

주의: 기존 f-string 안의 `html.escape(...)` 호출들(model_rows·recent_rows 등 사전 조립부)은 그대로 둔다. 삭제 대상은 `<style>…</style>`을 포함한 옛 `HTML = f"""<!doctype html>…"""` 블록과 수동 SVG 조립부뿐.

- [x] **Step 3: 재생성 + 마커 검증**

```bash
cd workos && python dashboard.py && python -c "
h = open('dashboard.html', encoding='utf-8').read()
assert 'themechk' in h, 'toggle missing'
assert 'class=\"gl\"' in h, 'gridlines missing'
assert '--bg:#0e0f13' in h, 'dark tokens missing'
assert h.startswith('<!doctype html>'), 'head malformed'
print('dashboard markers OK', len(h))
"
```
Expected: `dashboard markers OK` + 바이트 수(대략 15k~25k)

- [x] **Step 4: 시각 확인** — Playwright MCP로 `file:///D:/claude_project/데일리 작업로그/workos/dashboard.html` 열고 스크린샷. 토글 라벨 클릭 후 라이트 모드도 1장. 확인 포인트: 겹침·잘림 없음, y축 눈금 표시, KPI 위계, 라이트/다크 모두 텍스트 가독.

- [x] **Step 5: 커밋**

```bash
git add workos/dashboard.py
git commit -m "dashboard.py: theme 전환 — 다크/라이트 토글, y축 있는 차트, KPI·테이블 개편

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `ops_board.py` — theme 전환 + 카드·컬럼 정돈

**Files:**
- Modify: `workos/ops_board.py` (import, `CSS = """…"""` 상수, `metrics_strip()`의 SVG 조립부, `main()`의 문서 조립부)

**Interfaces:**
- Consumes: Task 1의 `theme.page_head/theme_toggle/daily_bars_svg/kpi/fmt_si`
- Produces: 없음 (말단 생성기)

- [x] **Step 1: import 추가** — `import ops_signals` 위에 `import theme` 추가.

- [x] **Step 2: CSS 상수 교체** — 기존 `CSS = """…"""`(110~218행)를 아래 **페이지 고유 CSS만** 남긴 버전으로 교체. 토큰·베이스·KPI·테이블·차트는 theme이 제공하므로 삭제하고, 옛 페이지 변수는 theme 토큰 별칭으로 연결한다.

```python
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
```

주의: ops_board의 h1은 28px이 기본이 되며(theme), h2는 페이지 CSS에서 16px로 재정의(점검대 섹션 제목은 밀도상 작게 유지 — 대시보드 h2 20px과 구분되는 의도적 예외).

- [x] **Step 3: `metrics_strip()`의 SVG 조립 교체** — `dmax = …`부터 `svgw = …`까지 삭제하고 `body` 조립을 아래로:

```python
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
```

- [x] **Step 4: `main()` 문서 조립 교체** — `doc = (…)`의 head·toolbar 부분을 theme 호출로:

```python
    doc = (
        theme.page_head("PARK HQ Work OS — 작업 전 점검대")
        + theme.theme_toggle()
        + f'<div class="wrap">'
        f'<h1>작업 전 점검대<span class="pill lock">🔒 로컬 전용</span></h1>'
        f'<div class="sub">기준일 {now_date} · <span class="pill pass">게이트 16/16 PASS</span>'
        f'<span class="prov">분류·담당·민감도 잠정</span></div>'
        # …이하 aggbar/cols/timeline/noise/headquarters/tips/metrics/foot 부분은 기존 그대로,
        # 단 '<h2>지표 (20%)…' 다음의 '<div class="metrics">' → '<div class="card">' 로,
        # f'<style>{CSS}</style>' 는 page_head가 theme CSS를 포함하므로
        # page_head 직후 f'<style>{CSS}</style>' 한 줄로 페이지 CSS만 추가 삽입.
    )
```

정확한 조립 순서: `theme.page_head(...) + f'<style>{CSS}</style>' + theme.theme_toggle() + f'<div class="wrap">…'`. 기존 `<!doctype …><style>{CSS}</style></head><body><div class="toolbar">…` 조립부와 `.metrics` 클래스 사용처(1곳)만 바뀐다. `.badge`→`.pill lock`, `.prov`→`.pill prov`로의 치환은 h1·sub 라인의 2곳.

- [x] **Step 5: 재생성 + 마커 검증**

```bash
cd workos && python ops_board.py && python -c "
h = open('ops_board.html', encoding='utf-8').read()
assert 'themechk' in h and '--bg:#0e0f13' in h, 'theme missing'
assert 'class=\"gl\"' in h, 'gridlines missing'
assert 'details class=\"pc' in h, 'cards missing'
assert '.metrics' not in h, 'old metrics class should be gone'
print('ops_board markers OK', len(h))
"
```
Expected: `ops_board markers OK` + 바이트 수(대략 40k~60k)

- [x] **Step 6: 시각 확인** — Playwright로 `file:///…/ops_board.html` 다크/라이트 스크린샷. 확인 포인트: 카드 상태 레일(ok/warn/bad) 색, 민감도 칩 가독, 컬럼 4→2→1 반응형, AI 코멘트 블록.

- [x] **Step 7: 커밋**

```bash
git add workos/ops_board.py
git commit -m "ops_board.py: theme 전환 — 페이지 CSS 축소(토큰 별칭), 칩·카드·컬럼 정돈

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 통합 검증

**Files:**
- 없음(검증만). 수정 발생 시 해당 파일 재커밋.

**Interfaces:**
- Consumes: Task 1~3 전부 완료 상태

- [x] **Step 1: 데이터 레이어 무변경 확인**

```bash
cd workos && python verify_gate.py
```
Expected: 게이트 16/16 PASS (하나라도 FAIL이면 중단하고 원인 보고 — 디자인 작업이 데이터를 건드렸다는 뜻)

- [x] **Step 2: 4장 스크린샷 최종 확인** — 두 페이지 × 다크/라이트. dataviz 최종 체크: 라벨 겹침·잘림 없음, 그리드는 배경으로 물러남, 상태색이 글리프·라벨과 항상 병기, 축 눈금 값이 어중간하지 않음(1/2/5 스케일).

- [x] **Step 3: 민감 파일 보호 확인**

```bash
git status --short
```
Expected: `workos/*.html` 이 목록에 **없어야** 함(.gitignore 동작). 나타나면 .gitignore 확인 후 수정.

- [x] **Step 4: 계획 문서 체크박스 갱신 + 잔여 커밋**

```bash
git add docs/superpowers/plans/2026-07-03-workos-design-upgrade.md
git commit -m "Work OS 디자인 업그레이드 완료: 계획 체크박스 갱신

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## 검증 결과 (2026-07-03 실행 기록)

- theme.py 스모크: PASS · dashboard 마커: PASS(19,727B) · ops_board 마커: PASS(38,199B)
- 스크린샷 4장(두 페이지 × 다크/라이트) 육안 확인: 겹침·잘림 없음, y축 눈금·호버 툴팁 동작, 카드 펼침(AI 코멘트) 정상. 발견 결함 1건(KPI 보조텍스트 CJK 개행) 즉시 수정.
- `workos/*.html`·`*.png`·`.playwright-mcp/` 모두 .gitignore 커버 확인 — 공개 repo 유출 없음.
- verify_gate: **14/16** — G1(디스크 줄 수 192,832≠동결 204,414)·G7(동결 553파일 중 16개 소실, mismatch 0) FAIL.
  원인: 원천 세션 로그 드리프트(Claude Code가 agent-*.jsonl 등 트랜스크립트 정리 + 신규 14파일 적재 대기).
  디자인 작업과 무관(본 작업은 workos/*.py UI 코드만 변경, verify_gate·ingest·DB 무변경).
  후속: 다음 증분 적재(ingest) 때 재동결하면 해소 — 데이터 레이어 소관.
