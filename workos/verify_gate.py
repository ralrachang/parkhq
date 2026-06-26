#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PARK HQ Work OS — Phase 1a 정량 게이트 (docs/00_design.md §8).
적재가 동결한 매니페스트(files 테이블)에 대해 '원본 == 적재, 누락·중복 0' 을
**검증기가 디스크에서 독립적으로 재계산**해 증명한다(적재기 카운터를 신뢰하지 않음).
하나라도 FAIL이면 종료코드 1.
사용법: python verify_gate.py [--db ./workos.db] [--projects <dir>]
"""
import argparse, glob, hashlib, os, sqlite3, sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="./workos.db")
    ap.add_argument("--projects", default="C:/Users/wonbuilding/.claude/projects")
    args = ap.parse_args()
    con = sqlite3.connect(args.db); c = con.cursor()

    runs = c.execute("""SELECT run_id,mode,files_seen,raw_lines,parse_errors,exact_dups_dropped,
        rows_stored,rows_canonical,rows_non_canonical,raw_out_tok,canonical_out_tok,distinct_workspaces,
        distinct_projects
        FROM ingest_runs ORDER BY run_id DESC LIMIT 2""").fetchall()
    run = runs[0]
    (_, mode, files_seen, raw_lines, perr, exact_dups, stored, canon, noncanon,
     raw_out, canon_out, n_ws, n_proj) = run

    # ── 독립 재계산: 매니페스트의 각 파일을 검증기가 직접 다시 읽어
    #    (1) 첫 phys_lines 줄을 sha256 재계산(G7 무결성)  (2) 비어있지 않은 줄을 직접 계수(G1) ──
    manifest = c.execute("SELECT path,phys_lines,rec_lines,prefix_sha FROM files").fetchall()
    man_rec_sum = sum(r[2] for r in manifest)
    indep_rec = 0                       # 검증기가 디스크에서 직접 센 레코드 줄 수(적재기 무신뢰)
    m_match = m_mismatch = m_missing = 0
    bad_files = []
    for path, phys, rln, sha in manifest:
        if not os.path.exists(path):
            m_missing += 1; bad_files.append(("MISSING", path)); continue
        h = hashlib.sha256(); n = 0; this_rec = 0
        try:
            with open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    if i > phys: break
                    h.update(line.encode("utf-8", "surrogatepass")); n = i
                    if line.strip(): this_rec += 1
        except Exception as e:
            m_mismatch += 1; bad_files.append(("READERR:" + str(e)[:60], path)); continue
        indep_rec += this_rec
        if n == phys and h.hexdigest() == sha:
            m_match += 1
        else:
            m_mismatch += 1; bad_files.append(("SHA_DRIFT", path))

    # ── DB 내부 정합 ──
    dup_ch = c.execute("SELECT COUNT(*)-COUNT(DISTINCT content_hash) FROM records").fetchone()[0]
    null_ch = c.execute("SELECT COUNT(*) FROM records WHERE content_hash IS NULL").fetchone()[0]
    bad_canon = c.execute("SELECT COUNT(*) FROM (SELECT uuid FROM records WHERE uuid IS NOT NULL "
        "AND is_canonical=1 GROUP BY uuid HAVING COUNT(*)>1)").fetchone()[0]
    tr = c.execute("SELECT COUNT(*) FROM tool_results").fetchone()[0]
    tr_join = c.execute("SELECT COUNT(*) FROM tool_results x WHERE EXISTS "
        "(SELECT 1 FROM tool_calls y WHERE y.tool_use_id=x.tool_use_id)").fetchone()[0]
    unmapped_ws = c.execute("SELECT COUNT(*) FROM records WHERE cwd IS NOT NULL "
        "AND workspace_id IS NULL").fetchone()[0]
    worktree_left = c.execute("SELECT COUNT(*) FROM workspaces "
        "WHERE norm_cwd LIKE '%\\.claude\\worktrees\\%' ESCAPE '\\'").fetchone()[0]
    # ── 프로젝트 루트 롤업 정합 ──
    unmapped_proj = c.execute("SELECT COUNT(*) FROM records WHERE workspace_id IS NOT NULL "
        "AND project_id IS NULL").fetchone()[0]
    n_proj_tbl = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    distinct_proj_rec = c.execute("SELECT COUNT(DISTINCT project_id) FROM records "
        "WHERE project_id IS NOT NULL").fetchone()[0]
    proj_recsum = c.execute("SELECT COALESCE(SUM(n_records),0) FROM projects").fetchone()[0]
    mapped_rec = c.execute("SELECT COUNT(*) FROM records WHERE project_id IS NOT NULL").fetchone()[0]
    # cross-session non-canonical(가시화 INFO): 같은 uuid가 여러 sessionId에 걸친 잔존 그룹
    nc_cross = c.execute("SELECT COUNT(*) FROM (SELECT uuid FROM records WHERE uuid IS NOT NULL "
        "GROUP BY uuid HAVING COUNT(*)>1 AND COUNT(DISTINCT session_id)>1)").fetchone()[0]
    # non-canonical 보관분이 '무엇'인지 타입별 가시화(운영자 오탐 방지)
    nc_break = c.execute("SELECT rec_type, COUNT(*) FROM records WHERE is_canonical=0 "
        "GROUP BY rec_type ORDER BY COUNT(*) DESC").fetchall()
    nc_break_s = ", ".join(f"{t}:{n}" for t, n in nc_break) or "(없음)"

    # ── 멱등성: fresh vs reuse(같은 매니페스트) 동일? ──
    idem = None
    if len(runs) >= 2:
        prev = runs[1]
        idem = (run[6] == prev[6] and run[7] == prev[7])
        idem_detail = f"reuse rows={run[6]} == prev rows={prev[6]}"
    else:
        idem_detail = "reuse 런 없음 — 2회차 적재 후 재검증 필요"

    gates = [
        ("G1  독립 재계산: 검증기가 디스크서 직접 센 줄 == 적재 raw_lines", indep_rec == raw_lines,
         f"{indep_rec:,} == {raw_lines:,}"),
        ("G1b 내부 정합(참고): raw == perr+dup+stored", raw_lines == perr+exact_dups+stored,
         f"{raw_lines:,} == {perr}+{exact_dups:,}+{stored:,}"),
        ("G2  분할 항등식: stored == canonical+non_canonical", stored == canon+noncanon,
         f"{stored:,} == {canon:,}+{noncanon:,}"),
        ("G3  중복 0: content_hash 유니크(중복 0·NULL 0)", dup_ch == 0 and null_ch == 0,
         f"dup={dup_ch} null={null_ch}"),
        ("G2b canonical 정합: 한 uuid에 canonical>1 = 0", bad_canon == 0, f"{bad_canon}"),
        ("G6  파서 무중단: parse_errors == 0", perr == 0, f"{perr}"),
        ("G7  무결성: 동결파일 prefix_sha 재현(불일치·소실 0)", m_mismatch == 0 and m_missing == 0,
         f"match={m_match} mismatch={m_mismatch} missing={m_missing} / {len(manifest)}files"),
        ("G8a 워크스페이스 매핑 누락 0(cwd 있으나 ws NULL)", unmapped_ws == 0, f"{unmapped_ws}"),
        ("G8b worktree 병합: 잔존 worktree 경로 0", worktree_left == 0, f"{worktree_left}"),
        ("G9a 롤업 매핑 누락 0(ws 있으나 project NULL)", unmapped_proj == 0, f"{unmapped_proj}"),
        ("G9b projects 정합: 행수 == records distinct project_id", n_proj_tbl == distinct_proj_rec,
         f"{n_proj_tbl} == {distinct_proj_rec}"),
        ("G9c 롤업 축소: projects ≤ workspaces", n_proj_tbl <= n_ws, f"{n_proj_tbl} ≤ {n_ws}"),
        ("G9d 레코드 보존: Σprojects.n_records == 매핑 레코드", proj_recsum == mapped_rec,
         f"{proj_recsum:,} == {mapped_rec:,}"),
        ("G5  토큰: canonical(진실) ≤ raw, 둘 다 >0", 0 < canon_out <= raw_out,
         f"raw={raw_out:,} canonical={canon_out:,} (dedup 과대 {raw_out-canon_out:,}, "
         f"{100*(raw_out-canon_out)/raw_out:.1f}%)"),
        ("G-tool tool_result→tool_call 조인 100%", tr == 0 or tr_join == tr, f"{tr_join}/{tr}"),
        ("G4  멱등성: reuse 재적재 시 행수 불변", idem is True, idem_detail),
    ]

    # 라이브 추가분 가시화(INFO): 현재 glob 파일 수 vs 동결 매니페스트
    try:
        cur_files = len(glob.glob(args.projects + "/**/*.jsonl", recursive=True))
    except Exception:
        cur_files = None

    print("\n" + "="*76)
    print(f"Phase 1a 게이트 검증  (db={args.db}, 최신 run mode={mode})")
    print("="*76)
    allpass = True; skipped = 0
    for name, ok, detail in gates:
        if name.startswith("G4") and idem is None:
            print(f"[SKIP] {name:<48} {detail}"); skipped += 1; continue
        allpass = allpass and ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name:<48} {detail}")
    print("-"*76)
    print(f"files(동결)={files_seen}  rows_stored={stored:,}  canonical={canon:,}  "
          f"non_canonical(보관)={noncanon:,}  workspaces={n_ws}")
    print(f"[INFO] 프로젝트 루트 롤업: workspaces {n_ws} → projects {n_proj_tbl}  "
          f"(오염 하위폴더 {n_ws-n_proj_tbl}개 병합)")
    print(f"[INFO] cross-session 잔존 그룹(가시화)={nc_cross}  "
          f"| 매니페스트 rec_lines합={man_rec_sum:,}")
    print(f"[INFO] non-canonical 보관분 타입별: {nc_break_s}  "
          f"(같은 uuid에 내용이 진짜 다른 복사본 — 감사용 보관, assistant 토큰 영향 없음)")
    if cur_files is not None and cur_files != files_seen:
        print(f"[INFO] 라이브 추가분: 현재 glob {cur_files}파일 vs 동결 {files_seen}파일 "
              f"(+{cur_files-files_seen}) — 다음 증분 적재 대상")
    if bad_files:
        print("드리프트/소실 파일(최대 8):")
        for tag, p in bad_files[:8]:
            print(f"   {tag}  {os.path.basename(p)}")
    print("="*76)
    verdict = "ALL GATES PASS" if allpass else "GATE FAILURE"
    if skipped: verdict += f"  (SKIP {skipped}: 2회차 적재 후 재검증)"
    print(verdict)
    print("="*76)
    con.close()
    sys.exit(0 if allpass else 1)

if __name__ == "__main__":
    main()
