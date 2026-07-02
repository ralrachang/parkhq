#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PARK HQ Work OS — Phase 1a 적재기 (PC 로컬 SQLite 정규화).
설계: docs/00_design.md §3, §5, §8.

핵심 원칙(실측 검증됨):
- 멱등키 = content_hash = sha256( raw_json - {휘발성 필드: slug, cwd, parentUuid} ).
  Claude Code의 uuid는 전역 유니크가 아님(세션 resume 시 같은 논리 레코드가 휘발성
  필드만 바뀐 채 재기록). uuid는 대화트리 복원용 논리키로만.
- 같은 uuid에 '내용이 진짜 다른' 복사본이 남으면: canonical 1개(최대 out_tok→최신
  ts) 채택, 나머지는 is_canonical=0 으로 **보관**(사용자 결정: 감사용).
- 토큰 합계/집계는 canonical 레코드만.
- 결측 방어: CC 30버전 전체에서 무중단(없는 필드 NULL).
- cwd 결측 봉투 레코드(last-prompt·queue-operation·file-history-snapshot·started·result
  등, 실측 11,428행·토큰/입력 가중치 0)는 같은 파일의 형제 라인 cwd로 workspace/project
  분류만 폴백(직전 cwd 우선, 선행 구간은 파일 첫 cwd). cwd 컬럼은 원본 그대로(NULL)
  보존, 폴백 건수는 ingest_runs.rows_cwd_inferred에 기록. cwd는 VOLATILE이라
  content_hash·멱등성에 영향 없음.

라이브 데이터 대응(중요):
  세션 로그는 살아 자란다(우리 작업 세션 포함). 그래서 적재 시작 시점에 파일별
  '물리 줄 수 + prefix_sha'를 files 테이블에 **동결(manifest)**하고, 그 경계까지만
  적재한다. 동결 경계 너머 추가분은 다음 증분 적재의 몫(watermark).
  → '원본(=manifest) == 적재, 누락·중복 0' 을 라이브 데이터에서도 자기일관적으로 증명.

사용법:
  python ingest.py --fresh                  # 새 manifest 동결 후 적재(첫 측정)
  python ingest.py --reuse-manifest         # 직전 manifest 경계로 재적재(멱등성 테스트)
  옵션: --projects <dir> --db <path> --limit-files N
"""
import argparse, glob, hashlib, json, os, sqlite3, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# content_hash에서 제외하는 '로깅 봉투(envelope)' 필드 — 실측: 세션 resume/replay 시
# 같은 논리 레코드가 이 필드들만 바뀐 채 재기록된다(slug=줄위치, cwd=작업디렉터리,
# parentUuid=트리위치, sessionId=어느 전사파일, version=resume시 CC버전, promptId=프롬프트
# 그룹id, sessionKind=resume표식). 실질 내용(message/usage/uuid/timestamp 등)은 보존.
VOLATILE = ("slug", "cwd", "parentUuid", "sessionId", "version", "promptId", "sessionKind")

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS files (        -- 동결 매니페스트(watermark)
  path TEXT PRIMARY KEY,
  size_bytes INTEGER,
  phys_lines INTEGER,      -- 물리 줄 수(동결 경계)
  rec_lines  INTEGER,      -- 비어있지 않은(=레코드) 줄 수
  prefix_sha TEXT          -- 첫 phys_lines 줄의 sha256
);

CREATE TABLE IF NOT EXISTS records (
  content_hash   TEXT PRIMARY KEY,
  uuid           TEXT, parent_uuid TEXT, session_id TEXT, rec_type TEXT,
  cwd            TEXT, workspace_id TEXT, project_id TEXT, ts TEXT, model TEXT,
  in_tok INTEGER, out_tok INTEGER, cache_read INTEGER, cache_create INTEGER,
  service_tier TEXT, is_sidechain INTEGER, origin_kind TEXT, prompt_source TEXT,
  request_id TEXT, cc_version TEXT, is_canonical INTEGER NOT NULL DEFAULT 1,
  raw_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_records_uuid    ON records(uuid);
CREATE INDEX IF NOT EXISTS ix_records_session ON records(session_id);
CREATE INDEX IF NOT EXISTS ix_records_type    ON records(rec_type);
CREATE INDEX IF NOT EXISTS ix_records_ws      ON records(workspace_id);
CREATE INDEX IF NOT EXISTS ix_records_proj    ON records(project_id);

CREATE TABLE IF NOT EXISTS workspaces (
  workspace_id TEXT PRIMARY KEY, norm_cwd TEXT, raw_cwds TEXT,
  sensitivity TEXT DEFAULT 'internal',
  client_id TEXT, property_id TEXT, deal_id TEXT, erp_category TEXT
);

CREATE TABLE IF NOT EXISTS projects (    -- 프로젝트 루트 롤업(운영 점검대 단위)
  project_id   TEXT PRIMARY KEY,
  project_name TEXT,
  project_root TEXT,
  n_workspaces INTEGER,
  n_records    INTEGER,
  category     TEXT,        -- 사용자 확정 대기(카테고리/팀 분류)
  agent        TEXT         -- 담당 에이전트(Phase 3)
);

CREATE TABLE IF NOT EXISTS tool_calls (
  tool_use_id TEXT PRIMARY KEY, content_hash TEXT, session_id TEXT,
  tool_name TEXT, tool_kind TEXT, is_mcp INTEGER, task_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_tool_calls_ch ON tool_calls(content_hash);

CREATE TABLE IF NOT EXISTS tool_results (
  tool_use_id TEXT PRIMARY KEY, content_hash TEXT, is_error INTEGER
);

CREATE TABLE IF NOT EXISTS parse_errors (file TEXT, lineno INTEGER, err TEXT);

CREATE TABLE IF NOT EXISTS ingest_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL, finished_at REAL, mode TEXT,
  files_seen INTEGER, raw_lines INTEGER, parse_errors INTEGER,
  exact_dups_dropped INTEGER, rows_stored INTEGER, rows_canonical INTEGER,
  rows_non_canonical INTEGER, raw_out_tok INTEGER, canonical_out_tok INTEGER,
  distinct_workspaces INTEGER, distinct_projects INTEGER,
  rows_cwd_inferred INTEGER
);
"""

def content_hash(o):
    # ensure_ascii=True → 순수 ASCII라 단독 서로게이트(\udXXX)도 인코딩-안전.
    d = {k: v for k, v in o.items() if k not in VOLATILE}
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()

def normalize_cwd(cwd):
    if not cwd:
        return None
    m = "\\.claude\\worktrees\\"
    return cwd.split(m)[0] if m in cwd else cwd

def ws_id(norm):
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16] if norm else None

def first_ncwd_in_file(path, limit):
    """파일 앞부분(동결 경계 내)에서 처음 나오는 non-NULL 정규화 cwd.
    선행 결측 레코드(파일 첫 cwd 등장 이전 줄)의 폴백 분류용. 없으면 None."""
    try:
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if limit is not None and i > limit:
                    break
                s = line.strip()
                if not s:
                    continue
                try:
                    n = normalize_cwd(json.loads(s).get("cwd"))
                except Exception:
                    continue
                if n:
                    return n
    except Exception:
        pass
    return None

# ── 프로젝트 루트 롤업 ───────────────────────────────────────────────
# workspaces(cwd 정규화)는 하위 폴더(engine·output·_qa·scripts…)로 오염된다(실측 65개).
# 운영 점검대는 '프로젝트' 단위가 필요하므로 cwd를 프로젝트 루트로 롤업한다(→ 실측 23개).
#   규칙: 1) 외부 마커 폴더(builpago 등)가 경로에 있으면 그 폴더까지를 루트.
#         2) 컨테이너(claude_project) 바로 아래 1차 세그먼트가 프로젝트.
#         3) 둘 다 아니면 정규화 cwd 전체를 자체 프로젝트로(무손실 폴백).
PROJECT_CONTAINER = "claude_project"       # 프로젝트들이 모여있는 컨테이너 폴더명
PROJECT_EXTERNAL_MARKERS = ("builpago",)   # 컨테이너 밖이지만 단일 프로젝트로 묶을 폴더명

def derive_project(norm):
    """정규화 cwd → (project_id, project_name, project_root). norm=None → (None,None,None)."""
    if not norm:
        return None, None, None
    parts = norm.split("\\")
    low = [p.lower() for p in parts]
    for marker in PROJECT_EXTERNAL_MARKERS:
        if marker in low:
            i = low.index(marker)
            root = "\\".join(parts[: i + 1])
            return ws_id(root), parts[i], root
    if PROJECT_CONTAINER in low:
        i = low.index(PROJECT_CONTAINER)
        if i + 1 < len(parts):                  # 컨테이너 바로 아래 1차 세그먼트
            root = "\\".join(parts[: i + 2])
            return ws_id(root), parts[i + 1], root
        root = "\\".join(parts[: i + 1])        # cwd == 컨테이너 루트 자체
        return ws_id(root), parts[i], root
    return ws_id(norm), parts[-1], norm         # 폴백: 무손실

def tool_kind(n):
    if n.startswith("mcp__"): return "mcp"
    if n in ("Bash", "PowerShell"): return "shell"
    if n in ("Read","Write","Edit","Glob","Grep","NotebookEdit"): return "file"
    if n in ("WebSearch","WebFetch"): return "web"
    if n == "Agent": return "agent"
    if n.startswith("Task"): return "task"
    return "other"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--reuse-manifest", action="store_true")
    ap.add_argument("--projects", default="C:/Users/wonbuilding/.claude/projects")
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "workos.db"))
    ap.add_argument("--limit-files", type=int, default=0)
    args = ap.parse_args()

    if args.fresh:
        for suf in ("", "-wal", "-shm", "-journal"):
            p = args.db + suf
            if os.path.exists(p): os.remove(p)

    con = sqlite3.connect(args.db)
    con.executescript(DDL)
    try:    # 구스키마 DB에 --reuse-manifest로 붙는 경우 대비(신규 DB는 DDL에 포함)
        con.execute("ALTER TABLE ingest_runs ADD COLUMN rows_cwd_inferred INTEGER")
    except sqlite3.OperationalError:
        pass
    cur = con.cursor()

    # 경계(watermark): reuse-manifest면 직전 files 테이블에서, 아니면 동결(EOF까지 읽고 기록)
    bound = {}
    if args.reuse_manifest:
        for path, pl in cur.execute("SELECT path, phys_lines FROM files"):
            bound[path] = pl
        files = sorted(bound.keys())
    else:
        files = sorted(glob.glob(args.projects + "/**/*.jsonl", recursive=True))
        if args.limit_files: files = files[: args.limit_files]
        cur.execute("DELETE FROM files")

    t0 = time.time()
    raw_lines = parse_err = raw_out_tok = cwd_inferred = 0
    pmap_live = {}   # 적재 중 만난 모든 pid→(name,root). 폴백 전용 pid의 projects 보강용.
    rec_b, tool_b, tres_b, perr_b, file_b = [], [], [], [], []
    BATCH = 4000

    def flush():
        if rec_b:
            cur.executemany("INSERT OR IGNORE INTO records "
                "(content_hash,uuid,parent_uuid,session_id,rec_type,cwd,workspace_id,project_id,ts,model,"
                "in_tok,out_tok,cache_read,cache_create,service_tier,is_sidechain,origin_kind,"
                "prompt_source,request_id,cc_version,raw_json) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rec_b); rec_b.clear()
        if tool_b:
            cur.executemany("INSERT OR IGNORE INTO tool_calls "
                "(tool_use_id,content_hash,session_id,tool_name,tool_kind,is_mcp) "
                "VALUES (?,?,?,?,?,?)", tool_b); tool_b.clear()
        if tres_b:
            cur.executemany("INSERT OR IGNORE INTO tool_results (tool_use_id,content_hash,is_error) "
                "VALUES (?,?,?)", tres_b); tres_b.clear()
        if perr_b:
            cur.executemany("INSERT INTO parse_errors (file,lineno,err) VALUES (?,?,?)", perr_b); perr_b.clear()
        con.commit()

    for f in files:
        try:
            fh = open(f, encoding="utf-8")
        except Exception as e:
            perr_b.append((f, -1, "open:" + str(e))); continue
        limit = bound.get(f)            # reuse면 물리 줄 경계
        h = hashlib.sha256()
        phys = rec = 0
        fb_ncwd = pre_ncwd = None       # cwd 폴백: 직전 cwd / 파일 첫 cwd(선행 구간용)
        prescanned = False
        with fh:
            for phys_idx, line in enumerate(fh, 1):
                if limit is not None and phys_idx > limit:
                    break
                phys = phys_idx
                h.update(line.encode("utf-8", "surrogatepass"))
                s = line.strip()
                if not s:
                    continue
                rec += 1; raw_lines += 1
                try:
                    o = json.loads(s)
                except Exception as e:
                    parse_err += 1; perr_b.append((f, phys_idx, str(e)[:200])); continue
                ch = content_hash(o)
                cwd = o.get("cwd"); ncwd = normalize_cwd(cwd)
                if ncwd:
                    fb_ncwd = ncwd
                else:
                    # cwd 결측 봉투 레코드 → 같은 파일 형제 라인 cwd로 분류만 폴백.
                    # cwd 컬럼은 원본(NULL) 보존 — ws/proj 파생 컬럼만 채운다.
                    if fb_ncwd is None and not prescanned:
                        prescanned = True
                        pre_ncwd = first_ncwd_in_file(f, limit)
                    ncwd = fb_ncwd or pre_ncwd
                    if ncwd is not None:
                        cwd_inferred += 1
                msg = o.get("message") if isinstance(o.get("message"), dict) else {}
                usage = msg.get("usage") or {}; rtype = o.get("type", "<none>")
                if rtype == "assistant":
                    raw_out_tok += (usage.get("output_tokens") or 0)
                origin = o.get("origin") or {}
                pid, pname, proot = derive_project(ncwd)
                if pid is not None:
                    pmap_live[pid] = (pname, proot)
                rec_b.append((ch, o.get("uuid"), o.get("parentUuid"), o.get("sessionId"), rtype,
                    cwd, ws_id(ncwd), pid, o.get("timestamp"), msg.get("model"),
                    usage.get("input_tokens"), usage.get("output_tokens"),
                    usage.get("cache_read_input_tokens"), usage.get("cache_creation_input_tokens"),
                    usage.get("service_tier"), 1 if o.get("isSidechain") else 0,
                    origin.get("kind"), o.get("promptSource"), o.get("requestId"), o.get("version"), s))
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict): continue
                        if b.get("type") == "tool_use" and b.get("id"):
                            nm = b.get("name", "?")
                            tool_b.append((b["id"], ch, o.get("sessionId"), nm, tool_kind(nm),
                                           1 if nm.startswith("mcp__") else 0))
                        elif b.get("type") == "tool_result" and b.get("tool_use_id"):
                            tres_b.append((b["tool_use_id"], ch, 1 if b.get("is_error") else 0))
                if len(rec_b) >= BATCH: flush()
        try:
            size = os.path.getsize(f)
        except Exception:
            size = None
        file_b.append((f, size, phys, rec, h.hexdigest()))
    flush()
    if not args.reuse_manifest:
        cur.executemany("INSERT OR REPLACE INTO files (path,size_bytes,phys_lines,rec_lines,prefix_sha) "
                        "VALUES (?,?,?,?,?)", file_b)
        con.commit()

    # canonical 선정
    cur.execute("UPDATE records SET is_canonical=1")
    cur.execute("""
        WITH ranked AS (
          SELECT content_hash, ROW_NUMBER() OVER (PARTITION BY uuid
            ORDER BY COALESCE(out_tok,-1) DESC, COALESCE(ts,'') DESC, content_hash ASC) rn
          FROM records WHERE uuid IS NOT NULL AND uuid IN
            (SELECT uuid FROM records WHERE uuid IS NOT NULL GROUP BY uuid HAVING COUNT(*)>1))
        UPDATE records SET is_canonical=0
        WHERE content_hash IN (SELECT content_hash FROM ranked WHERE rn>1)""")
    con.commit()

    # workspaces
    cur.execute("DELETE FROM workspaces")
    cur.execute("""INSERT INTO workspaces (workspace_id,norm_cwd,raw_cwds)
        SELECT workspace_id, MIN(cwd), json_group_array(DISTINCT cwd)
        FROM records WHERE workspace_id IS NOT NULL GROUP BY workspace_id""")
    con.commit()

    # projects (프로젝트 루트 롤업): DB의 distinct cwd에서 id→(name,root) 매핑을 재구성해
    # 채운다. workspaces처럼 DB 전체에서 재계산하므로 부분 스캔/멱등 재적재에 면역.
    cur.execute("DELETE FROM projects")
    pmap = {}
    for (cwd,) in cur.execute("SELECT DISTINCT cwd FROM records WHERE cwd IS NOT NULL"):
        pid, pname, proot = derive_project(normalize_cwd(cwd))
        if pid is not None:
            pmap[pid] = (pname, proot)
    # 폴백 분류로만 존재하는 pid(저장 cwd 없음)를 적재 시 수집한 매핑으로 보강.
    # records에 실재하는 pid만 추가 → G9b(projects 행수 == distinct project_id) 정합 유지.
    for (pid,) in cur.execute("SELECT DISTINCT project_id FROM records WHERE project_id IS NOT NULL"):
        if pid not in pmap and pid in pmap_live:
            pmap[pid] = pmap_live[pid]
    cur.executemany("INSERT INTO projects (project_id,project_name,project_root) VALUES (?,?,?)",
                    [(pid, nm, rt) for pid, (nm, rt) in pmap.items()])
    cur.execute("""UPDATE projects SET
        n_records    = (SELECT COUNT(*) FROM records r WHERE r.project_id = projects.project_id),
        n_workspaces = (SELECT COUNT(DISTINCT r.workspace_id) FROM records r
                        WHERE r.project_id = projects.project_id)""")
    con.commit()

    rows = cur.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    canon = cur.execute("SELECT COUNT(*) FROM records WHERE is_canonical=1").fetchone()[0]
    canon_out = cur.execute("SELECT COALESCE(SUM(out_tok),0) FROM records "
                            "WHERE is_canonical=1 AND rec_type='assistant'").fetchone()[0]
    n_ws = cur.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
    n_proj = cur.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    exact_dups = raw_lines - parse_err - rows
    cur.execute("""INSERT INTO ingest_runs (started_at,finished_at,mode,files_seen,raw_lines,
        parse_errors,exact_dups_dropped,rows_stored,rows_canonical,rows_non_canonical,
        raw_out_tok,canonical_out_tok,distinct_workspaces,distinct_projects,rows_cwd_inferred)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (t0, time.time(), "reuse" if args.reuse_manifest else "fresh", len(files), raw_lines,
         parse_err, exact_dups, rows, canon, rows-canon, raw_out_tok, canon_out, n_ws, n_proj,
         cwd_inferred))
    con.commit(); con.close()

    print(f"mode={'reuse' if args.reuse_manifest else 'fresh'} files={len(files)} "
          f"raw_lines={raw_lines} parse_errors={parse_err} exact_dups_dropped={exact_dups}")
    print(f"rows_stored={rows} canonical={canon} non_canonical={rows-canon}")
    print(f"raw_out_tok={raw_out_tok:,} canonical_out_tok={canon_out:,} "
          f"workspaces={n_ws} projects={n_proj} cwd_inferred={cwd_inferred}")
    print(f"elapsed={time.time()-t0:.1f}s db={args.db}")

if __name__ == "__main__":
    main()
