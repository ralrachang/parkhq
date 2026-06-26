# Work OS — 다음 작업: 운영 점검대(Operations Board) 재설계

> 작성 시점: 2026-06-24. Phase 0 설계 + Phase 1a 적재(게이트 통과) + Phase 2 지표 대시보드 미리보기 완료 후,
> 사용자 피드백으로 대시보드 방향을 **재정의**함. 다음 세션은 이 문서에서 이어간다.

## 사용자 요구 (핵심 전환)
참고 이미지 `ex.jpg`("HAM MEDIA OS — 작업 전 점검대")처럼, 대시보드를 **프로젝트 운영 현황판**으로 재설계.
- **80%** = 내 프로젝트들이 **어떻게 운영되고 있는가** + **소외(방치)받는 프로젝트는 없는가**.
- **20%** = 기존 지표(토큰·비용·도구·일별추이) — 이미 `workos/dashboard.py`로 구현됨, 상단 스트립으로 축소.
- **그 위에** = 각 프로젝트를 **어떤 에이전트가 돌볼 것인가**(Hermes 유나/서연/하린) — 환경 조성.

## 참고 이미지(ex.jpg) 구조 — 우리가 모사할 레이아웃
- 헤더: OS명·버전 · "작업 전 점검대" · 생성시각 · 로컬 read-only 배지.
- 상단 집계 바: 전체 N · ▲민감 · ◆주의 · ●일반 · 점검필요 · 오늘 · 오래됨.
- **팀(카테고리)별 컬럼** → 각 프로젝트 = 카드 한 줄:
  `[플래그] 번호 이름 · 최근활동(오늘/3일/오래) · 상태(수정/승인/읽기) · 문서등급(A/B/C) · (정상/점검필요)`
- 하단: 본부문서(기준 원본), 시작일 타임라인(접기), 활용 팁(접기).

## 실데이터로 확인된 것 (workos.db 기준, now=2026-06-24)

### ⚠️ 선결 과제: 프로젝트 루트 롤업
현재 `workspaces`(cwd 정규화)는 **하위 폴더로 오염**됨(63개). `engine·cards·video·workos·scripts·_qa·
buildscope-mvp·marketing·output·...`은 진짜 프로젝트가 아니라 하위 디렉터리.
- **롤업 규칙**: `project = D:\claude_project\` 바로 아래 1차 세그먼트. builpago 경로(`D:\박창현…\builpago`)는 `builpago`로.
  → 모든 하위 cwd를 프로젝트 루트로 병합. 약 63 → **약 22개 실제 프로젝트**.
- **구현 위치**: `ingest.py`에 `project_id` 파생(workspaces에 컬럼 추가 또는 `projects` 테이블). 재적재 2분.
- 실제 프로젝트 루트 목록은 `ls D:\claude_project\` 1차 폴더 참고(AI PB·Building scope·diwolbu·builpago·
  wonbuilding AI TF·building sns·Auto IM2·Auto IM pptx·Taxpago·team ERP·worldcup dashboard·dungeon writer·
  remotion_youtube·notion work·korea-finance·kordoc·godot·ppt yoon·yangjae_NI·데일리 작업로그·매수고객관리·직원평가시스템 등).

### 운영 신호(이미 산출 가능) — `scratchpad/probe_ops.py`
프로젝트별로 계산됨(롤업 전 기준, 롤업 후 재계산 필요):
- **방치도**: 마지막 활동 경과일 → 오늘/3일/주간/2주/오래(14d+). (now = DB 전체 max(ts) 기준 — 시계 무관 견고)
- **추세**: 최근 14일 세션 vs 직전 14일 → ▲증가/▼감소/=정체.
- **문서등급**: 프로젝트 폴더에 README / CLAUDE·AGENTS / docs·specs 존재 여부 → A/B/C/없음.
- **현재 초점**: 가장 최근 `ai-title`(세션 자동제목).
- 세션·토큰·사람입력 수.

### 🔴 이미 보이는 '소외(방치)' 프로젝트 (롤업 전 잠정)
- **오래(15일+)**: Auto IM pptx(15d) · korea-finance(24d) · ppt yoon(22d) · yangjae_NI(27d) · 매수고객관리 · 직원평가시스템(28d).
- **2주·하락세(▼)**: notion work(14d↓) · remotion_youtube(14d) · team ERP(13d) · kordoc(12d).
- **활발(오늘)**: Building scope · diwolbu · builpago · building sns · wonbuilding AI TF · Auto IM2.

## 다음 세션 작업 계획
1. ~~`ingest.py`에 프로젝트 루트 롤업(`project_id`) 추가 → 재적재 → 게이트 재확인.~~
   ✅ **완료(2026-06-26)**: `derive_project()` 추가(컨테이너=`claude_project` 1차 세그먼트,
   외부 마커=`builpago`, 폴백=정규화 cwd 무손실). `records.project_id` 컬럼 + `projects` 테이블
   (id·name·root·n_workspaces·n_records·category·agent) 추가. `projects`는 `workspaces`처럼
   **DB 전체에서 재계산**(distinct cwd → 롤업) → 멱등·부분스캔 면역.
   재적재 결과 **workspaces 64 → projects 22**. 게이트에 G9a~d(롤업 정합) 추가, **16/16 ALL PASS**
   (멱등성 G4 포함, reuse가 fresh와 projects 22==22 동일). `category·agent`는 사용자 확정 대기(NULL).
2. `probe_ops.py` 로직을 프로젝트 단위로 재계산.
3. 새 생성기 `ops_board.py`(또는 dashboard.py 확장): 80% 운영 점검대 + 20% 지표 스트립.
   - 카테고리별 컬럼, 카드별 방치도/추세/문서/현재초점/상태 플래그.
   - 상단 집계: 전체 · 활발 · 식어감 · 방치 · 점검필요.
4. **에이전트-환경 레이어**(Phase 3 연결): 카드마다 `담당 에이전트` + `추천 액션`.

## 사용자 확정 필요(다음 세션 시작 시 질문)
1. **카테고리/팀 분류** (제안: 부동산·빌딩 / 제품·플랫폼 / 콘텐츠·실험 / 인프라·내부).
2. **프로젝트별 담당 에이전트 매핑** (제안: 서연 CSO→부동산·빌딩, 유나 CTO→제품·플랫폼·인프라, 하린 CLO→개인·투자·실험).
3. **방치 임계값** (며칠부터 '오래'·'방치'로 볼지).
4. **문서등급 기준** (A/B/C 정의).
5. **"환경 조성"의 구체화**: 방치 프로젝트에 어떤 에이전트 액션을 자동 제안할지(예: 재점화 브리프, 주간 점검).

## 현재 자산(오늘까지)
- `docs/00_design.md` — Phase 0 설계(승인됨).
- `workos/ingest.py` · `verify_gate.py` — Phase 1a 적재+게이트 + **프로젝트 루트 롤업**
  (**16/16 PASS**, G9a~d 추가, 적대적 검증 통과).
- `workos/dashboard.py` — Phase 2 지표 대시보드(→ 20% 스트립으로 재활용).
- `workos.db` `projects` 테이블 — **22개 프로젝트**(롤업 완료). 다음 단계 ops_board의 1차 입력.
  실측 분포(n_records): Building scope 71k · diwolbu 14.5k · building sns 10.8k · builpago 10.4k ·
  Auto IM pptx 9.5k · wonbuilding AI TF 9.0k · Auto IM2 7.1k · remotion_youtube 6.7k · team ERP 5.5k ·
  worldcup dashboard 5.4k · dungeon writer 4.7k · notion work · Taxpago · yangjae_NI · 데일리 작업로그 ·
  claude_project(루트 활동) · kordoc · 매수고객관리 · korea-finance · godot · ppt yoon · remember project.
- `workos/workos.db` — 적재 DB(gitignore, 로컬 전용).
- scratchpad: `census.py · probe_collision.py · probe_overmerge.py · probe_ops.py`(분석 스크립트, 재사용).
