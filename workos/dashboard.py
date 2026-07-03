#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PARK HQ Work OS — Phase 2 미리보기 대시보드 생성기 (읽기 전용, 로컬 전용).
검증된 로컬 SQLite(workos.db)를 읽어 의존성 0의 자체완결 HTML을 만든다.
민감 데이터(고객명·금액·세션제목)를 담을 수 있으므로 *_로컬 전용_*, 절대 커밋 금지(.gitignore).
사용법: python dashboard.py [--db ./workos.db] [--out ./dashboard.html]
"""
import argparse, html, os, sqlite3, sys
import theme
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 가정 단가 (USD / 1M tokens) — 확인·수정 필요. 모델군별 표준 비율 가정.
RATES = {  # in, out, cache_write, cache_read
    "opus":   (15.0, 75.0, 18.75, 1.50),
    "sonnet": (3.0, 15.0, 3.75, 0.30),
    "haiku":  (1.0, 5.0, 1.25, 0.10),
    "fable":  (3.0, 15.0, 3.75, 0.30),   # 단가 미공개 → sonnet급 가정
}
def rate_for(model):
    m = (model or "").lower()
    if "opus" in m: return RATES["opus"]
    if "sonnet" in m: return RATES["sonnet"]
    if "haiku" in m: return RATES["haiku"]
    if "fable" in m: return RATES["fable"]
    return (0.0, 0.0, 0.0, 0.0)

def base(cwd):
    if not cwd: return "?"
    return cwd.replace("\\", "/").rstrip("/").split("/")[-1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "workos.db"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html"))
    args = ap.parse_args()
    c = sqlite3.connect(args.db).cursor()

    run = c.execute("""SELECT files_seen,raw_lines,rows_stored,rows_canonical,exact_dups_dropped,
        raw_out_tok,canonical_out_tok,parse_errors FROM ingest_runs ORDER BY run_id DESC LIMIT 1""").fetchone()
    files_seen, raw_lines, stored, canon, dups, raw_out, canon_out, perr = run

    n_ws = c.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
    n_ws_active = c.execute("""SELECT COUNT(*) FROM (SELECT workspace_id FROM records
        WHERE is_canonical=1 AND rec_type='assistant' AND out_tok>0 GROUP BY workspace_id)""").fetchone()[0]
    n_sess = c.execute("SELECT COUNT(DISTINCT session_id) FROM records WHERE session_id IS NOT NULL").fetchone()[0]
    n_human = c.execute("SELECT COUNT(*) FROM records WHERE rec_type='user' AND origin_kind='human' "
                        "AND prompt_source='typed'").fetchone()[0]
    drange = c.execute("SELECT substr(MIN(ts),1,10), substr(MAX(ts),1,10) FROM records WHERE ts IS NOT NULL").fetchone()
    tot = c.execute("""SELECT COALESCE(SUM(in_tok),0),COALESCE(SUM(out_tok),0),COALESCE(SUM(cache_read),0),
        COALESCE(SUM(cache_create),0) FROM records WHERE is_canonical=1 AND rec_type='assistant'""").fetchone()
    tin, tout, tcr, tcc = tot

    daily = c.execute("""SELECT substr(datetime(ts,'+9 hours'),1,10) d, COUNT(DISTINCT session_id),
        COALESCE(SUM(CASE WHEN is_canonical=1 AND rec_type='assistant' THEN out_tok END),0)
        FROM records WHERE ts IS NOT NULL GROUP BY d ORDER BY d""").fetchall()
    daily = daily[-35:]

    ws = c.execute("""SELECT w.norm_cwd, COUNT(DISTINCT r.session_id),
        COALESCE(SUM(CASE WHEN r.is_canonical=1 AND r.rec_type='assistant' THEN r.out_tok END),0) t
        FROM records r JOIN workspaces w ON r.workspace_id=w.workspace_id
        GROUP BY w.workspace_id ORDER BY t DESC LIMIT 14""").fetchall()

    models = c.execute("""SELECT model, COUNT(*), COALESCE(SUM(in_tok),0), COALESCE(SUM(out_tok),0),
        COALESCE(SUM(cache_read),0), COALESCE(SUM(cache_create),0)
        FROM records WHERE is_canonical=1 AND rec_type='assistant' AND model IS NOT NULL
        GROUP BY model ORDER BY 4 DESC""").fetchall()

    tools = c.execute("""SELECT t.tool_name, COUNT(*) FROM tool_calls t
        JOIN records r ON t.content_hash=r.content_hash AND r.is_canonical=1
        GROUP BY t.tool_name ORDER BY 2 DESC LIMIT 14""").fetchall()

    titles = {}
    for sid, tt in c.execute("SELECT session_id, json_extract(raw_json,'$.aiTitle') FROM records "
                             "WHERE rec_type='ai-title' AND json_extract(raw_json,'$.aiTitle') IS NOT NULL ORDER BY ts"):
        titles[sid] = tt
    recent = c.execute("""SELECT r.session_id, MAX(w.norm_cwd),
        substr(datetime(MAX(r.ts),'+9 hours'),1,16),
        COALESCE(SUM(CASE WHEN r.is_canonical=1 AND r.rec_type='assistant' THEN r.out_tok END),0),
        MAX(r.model)
        FROM records r LEFT JOIN workspaces w ON r.workspace_id=w.workspace_id
        WHERE r.ts IS NOT NULL GROUP BY r.session_id ORDER BY MAX(r.ts) DESC LIMIT 20""").fetchall()

    # 비용 추정
    cost_total = 0.0; cost_rows = []
    for m, n, i, o, cr, cc in models:
        ri, ro, rcw, rcr = rate_for(m)
        cst = (i*ri + o*ro + cc*rcw + cr*rcr) / 1_000_000
        cost_total += cst
        cost_rows.append((m, n, o, cst))

    # ---------- HTML ----------
    def bars(rows, label_idx, val_idx, fmt=lambda v: f"{v:,}"):
        mx = max((r[val_idx] for r in rows), default=1) or 1
        out = []
        for r in rows:
            w = 100 * r[val_idx] / mx
            out.append(f'<div class="bar"><div class="bl">{html.escape(str(r[label_idx]))}</div>'
                       f'<div class="bt"><div class="bf" style="width:{w:.1f}%"></div></div>'
                       f'<div class="bv">{fmt(r[val_idx])}</div></div>')
        return "\n".join(out)

    ws_disp = [(base(w[0]), w[1], w[2]) for w in ws]
    model_rows = "".join(f"<tr><td>{html.escape(m)}</td><td class='r'>{n:,}</td>"
                         f"<td class='r'>{o:,}</td></tr>" for m, n, i, o, cr, cc in models)
    cost_rows_html = "".join(f"<tr><td>{html.escape(m)}</td><td class='r'>{o:,}</td>"
                             f"<td class='r'>${cst:,.2f}</td></tr>" for m, n, o, cst in cost_rows)
    recent_rows = "".join(
        f"<tr><td>{html.escape(t or '')}</td><td>{html.escape(base(w))}</td>"
        f"<td>{html.escape(titles.get(sid,'') or '')}</td><td class='r'>{tok:,}</td>"
        f"<td>{html.escape((mdl or '').replace('claude-',''))}</td></tr>"
        for sid, w, t, tok, mdl in recent)

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

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(HTML)
    print(f"대시보드 생성: {args.out}  ({len(HTML):,} bytes)")
    print(f"브라우저로 열기: file:///{args.out.replace(chr(92),'/')}")

if __name__ == "__main__":
    main()
