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
.kpi .v .ks{font-size:13px;font-weight:600;color:var(--mut);margin-left:2px;white-space:nowrap}
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
