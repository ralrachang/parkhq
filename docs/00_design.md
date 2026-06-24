# PARK HQ Work OS — Phase 0 설계 (00_design.md)

> 이 문서는 **설계만** 다룹니다(구현 코드 없음). 모든 수치는 실측 센서스(`census.json` / `census_summary.txt`)와 기존 스크립트(`.scripts/*.sh`), 그리고 원본 JSONL 직접 검증에서 인용했습니다. 추측한 항목은 "가정"으로 명시했습니다. 사용자(코딩 비전공·바이브코더)가 읽고 **항목별로 승인/거부**할 수 있도록, 핵심 결정마다 근거와 트레이드오프를 한국어로 적었습니다.
>
> **검증 전 대규모 개발 금지 · 순차 레이어 · 읽기 우선(쓰기·실행은 사람 승인 게이트) · 정량 검증(숫자로 통과 증명) · 에이전트 행동도 다시 로그에 기록(감사).**

---

## 0. 개요 & 확정 결정(4가지)

### 미션 한 줄
Claude Code 작업로그(JSONL)를 **단일 정규화 저장소**로 적재 → 업무 대시보드로 시각화 → 그 위에서 에이전트가 실제 업무를 수행한다. 한 번에 다 짓지 않고, **레이어를 순차로 쌓되 각 단계를 숫자로 검증**한 뒤에만 다음으로 넘어간다.

### 사용자가 이미 확정한 4가지 결정 (이 설계가 반드시 따른다)

| # | 결정 | 이 설계에 미치는 영향 |
|---|---|---|
| **1. ERP = 신규 구축** | Work OS 안에 업무/거래/고객 관리 ERP를 **새로** 만든다. 단 **Phase 1은 "적재"만** 한다. 데이터 모델은 ERP로 확장 가능하게 설계하되, ERP 자체(고객·매물·거래 입력 화면 등)는 후속 Phase. | 정규화 스키마에 **ERP 연결용 빈 칸(nullable FK)을 미리** 뚫어둔다 → Phase 2에서 스키마를 부수지 않고 채우기만 한다(§3). |
| **2. 배포 = Hostinger VPS 통합** | Ubuntu 24.04 호스트. 이미 **Hermes v0.15.1 + Discord 에이전트 3종**(유나=CTO 기술/코드, 서연=CSO 빌딩매매중개, 하린=CLO 개인/투자)이 상시 가동 중. | 저장소·대시보드·에이전트는 **이 VPS에 통합**한다. 새 서버를 띄우지 않는다(§4·§7). |
| **3. 공개범위 = 직접 지정** | 세션 로그엔 고객 실명·거래금액(예: 184억)·비밀키가 섞일 수 있고 기존 `parkhq` 저장소는 **PUBLIC**. | **기본 전부 비공개**(VPS 인증 뒤). 공개는 **사용자가 셀 단위로 켜는 화이트리스트**로만(§6). |
| **4. 적재 원천 = JSONL 주원천 + 기존 일일 .md 병행 유지** | JSONL(세션·토큰·도구호출 단위)이 **새 주원천**. 기존 일일 마크다운 자동화(사람이 읽는 서사 레이어)는 **삭제하지 않고 병행**. | 적재 파이프라인은 신규로 만들되, 기존 `daily_worklog.sh`→`git_push.sh`(parkhq) 트랙은 **독립적으로 계속 동작**(§4·§5). |

### 이 설계의 결론을 한 문단으로
**PC(윈도우)에서 JSONL을 읽어 내용 기반으로 중복 제거(dedup)·1차 비밀 마스킹한 배치를 만들고, SSH로 VPS에 단방향 push → VPS의 PostgreSQL(보유 중인 Supabase 재사용)에 멱등 적재 → 대시보드는 인증 뒤에서만 보이고, 공개는 사용자가 켠 집계만 내보낸다.** 핵심 안전장치 두 가지: ① 멱등키를 `uuid`가 아니라 **내용 해시**로 잡는다(아래 §0의 경고 참조). ② Phase 1 통과는 **±오차 없는 항등식**으로 증명한다(§8).

### ⚠️ 설계를 바꾼 결정적 실측 발견 (반드시 먼저 읽을 것)
초안 3종이 모두 "Claude Code의 `uuid`는 전역 유니크 → `uuid`를 기본키로 UPSERT하면 중복이 구조적으로 0"이라고 단언했습니다. **이는 거짓입니다.** 직접 검증 결과:

- 가장 큰 Building scope 파일(`4e9d5eba…`, 20,753라인): uuid를 가진 레코드 18,580개 중 **distinct uuid는 16,743개뿐**. 두 번 이상 등장하는 uuid 1,837개는 **100%(1,837/1,837)가 내용이 서로 다름**.
- 상위 5개 파일 종합: 내용이 다른 중복-uuid 그룹이 **attachment 969 · assistant 635 · user 290 · system 21**건.
- **무엇이 다른가**: 거의 전부 `slug`(라인 위치/순번 표식), 그리고 일부 `cwd`·`parentUuid`. 즉 **세션을 resume/replay하면 같은 논리적 레코드가 bookkeeping 필드만 바뀐 채 다시 기록**됩니다.

→ 결론: `uuid` 단독 UPSERT는 **서로 다른 레코드를 덮어써 데이터를 손실**시키고, "같은 uuid 3복사본"을 누락으로 셀지 중복으로 셀지 정의가 없어 **게이트 자체가 성립 불가**했습니다. 이 문서는 멱등키를 **내용 해시 기반**으로 교체하고, 게이트를 **항등식**으로 재정의해 이 문제를 수술합니다(§3.5, §8).

---

## 1. 데이터 소스 현황 (실측 숫자)

### 1.1 전체 규모 (불변 닻 = 게이트의 기준 상수)

| 항목 | 실측값 | 출처 / 주의 |
|---|---|---|
| JSONL 파일 수 | **448개** | `FILES=448` |
| 총 레코드(물리 라인) 수 | **199,152** | `LINES=199152` — **불변 닻 A**(원본 물리 라인) |
| 용량 | **707.8 MB** | 미션 브리프 |
| 기간 | **2026-04-14 ~ 06-24** (약 10주) | per-project first/last |
| cwd(워크스페이스) — raw | **29개** | per-project 배열(아래 1.3 정정) |
| 사람 입력 프롬프트 | **166개** | `HUMAN_PROMPTS=166` (구버전 결측 가능) |
| 출력 토큰 | **101,857,444** | **불변 닻 B** |
| 입력 토큰 | **22,399,386** | |
| 캐시읽기 / 캐시생성 | 11,724,059,321 / 1,243,587,686 | 비용 산출은 모델별 단가 분리 필요 |
| 파싱 에러 | **전 파일 parse_err=0** | 라인 단위 무손실 파싱 확인됨 |

> **불변 닻 3개**: 448파일 / 199,152라인 / 출력 101,857,444토큰. 적재 결과가 이 값을 **재현**하는지로 누락·중복을 수치 증명한다(§8).

### 1.2 레코드 타입 13종 (실측 분포)

```
attachment 98,971  assistant 47,964  user 25,434  last-prompt 7,505  mode 5,085
permission-mode 3,801  ai-title 3,253  queue-operation 2,645  system 2,563
file-history-snapshot 1,573  agent-name 130  started 114  result 114
```
- **attachment(98,971, 전체의 49.7%)** 가 최다 — tool_result 본문·붙여넣기·스크린샷 등 대용량. → 원문은 별도 blob 저장소로 분리하고 정규화 테이블엔 참조만(§2·§3).
- 모델 6종 + `<synthetic>`: opus-4-8 26,562 · opus-4-7 13,373 · fable-5 4,066 · sonnet-4-6 3,285 · haiku-4-5 271 · opus-4-6 265 · `<synthetic>` 142(비과금, 비용 산출에서 분리).
- **CC 버전 30종**(2.1.101~2.1.187) → 구버전엔 `origin`·`promptSource`·`service_tier` 결측. 파서는 **결측 방어(NULL 허용·기본값)** 필수.

### 1.3 워크스페이스(cwd) 정정 — 정확한 분모 고정
초안들이 28/29로 엇갈렸습니다. 실측 정정:

- **raw cwd = 29개**
- **worktree = 4개** (병합 대상): builpago 3개(`competent-einstein`, `gracious-mccarthy`, `jolly-benz`) + building sns 1개(`objective-easley`). → 모두 부모 cwd로 병합.
- **빈 세션 = 2개** (assistant 출력 0): `dungeon writer`, `remember project`.
- → **worktree 병합 후 = 25개**, 그중 활동(출력>0) 워크스페이스 = 23개.

### 1.4 스키마 설계를 좌우하는 핵심 관찰

1. **워크스페이스 ≠ 폴더명.** 폴더명은 깨진 인코딩이지만 모든 레코드가 실제 `cwd`를 품는다. **정규화 키는 폴더명이 아니라 `cwd`다.** worktree(`…\.claude\worktrees\…`)는 부모 cwd로 병합한다.
2. **데이터가 한 곳에 극단적으로 쏠림.** `Building scope` 단독으로 139세션·출력 48.8M토큰 = **전체 출력의 약 48%**. 인덱싱·증분이 이 편향을 견뎌야 한다.
3. **현재 JSONL은 미적재.** 기존 `scan_changes.sh`는 파일시스템 mtime(`find -newermt`)만 스캔하고 JSONL 내부는 읽지 않는다. 즉 토큰·세션·도구호출 단위 사실은 **아직 한 번도 정규화 저장된 적이 없다** — 이 설계가 그 첫 적재기다.
4. **비밀·PII는 자유텍스트에 몰려 있다.** 구조화 메타(토큰 수·모델·타임스탬프·sessionId)는 거의 안전. 비밀은 `assistant`/`user`/`attachment`의 본문과 `tool_use.input`(Bash/PowerShell 명령행)에 집중(§6).

---

## 2. JSONL 스키마와 추출 필드

### 2.1 레코드 공통 메타 (대부분의 타입이 보유)
`uuid`, `parentUuid`, `sessionId`, `type`, `timestamp`(ISO-8601 Z, UTC), `cwd`, `gitBranch`, `version`(CC 버전), `isSidechain`(서브에이전트 턴), `slug`(라인 위치 표식 — **dedup에서 제외할 휘발성 필드**).

### 2.2 타입별 핵심 필드 (실측)

| 타입 | 핵심 필드 | 비고 |
|---|---|---|
| `assistant` | `message.model`, `message.content[]`(thinking/text/tool_use), `message.usage{input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens, service_tier}`, `requestId` | requestId 거의 항상 존재(검증: 5,118 중 5,105). 토큰·도구호출의 원천 |
| `user` | `message.role`, `message.content`(문자열=사람입력 / 리스트=tool_result), `origin.kind`(human), `promptSource`(typed), `promptId`, `toolUseResult` | 사람 프롬프트 + 도구결과 |
| `tool_use`(블록) | `id`, `name`(Bash/Read/Edit/Write/Grep/PowerShell/Agent/MCP…), `input` | **`id` 100% 존재**(검증: 2,016/2,016) → 안정 키 |
| `tool_result`(블록) | `tool_use_id`, 결과 본문 | **`tool_use_id` 100% 존재**(검증: 2,013/2,013) → tool_use와 조인키 |
| `attachment` | 본문/`byte_size`/media, `slug` | 최다(98,971). 본문은 blob 분리 |
| `ai-title` | 세션 자동제목 | cwd→거래 매핑 입력으로 **internal 보존**(§3.6) |
| `file-history-snapshot` | 변경 파일 경로·스냅샷 | Edit/Write와 함께 `file_changes`로 |
| `mode`/`permission-mode`/`queue-operation` | 상태 enum (총 11,531건) | **세션 상태 타임라인 별도 테이블**(messages에 섞지 않음) |
| `system`/`started`/`result`/`agent-name` | 시스템 메타·결과코드·에이전트명 | 메타 테이블 |

### 2.3 추출 시 결측 방어 규칙
- 없는 필드는 **NULL/기본값**으로(크래시 금지). CC 30버전 전체에서 파서 무중단이 게이트 G6.
- `timestamp`는 JSONL 원본이 이미 UTC(Z) → **그대로 신뢰**, VPS 저장은 UTC 통일. (PC의 git-bash는 `TZ=Asia/Seoul` 지정 시 GMT로 깨지는 실측 함정이 있으므로 **TZ를 건드리지 않는다**.)

---

## 3. 정규화 스키마 (테이블/컬럼/키/인덱스/멱등키) + ERP 확장 경로

> 베이스 골격은 ERP 초안(cwd=정규화 중심축, worktree 병합, ERP nullable FK 선설계)을 채택하고, 멱등키는 §3.5의 내용 해시로 교체했다. **PC측은 SQLite 임시 스테이징(추출·dedup·1차 마스킹 캐시) 한정**, **VPS측 진실원본은 PostgreSQL**(§7).

### 3.1 `workspaces` — cwd 정규화 마스터 (ERP 연결의 중심축)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| workspace_id | TEXT PK | `sha1(normalized_cwd)` — 안정·멱등 |
| raw_cwd | TEXT | 예: `D:\claude_project\Building scope` |
| display_name | TEXT | 사람이 읽는 표시명(수동 보정) |
| is_worktree | BOOL | true면 parent로 병합 |
| parent_workspace_id | TEXT NULL FK→workspaces | worktree→부모 |
| sensitivity | TEXT | `public`/`internal`/`confidential` (기본 `internal`, §6) |
| client_id / property_id / deal_id | TEXT NULL FK | **ERP 확장 슬롯(Phase 1엔 전부 NULL)** |
| erp_category | TEXT NULL | lookup 테이블 참조(enum 아님, ALTER 불필요) |

### 3.2 `sessions`

| 컬럼 | 타입 | 비고 |
|---|---|---|
| session_id | TEXT PK | JSONL `sessionId` |
| workspace_id | TEXT FK→workspaces | |
| ai_title | TEXT NULL | ai-title 레코드 |
| started_at / ended_at | TIMESTAMP | UTC |
| cc_version_set | JSONB | 등장 버전들 |
| git_branch | TEXT NULL | |
| msg_count / human_prompt_count | INT | 집계 캐시 |
| in_tok / out_tok / cache_read / cache_create | BIGINT | dedup 후 canonical 합산 |
| est_cost_usd | NUMERIC NULL | 모델 단가×토큰 |
| deal_id / task_id | TEXT NULL FK | **ERP 확장 슬롯** |

**멱등키**: `session_id`(PK). **인덱스**: `(workspace_id)`, `(started_at)`.

### 3.3 `messages` (자유텍스트 레코드: assistant/user/system)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| message_pk | TEXT PK | **= content_hash (§3.5)** — 진짜 멱등키 |
| uuid | TEXT | **트리 복원용 논리키(PK 아님)** |
| session_id | TEXT FK | |
| parent_uuid | TEXT NULL | 대화 트리 |
| workspace_id | TEXT FK | 비정규화(쿼리 가속) |
| rec_type | TEXT | assistant/user/system |
| role | TEXT NULL | user/assistant |
| model | TEXT NULL | assistant만 |
| is_sidechain | BOOL | |
| origin_kind / prompt_source | TEXT NULL | 구버전 NULL |
| request_id | TEXT NULL | assistant |
| created_at | TIMESTAMP | |
| in_tok/out_tok/cache_read/cache_create | INT NULL | usage(없으면 NULL) |
| service_tier | TEXT NULL | |
| content_redacted | TEXT NULL | **1차 마스킹(비밀만) 통과 본문**(§6) |
| is_canonical | BOOL | 같은 uuid 중복군의 채택판 표시(§3.5) |
| redaction_flags | JSONB | 마스킹 타입별 카운트(감사) |

**멱등키**: `message_pk(=content_hash)`. **인덱스**: `(session_id, created_at)`, `(uuid)`, `(rec_type)`, `(model)`.

### 3.4 보조 테이블

**`tool_calls`** — tool_use 블록.
| 컬럼 | 비고 |
|---|---|
| tool_use_id TEXT PK | 실측 100% 존재 |
| message_pk TEXT FK→messages · session_id · workspace_id (비정규화) | |
| tool_name TEXT · tool_kind TEXT(file/shell/web/mcp/agent/task) · is_mcp BOOL | |
| input_summary TEXT NULL | 파일경로·명령 요약(비밀 마스킹 후) |
| target_path TEXT NULL | file_changes 연결 |
| created_at · task_id TEXT NULL FK(ERP 슬롯) | |

**`tool_results`** — tool_result 블록. PK `(tool_use_id)`, FK→tool_calls(tool_use_id). **이 매핑이 세 초안 모두 누락했던 tool_use↔tool_result 조인키다.** 본문은 `result_redacted`/`blob_ref`.

**`attachments`** — 98,971건. PK `attachment_id`, FK message_pk, `blob_ref`(원문은 DB 밖), `byte_size`, `media_type`. **slug는 dedup 키에서 제외**(같은 attachment의 재기록 흡수).

**`file_changes`** — file-history-snapshot + Edit/Write 파생. PK 합성 `(message_pk, file_path, change_kind)`, `change_type`(create/edit/write/delete), `occurred_at`, `deal_id NULL`(ERP 슬롯). 인덱스 `(file_path)`.

**`session_state_events`** — `mode`/`permission-mode`/`queue-operation`(11,531건)을 **별도 타임라인**으로 수용(messages에 섞지 않음). 컬럼: session_id, event_type, value, at.

**`meta_events`** — `system`/`started`/`result`/`agent-name`. 가벼운 메타.

**`daily_rollup`** — 대시보드 사전집계. PK `(day(KST), workspace_id)`. sessions/messages/human_prompts, in/out/cache 토큰, est_cost_usd, top_tools(JSONB), models(JSONB), `narrative_md_path`(그날 사람이 읽는 .md 링크 — 기존 자동화 산출물 병행), `deal_id NULL`(ERP 슬롯). 재실행 시 해당 (day,workspace)만 DELETE+재집계(부분 멱등).

**`ingest_runs`** — 게이트 증거 원장. run_id, started/finished, files_seen, raw_lines_seen, rows_ingested_canonical, rows_deduped_dropped, parse_errors, manifest(JSONB: 파일별 prefix-sha·offset). **§8 게이트의 증거 테이블.**

### 3.5 멱등키 설계 (must_fix #1·#2 반영 — 이 설계의 심장)

**문제(실측):** 같은 `uuid`가 내용이 다른 채로 여러 번 등장(세션 resume/replay). `uuid` UPSERT는 데이터 손실.

**해법 — 2단계 키:**
1. **dedup 키 = `content_hash`** = `sha256` of (레코드를 정규화한 JSON에서 **휘발성 bookkeeping 필드 제외**). 제외 필드(실측 근거): `slug`(라인 순번), 그리고 dedup 판정용으로 `cwd`·`parentUuid`는 정규화 후 비교(이들이 resume 시 바뀌는 주범). → 같은 논리적 레코드의 재기록은 **동일 해시로 수렴**(중복 0), 진짜로 다른 레코드는 다른 해시(손실 0).
2. **uuid = 논리키만** — 대화 트리(parent_uuid) 복원·조인에만 쓰고 PK가 아니다.

**같은 uuid의 "내용이 진짜 다른" 복사본 채택 규칙(canonical):** 같은 uuid 그룹에서 **마지막 등장(최신 timestamp) 또는 최대 usage 보유 레코드**를 `is_canonical=true`로 채택. **토큰 집계는 canonical 레코드만 합산**(어느 복사본을 쓰냐로 합계가 흔들리는 문제 제거). 비채택 복사본은 보관(감사) 또는 폐기 — **사용자 확정 게이트(§9)**.

> 결과: "전량 재파싱해도 중복 0"이 **구조적으로** 성립(키가 내용 해시라서). 이는 §5의 rewrite 대응(전량 재파싱)을 안전하게 만든다.

### 3.6 ERP 확장 경로 (Phase 2+, 골격만)

**미래 ERP 테이블(Phase 2 생성):**
```
clients     client_id PK · name · type · contact · sensitivity
properties  property_id PK · client_id FK · address · type · price_listed · status
deals       deal_id PK · property_id FK · client_id FK · stage(lead/nego/contract/closed)
                       · amount · agent_role(서연CSO/하린CLO/…) · opened_at · closed_at
tasks       task_id PK · deal_id FK NULL · client_id FK NULL · workspace_id FK NULL
                       · title · status · assignee · due_at · source(human/agent)
```

**연결 전략 — cwd가 중심축, 3단계 점진 도입(검증 전 대규모 금지):**
- **A. 1:1 정적 매핑(Phase 2 진입 즉시):** 활동 워크스페이스를 ERP 카테고리에 수동 연결. `workspaces`의 nullable FK만 채움 → **스키마 변경 0**.
- **B. 세션/거래 N:1:** 한 cwd에 여러 거래가 섞이면 `sessions.deal_id`로 세션 단위 귀속. **ai-title·human prompt 키워드(주소·고객명·금액)로 반자동 후보 제시 → 사람 승인 게이트.** (이래서 §6에서 ai-title을 마스킹하지 않고 internal 보존한다 — 매핑 입력을 죽이지 않으려고.)
- **C. 산출물/행동 단위:** `file_changes.deal_id`(계약서·IM이 어느 거래물인지), `tool_calls.task_id`(에이전트 행동이 어느 업무인지) → "이 거래에 AI가 몇 토큰·어떤 산출물을 기여했나"를 deal 단위로 집계.

**못 박힘 방지:** ① 모든 ERP FK는 Phase 1부터 nullable로 존재(비파괴 마이그레이션). ② cwd→deal은 직접 FK가 아니라 sessions/file_changes/tool_calls의 nullable FK로 분산(N:1 수용). ③ erp_category는 lookup 테이블(새 업종 추가에 ALTER 불필요).

---

## 4. 3레이어 아키텍처(텍스트 다이어그램) + 신뢰경계

```
┌─ 신뢰경계 TB1 : 윈도우 PC (사용자 단독 제어 / 평문·비밀이 존재하는 유일 영역) ──┐
│  C:\Users\wonbuilding\.claude\projects\<인코딩폴더>\*.jsonl  (448파일·707MB)    │
│        │                                                                        │
│   ├─[기존] scan_changes.sh → daily_worklog.sh → 서사 .md → git_push.sh(parkhq)  │
│   │        (mtime 스캔, 09:40 KST, 병행 유지 — 독립 트랙)                       │
│   │                                                                             │
│   └─[신규] L1 적재 파이프라인 (모두 PC에서, 09:40 잡 직후)                       │
│        (1) 증분 스캔: prefix-sha 커서로 변경/추가/rewrite 감지 (§5)              │
│        (2) 파싱+정규화: cwd 병합·결측 방어·content_hash dedup (§3.5)             │
│        (3) 1차 비밀 마스킹: 자격증명만 하드 차단, 메모리에서 폐기 (§6)            │
│        (4) SQLite 스테이징 → dedup된 NDJSON 배치 + manifest 생성                 │
└──────────────────────────────┬──────────────────────────────────────────────────┘
                               │  ↑ 신뢰경계 TB2 (네트워크) ↑
                  SSH(ed25519) 단방향 push (rsync). 키인증·평문/PAT-in-URL 금지.
                  VPS는 PC로 역접속 안 함(역방향 차단).
                               ▼
┌─ 신뢰경계 TB3 : Hostinger VPS (Ubuntu 24.04 · 기본 전부 인증 뒤 비공개) ─────────┐
│  L2 저장/정규화                                                                  │
│   수신: cron이 incoming/ 폴링 → verify_gate.py(2차 마스킹 재검증·게이트)         │
│        통과 못하면 quarantine, 적재 중단·알림                                    │
│   PostgreSQL (보유 Supabase 재사용):                                            │
│     raw 스키마(내부전용, 외부 도달 0) → derived(집계) → public_view(뷰만)        │
│     role 분리: ingest_role(raw 쓰기) / api_role(public_view 읽기)               │
│   attachment blob: VPS 파일시스템/오브젝트 스토어(DB엔 참조만)                   │
│   [Phase 2+ 슬롯] clients/properties/deals/tasks (nullable FK로 연결)            │
│                               │                                                  │
│  L3 시각화/실행 (후속 Phase, 승인 게이트)                                         │
│   대시보드(Next.js, 읽기전용) ─ 인증 뒤 derived 전체 / 공개표면은 public_view만   │
│   에이전트 유나·서연·하린 (Hermes+Discord) ─ DB 읽기, 쓰기·실행은 사람 승인      │
│        └ 에이전트 행동도 다시 audit 로그로 재적재(감사)                          │
└──────────────────────────────────────────────────────────────────────────────────┘
   parkhq(PUBLIC) = 서사 .md 전용 트랙 (JSONL 적재물과 물리적으로 절대 교차 금지)
```

**신뢰경계 요약:** TB1(PC)에서 **비밀은 경계를 넘기 전에 1차로 죽인다**. TB2는 PC→VPS 단방향·키 인증. TB3는 기본 비공개, raw는 외부 도달 불가(role 분리·localhost 바인딩), public_view만 공개 후보. **Phase 1 범위 = L1 + L2의 읽기 검증까지.** L3·ERP는 후속.

---

## 5. PC→VPS 동기화 설계 (구체 메커니즘·보안·멱등·실패복구)

**확장점:** 기존 `daily_worklog.sh`가 이미 09:40 작업스케줄러에서 PC에 돌고 git push까지 한다. **새 데몬·새 스케줄러를 만들지 않고** 이 잡에 단계를 덧붙인다(과설계 회피). 단계 순서: `scan_changes(mtime)` → **`ingest_jsonl(증분+dedup+1차마스킹)` → `sync_to_vps(SSH push)`** → 기존 `git_push(.md)`. 서사 .md 트랙과 적재 트랙은 **독립 실패 가능**하게 분리(VPS가 죽어도 .md는 산다).

### 5.1 증분 메커니즘 — append-only 가정 보강 (must_fix #4)
JSONL이 순수 append라는 가정은 **틀렸다**(resume 시 앞부분 rewrite). 따라서:
- **커서 파일** `~/.claude/sync_state.json`: 파일별 `{path, size, mtime, last_offset, prefix_sha}`.
- **판정:** 이전 처리 끝 offset까지의 **prefix-sha**가 그대로면 → append-only 확정 → **늘어난 라인만** 파싱. prefix-sha가 깨졌으면 → 그 파일 **전량 재파싱**.
- **안전:** 멱등키가 내용 해시(§3.5)라 전량 재파싱해도 **중복 0**. (전체 707MB 매일 재파싱은 회피하되, rewrite는 절대 누락 안 함.)
- **백필/증분 분리:** 최초 1회 707MB 전량 적재는 **별도 1회성 백필 잡**(야간 수동 승인). 이후는 증분.

### 5.2 전송 매체 — SSH push 단일화 (must_fix #5, 초안 충돌 해소)
초안들이 rsync/scp·HTTPS API·SSH로 엇갈렸고 셋 다 "신규 인프라 0"이라 주장했으나 부정확(어느 쪽이든 VPS에 수신 표면이 새로 생긴다). **결론: SSH(ed25519) + rsync push로 단일화** — 신규 표면이 **sshd authorized_keys 1줄**로 가장 작다. 신규 API 서버 불필요, **Hermes 포트·프로세스는 건드리지 않는다**(이는 가정이 아니라 §9의 사용자 확인 항목으로 등재).
- PC측 키: ed25519 개인키, **worktree 밖**, chmod 600. (기존 `git_push.sh:10`의 토큰 격리 패턴 계승: 비밀은 working tree 밖 보호파일에서만 읽고 절대 커밋 안 함. `.gitignore`에 `*.token *.pat .env*` 이미 존재 → `.worklog-sync-*` 추가.)
- VPS측: 전용 키 1개 + `from=`로 IP 핀(최소권한). PAT를 URL에 박는 `git_push.sh:20` 방식보다 **키 인증으로 격상**(명령행·URL에 비밀 미노출).
- 에러 로그 마스킹: `git_push.sh:36`의 `sed "s/${TOKEN}/***/g"` 패턴을 동기화 로그에도 적용.

### 5.3 멱등 적재
- 전송물 = dedup된 NDJSON 배치(파일 통째 X) + manifest. VPS는 **content_hash 기준 멱등 UPSERT**(`ON CONFLICT (message_pk) DO NOTHING`/canonical 갱신 규칙).
- 배치 단위 `ingest_run_id` 트랜잭션 → 재전송·부분 실패 무해(at-least-once + 내용해시 멱등 = 정확히 한 번 효과).

### 5.4 실패 복구

| 실패 지점 | 동작 |
|---|---|
| 네트워크 단절 | PC에 배치 보존(append) → 다음 09:40에 미전송분부터 재개 |
| VPS 마스킹 재검증 실패 | 해당 라인 **quarantine + 적재 중단 + 알림**(비밀 누출 의심 → 사람 확인) |
| 부분 적재 | `ingest_run_id` 트랜잭션 롤백 |
| 키 누락 | `git_push.sh:14`의 `SKIP_NO_KEY` 패턴 — 조용히 건너뛰고 로컬 보존(데이터 유실 0) |
| 무결성 | 전송 후 VPS가 manifest의 prefix-sha 재계산 → 불일치 시 해당 파일 재요청 |

---

## 6. 보안·비밀 마스킹 + 공개범위 화이트리스트 초안 (사용자 확정 대상)

### 6.1 마스킹 정책 — "자격증명만 차단, 업무내용은 보존하되 비공개" (must_fix #3)
사용자 확정 정책(MEMORY: parkhq-public-repo-policy)은 **"자격증명(API키·토큰)만 제외, 업무 내용 공개 OK"**. 따라서 security 초안의 NER 고객명·금액 마스킹을 **디폴트에서 내린다**(그걸 디폴트로 박으면 ERP가 다뤄야 할 고객·거래 데이터를 적재 단계에서 파괴해 §3.6 매핑이 불가능해짐). 대신:

- **하드 차단(무조건, 적재 단계에서 메모리 폐기):** 자격증명/비밀만.
  - 패턴 정규식: `sk-…`, `ghp_/github_pat_…`, `xox[baprs]-…`(봇토큰), AWS `AKIA…`, `https://<user>:<pw>@…`, JWT `eyJ…`, PEM `-----BEGIN … PRIVATE KEY-----`, Supabase `service_role` JWT, `.env` 라인 `KEY=value`. **`git_push.sh`의 `https://${TOKEN}@github.com` 형태 명시 룰.**
  - 컨텍스트 룰: Read/Write/Edit 대상 경로가 `.env|*.pat|*.token|*secret*|*credential*|*.pem|service-account*.json` → 해당 input/result 본문 통째 `[REDACTED:file]`.
  - **fail-closed:** 파싱·마스킹 모듈 예외 시 그 라인은 전송 제외(통과 금지).
- **고객명·금액 = 마스킹 아님, 접근 등급으로 보존.** 원문은 VPS `raw` 스키마에 보존(ERP 매핑·감사에 필수)하되 **외부 도달 0**(role 분리·localhost 바인딩). 공개표면(public_view)에는 **집계·기술메타만** 나간다.
- **다층 방어:** PC 1차 마스킹(필수) + VPS 2차 재검증(방어적 재스캔, 룰 누락 회귀 방지).

### 6.2 공개범위 화이트리스트 — 필드 단위 (deny-by-default)

| 필드 | PUBLIC(집계) | 내부전용(인증) | 미저장/폐기 |
|---|---|---|---|
| model / cc_version | ● | | |
| token_usage(in/out/cache) · est_cost_usd | ●(집계) | | |
| timestamp | ●(일 단위) | ●(정밀) | |
| tool_name 빈도 · MCP 사용 수 | ●(집계) | | |
| model 분포 · is_sidechain 비율 | ●(집계) | | |
| n_sessions/messages/human_prompts | ●(집계) | | |
| display_name(사용자가 정한 안전 표시명) | △(프로젝트별 §6.3) | ●(전체) | |
| project_key(슬러그)·git_branch | | ● | |
| cwd 원경로(사용자명·내부구조) | | | ● → display_name으로 대체 |
| session_id/uuid/requestId | | ● | |
| ai-title 원문 | | ●(**internal 보존**, 마스킹 X — §3.6 매핑 입력) | |
| content(평문)·tool input/result(평문)·attachment 본문 | | (마스킹본만 raw) | ●(공개표면 절대 금지) |
| 고객 실명·거래금액 정확값 | | ●(raw 보존, 인증 뒤) | (공개표면 금지) |
| 비밀/키/토큰 | | | ●(하드 차단·폐기) |

### 6.3 공개범위 화이트리스트 — 프로젝트(cwd) 단위 (사용자 확정 대상)
**기본값 전부 `internal`.** PUBLIC 승격은 사용자가 셀 단위로 확정. **근거 없는 추정 금지** — ai-title 등 실측 근거가 없으면 `UNKNOWN→internal`(보수적). 아래는 per-project 실측(`census_summary.txt`)에 근거한 **출발점 제안**일 뿐이며, 사용자가 ✅/❌로 확정한다.

| cwd | 실측 근거 | 권장 초기 등급 | 사용자 확정 |
|---|---|---|---|
| `Building scope` | 139세션·출력 48.8M(최대), 빌딩매매 추정 | **confidential**(익명 집계만) | ☐ |
| `diwolbu` | 88세션, 성격 근거 부족 → 추정 금지 | **internal (UNKNOWN)** | ☐ |
| `building sns` | 40세션, 빌딩 SNS 콘텐츠 | internal | ☐ |
| `wonbuilding AI TF` | 사내 AI TF | internal | ☐ |
| `매수고객관리` / `직원평가시스템` | 고객/인사 PII 명백 | **confidential**(익명 집계만) | ☐ |
| `team ERP`, `team ERP/erp/project` | ERP 구축 | internal | ☐ |
| `Auto IM2` / `Auto IM pptx` | 거래 산출물(IM) → deal 연결 | internal | ☐ |
| `builpago`(빌파고닷컴) | 자사 제품 | public-lite 후보 | ☐ |
| `데일리 작업로그` | 자동화 인프라(본 프로젝트) | **public 후보** | ☐ |
| `worldcup dashboard`/`godot`/`remotion_youtube`/`dungeon writer`/`kordoc`/`korea-finance` | 도구·실험·콘텐츠 | public-lite 후보 | ☐ |
| `Taxpago`/`yangjae_NI`/`ppt yoon`/`notion work` | 내부 작업물 | internal | ☐ |

> 룰: 고객명·거래금액이 닿는 cwd(Building scope·매수고객관리·직원평가시스템)는 **익명 집계 외 일체 비공개 + project_key도 별칭**. 자사 제품/도구/인프라만 PUBLIC 후보. **사용자 확정 전 기본 전부 internal.**

### 6.4 공개표면이 실제로 내보내는 것(안전 예시)
"이번 주 6개 프로젝트에서 139세션, opus-4-8 비중 55%, 출력 48.7M토큰, 추정비용 $X, Bash 호출 N회" — **숫자·집계·기술메타만. 고객·금액·본문·키는 0건.** 기술 게이트: 공개 뷰는 `public_view`(SQL 뷰)로만 노출, 원본 테이블 직접 노출 금지(role 분리).

---

## 7. 기술 스택 선택 + 근거/트레이드오프

| 레이어 | 선택 | 근거 | 트레이드오프 / 배제 이유 |
|---|---|---|---|
| L1 추출기 | **기존 bash 드라이버 확장 + Python 3 파서**(stdlib json/sqlite3) | 09:40 스케줄러·토큰격리 패턴이 이미 검증됨. Python은 결측 방어·dedup·NDJSON 변환에 간결. 의존성 0, 라인 스트리밍으로 707MB 안전(parse_err=0 검증) | 신규 상시 데몬 0(공격표면 최소) |
| PC 스테이징 | **SQLite (임시)** | 추출·dedup·1차 마스킹 로컬 캐시 한정. 파일 1개로 단순 | 진실원본 아님 — VPS로만 push |
| L2 진실원본 DB | **PostgreSQL (보유 Supabase 재사용)** | **다중 동시 접근**(PC 적재 + 대시보드 + 에이전트 3종 read/write + 감사 write)을 SQLite 단일 라이터가 못 견딤(락 경합). ERP 다중 엔티티 조인·FK 무결성·MVCC 필요. 보유 스택 재사용(중복구축 금지) | 서버 운영 필요(SQLite 우위 항목) — 그러나 다중접근·ERP·감사가 확정 요구라 Postgres 필수급 |
| attachment 저장 | **VPS 파일시스템/오브젝트 스토어** | 98,971건·대용량 → DB 밖, 인덱스만 경량 유지 | 저장 위치 최종 확정은 §9 |
| 동기화 | **SSH(ed25519) rsync push** | 신규 표면 최소(sshd만), 키 인증, PAT-in-URL 회피 | 실시간성 없음(일 1회) — Phase 1 목적엔 충분 |
| L3 대시보드 | **Next.js 읽기전용, VPS 통합** | 기존 스택 일관(빌파고=Next.js), Hermes 호스트 재활용 | Cloudflare Pages는 DB 직접 못 읽음 → 데이터 레이어는 VPS |
| L3 에이전트 | **Hermes v0.15.1 + Discord(유나/서연/하린)** | VPS 상시가동 중 → 그 위에 얹음 | 후속 Phase, 쓰기·실행은 승인 게이트 |
| 공개 .md | 기존 `git_push.sh`→parkhq(PUBLIC) 유지 | 검증된 트랙 | JSONL 적재물과 물리 격리 |

**일관성 유지:** Hermes/Discord/Supabase/Next.js/일일.md를 **중복 구축하지 않고** 재사용·확장한다.

---

## 8. Phase 1 정량 통과 게이트 (숫자로 측정·증명)

> 게이트는 `verify_gate.py`가 자동 산출하고 `ingest_runs`에 기록. **모든 기준 ±오차 없이 PASS여야 Phase 1 통과** → 그 전엔 대시보드 빌드·L3 착수 금지(순차 레이어).

### 8.1 게이트 분모 2층 분리 (must_fix #2)
- **분모 A(불변 닻):** 원본 물리 라인수 = **199,152**(불변).
- **분모 B(결정값):** dedup 후 canonical 레코드수 = 파이프라인이 산출.
- **핵심 항등식:** `Σ(파일별 라인수) = 199,152 = rows_ingested_canonical + rows_deduped_dropped + parse_errors`. **차이 = 0 (± 허용 금지).**

### 8.2 게이트 표

| # | 기준 | 측정식 | PASS 조건 |
|---|---|---|---|
| G1 | **건수 항등식** | 199,152 == canonical + deduped_dropped + parse_errors | **차이 0** |
| G2 | **dedup 정합** | 같은 uuid 중복군이 deduped_dropped로 정확히 분류, canonical 1개만 | 분류 누락 0 |
| G3 | **중복 0(구조)** | `content_hash` UNIQUE 제약 | 위반 행 0 |
| G4 | **멱등성** | 동일 적재 2회 연속 실행 후 행수 동일 | Δrow = 0 |
| G5 | **토큰 정합** | DB `SUM(out_tok)` over **canonical** == 101,857,444 | **정확히 일치**(결측분은 결측필드 카운트로 별도 증명) |
| G6 | **파서 무중단** | CC 30버전 전체, parse_errors | 0 (census 확인 재현) |
| G7 | **무결성** | VPS prefix-sha 재계산 == PC manifest | 전 파일 일치 |
| G8 | **워크스페이스 정규화** | raw cwd 29 → worktree 4 병합 → 25, 미매핑 | 0 |
| G9 | **rewrite 누락 0** | resume된 파일의 prefix-sha 깨짐 감지 → 전량 재파싱 후 canonical 재현 | 누락 uuid 0 |
| G10 | **공개표면 격리** | public_view에서 raw 도달 시도(권한 테스트) | 성공 0건 |
| G11 | **ERP 슬롯 비파괴** | ERP 빈 테이블 생성 + FK 채움이 로그 스키마 ALTER 0 | 마이그 dry-run 통과 |

### 8.3 비밀 0건 유출 검증 (통과 못하면 Phase 종료 금지)
1. **레드팀 코퍼스:** 더미 `sk-`/PEM/봇토큰을 테스트 JSONL에 심어 통과 → DB 어디에도 평문 0건(`LIKE`/정규식 스캔).
2. **전수 스캐너:** 적재 후 derived/public_view 전 행을 §6 룰셋 + gitleaks/trufflehog류로 재스캔 → 매치 0건.
3. **공개표면 침투:** 비인증 클라이언트로 public_view 호출 → 고객명·금액·키 응답 0건.
4. **parkhq 회귀:** PUBLIC 커밋 diff에 `.token/.pat/.env`·키 패턴 0건.
5. **quarantine 리뷰:** 격리 라인은 사람 확인 후에만 처리(자동 통과 금지).

> **측정 닻 재확인:** 199,152 라인 / 448 파일 / 출력 101,857,444 토큰을 게이트 상수로 박고, 적재 결과가 이 값을 **재현**하는지로 누락·중복을 증명한다.

---

## 9. 미해결 질문 (사용자 확정 필요 항목)

1. **L2 DB 확정:** PostgreSQL(보유 Supabase 재사용) 채택 — 승인? (권장)
2. **공개 등급 확정:** §6.3 표의 cwd별 sensitivity 초기값을 셀 단위로 ✅/❌. (기본 전부 internal, 근거 없는 cwd는 internal 유지)
3. **공개 집계 허용:** 토큰 합·추정 비용·도구 분포 등 §6.2의 PUBLIC(집계) 컬럼을 실제로 공개할지.
4. **canonical 비채택 복사본 처리:** 같은 uuid의 비채택 복사본을 **보관(감사용)** vs **폐기** 중 어느 쪽?
5. **원문 평문 보존 범위:** raw 스키마에 본문 평문을 보존(ERP 매핑·감사에 필요)하되, 별도 오프라인 암호화 vault가 필요한지(고민감 cwd 한정).
6. **attachment blob 저장 위치:** VPS 파일시스템 vs 오브젝트 스토어.
7. **VPS 사실 확인(가정 아님):** Hermes가 쓰는 포트/프로세스를 건드리지 않는 SSH 수신만 추가 가능한지 — VPS에서 직접 확인 필요.
8. **백필 승인:** 707MB 전량 1회 적재를 야간 수동 승인으로 실행할지.

---

## 10. Phase 로드맵 요약

| Phase | 범위 | 통과 게이트(요약) |
|---|---|---|
| **Phase 1 — 적재 + 읽기 검증** (이 문서) | L1(PC 추출·dedup·1차 마스킹) + SSH 동기화 + L2 Postgres 멱등 적재 + 게이트 검증. **읽기 전용.** | §8의 G1~G11 전부 PASS + 비밀 0건(5종 검증). 기존 .md/parkhq 트랙 회귀 0. |
| **Phase 2 — 대시보드(읽기)** | Next.js 읽기전용 대시보드(인증 뒤), daily_rollup 시각화, 공개표면 public_view. ERP 1:1 정적 매핑(단계 A). | 집계가 원시 합산과 100% 일치(샘플 7일), 공개표면 격리 침투 0건. |
| **Phase 3 — ERP 구축** | clients/properties/deals/tasks 생성, cwd→deal 반자동 매핑(단계 B·C, 사람 승인 게이트). | 비파괴 마이그(ALTER 로그 0), 매핑 사람 승인율·정확도 기준. |
| **Phase 4 — 에이전트 실행(쓰기)** | 유나·서연·하린이 ERP 위에서 실제 업무. **쓰기·실행은 사람 승인 게이트 + 행동 재로깅(감사).** | 모든 에이전트 행동이 audit 로그에 100% 재기록, 승인 없는 쓰기 0건. |

**절대 원칙 재확인:** 검증 전 대규모 개발 금지 · 순차 레이어 · 읽기 우선 / 쓰기·실행은 사람 승인 게이트 · 정량 검증(각 Phase 숫자 통과) · 에이전트 행동도 다시 로그에 기록.

---

### 참고한 실측 소스(절대경로)
- `C:\Users\WONBUI~1\AppData\Local\Temp\claude\D--claude-project---------\29597d24-b606-4fe4-9f59-d8500727a2cf\scratchpad\census.json`, `census_summary.txt`
- `D:\claude_project\데일리 작업로그\.scripts\daily_worklog.sh`, `scan_changes.sh`, `git_push.sh` (토큰격리·에러마스킹 패턴은 `git_push.sh:10,14,20,36`에서 직접 계승)
- 원본 JSONL 직접 검증: `C:\Users\wonbuilding\.claude\projects\D--claude-project-Building-scope\4e9d5eba-2877-4561-9b73-cb3a84baeac2.jsonl` 등 상위 5개 파일(uuid 중복·content 발산·tool_use_id 100% 커버리지 실측)
