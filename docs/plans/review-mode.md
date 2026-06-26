<!-- audience: agent -->
# pr-guard-bot 개선 계획 — "drift 검출기"에서 "drift + 일반 리뷰 + 루프"로

> 한 줄 요약: pr-guard-bot에 **일반 코드 리뷰(버그·보안·품질) 패스**와 **grep-loop형 자동 수정 루프**를 추가해, **Greptile/Vercel Agent Review 유료를 본인이 이미 내는 크레딧(Hermes/Anthropic/ChatGPT)으로 대체**한다. SEED 제약(personal·async·no force-push·no hardcoded bar)은 그대로 지킨다.

작성 2026-06-26 · 대상 repo: `Daysun-Labs/pr-guard-bot` · 근거: 실제 소스(`src/pr_guard/*`)·`SEED.yaml` 직접 확인.

---

## 1. 현재 상태 (확인됨)

pr-guard-bot은 **PR diff ↔ PRD/SEED 정합성(drift) 검출기**다.
- 흐름(`src/pr_guard/main.py`): diff 추출 → `detect_drift` → `filter_actionable_drift` → `select_blocking_drift_decisions` → 안정 마커 코멘트(`<!-- pr-guard:drift-report -->`) + `_maybe_generate_fix_prs`.
- LLM 추상화(`src/pr_guard/llm_provider.py`): `LLMProvider` Protocol = `generate_seed_fix` / `generate_code_fix_proposal` / `classify_blocking_drift`. 구현 2개: `AnthropicProvider`(직접 SDK), `HermesWebhookProvider`(Hermes webhook). 즉 **LLM 호출·fix-PR·마커 코멘트·GitHub 클라이언트 인프라가 이미 다 있다.**
- oracle 레벨 L1~L3 개념 존재(`oracle_l1_report.py`, SEED `oracle_level_used`).
- SEED 제약: 단일 사용자 personal tool · **봇은 성공 기준 hardcode 안 함(per-repo PRD/SEED만)** · PR Guard = Required Check · Hermes는 webhook 설정 시에만 · **원본 PR force-push 금지(마커 코멘트 또는 별도 fix-PR만)** · **async PR-after만(실시간 인터럽트 금지)**.

## 2. 갭 (왜 Greptile/Vercel을 못 대체하나)

drift 검출은 "스펙대로 만들었나"만 본다. **일반 버그·보안·trust-boundary·성능·품질 리뷰는 없다** — 그게 Greptile/Vercel Agent Review의 역할이다. 영상의 grep-loop(=Greptile 리뷰가 5/5 될 때까지 자동 수정)도 이 일반 리뷰에 의존한다. **이 한 갈래만 추가하면 pr-guard-bot이 둘 다 한다.**

## 3. 개선 설계 — 3개 기능

### F1. 일반 리뷰 패스 (Greptile/Vercel-Agent 대체 핵심)
- **`LLMProvider`에 4번째 메서드 추가**: `review_diff(diff, repo_context) -> ReviewReport`.
  - `ReviewReport` = `{ findings: [{category: bug|security|trust_boundary|perf|quality, severity, file, line, quote, suggestion}], score: 0..5, summary }`. (Greptile의 5/5 점수를 미러)
  - `AnthropicProvider`·`HermesWebhookProvider` 양쪽 구현. 프롬프트는 "이 diff에서 버그·보안·trust-boundary 위반·과잉복잡도를 찾아라. 스펙 일치(drift)는 별도이므로 제외."
- **`main.py`에 review 패스 추가**, 플래그 `--review`(opt-in)로 켠다. drift 패스와 **병렬/독립**.
- **별도 마커 코멘트** `<!-- pr-guard:review-report -->`에 findings + `score N/5` 렌더(`comment_format.py` 패턴 재사용). drift 코멘트와 분리해 둘 다 안정 업데이트.
- **bar 미하드코딩 준수**: 일반 리뷰는 기본 **advisory(non-blocking)**. 단 `category=security`만 opt-in `--fail-on-security`로 blocking 가능. 리뷰 기준을 repo의 `AGENTS.md`/표준에서 끌어오면 "per-repo bar" 원칙과도 합치(있으면 repo_context에 주입).

### F2. 자동 수정 루프 (grep-loop 대체)
영상의 grep-loop = 리뷰 읽기 → 수정 push → 재리뷰 → 5/5까지 반복. SEED 제약(async·no force-push) 안에서 두 경로:
- **이벤트 구동(권장, CI 네이티브)**: review 패스가 finding마다 `_maybe_generate_fix_prs` 재사용해 **fix-PR 제안**. fix를 적용/머지하면 다음 `synchronize` 이벤트에서 pr-guard가 재실행 → score 재계산. 즉 **PR 이벤트 자체가 루프**가 된다. 새 인프라 거의 불필요.
- **로컬 스킬(선택, grep-loop와 동형)**: `/pr-guard-loop <PR#>` 스킬 — pr-guard의 `review-report` 코멘트를 읽고(Greptile 대신), 수정 push, 재리뷰 대기, `score >= 임계(기본 4/5)` 또는 N회(기본 5)까지 반복. **로컬에선 Codex/Claude(구독 토큰)로 수정**하므로 추가 비용 없음.
- **폭주 방지**: 루프 최대 횟수 캡(기존 `PR_GUARD_MAX_FIX_PRS` 패턴 차용), 동일 finding 재제안 금지(해결 추적).

### F3. 제약·안전 (SEED 준수 자동 점검)
- 원본 PR 직접 수정 금지 → fix-PR/마커 코멘트만(기존 그대로).
- async PR-after만 → 실시간 인터럽트 없음(기존 그대로).
- 일반 리뷰는 advisory 기본 → "no hardcoded production bar" 유지.
- LLM 비용 = Hermes webhook(권장) 또는 `ANTHROPIC_API_KEY` fallback = **본인 크레딧**. 새 SaaS 구독 0.

## 4. 구현 단위 (PR 크기로 분할)

| # | PR | 손대는 파일 | 산출 |
|---|---|---|---|
| 1 | `review_diff` provider 메서드 + 스키마 | `llm_provider.py`, (신규) `review.py`, `tests/test_llm_provider.py` | 일반 리뷰 LLM 호출 + ReviewReport 타입 |
| 2 | review 패스 + `--review` 플래그 + 마커 코멘트 | `main.py`, `comment_format.py`, `tests/test_main_cli_gate.py` | `--review`로 score N/5 코멘트 게시 |
| 3 | review → fix-PR 제안 연결 | `fix_pr.py`/`patcher.py` 재사용, `main.py` | finding별 fix-PR(advisory) |
| 4 | (선택) `/pr-guard-loop` 로컬 스킬 | 신규 SKILL.md (pr-guard-bot 밖, 본인 ~/.claude/skills) | grep-loop 동형 루프 |
| 5 | astate-brain 적용 | `astate-brain/.github/workflows/pr-guard.yml`에 `--review`(advisory) 추가 | 실 PR에서 일반 리뷰 자동화 |

각 PR은 pr-guard-bot 자체 게이트(자기 PRD/SEED + tests)를 통과해야 머지.

## 5. 대체 범위 (정직)

| 항목 | pr-guard-bot 확장으로 | 비고 |
|---|---|---|
| Greptile 일반 리뷰 | ✅ 대체 | review 패스가 동일 역할, 본인 크레딧 |
| grep-loop(5/5 루프) | ✅ 대체 | F2 이벤트 구동 또는 로컬 스킬 |
| Vercel **Agent Review**(AI 리뷰) | ✅ 대체 | review 패스 |
| Greptile 전체-레포 그래프 컨텍스트 | △ 근접 | `repo_context`에 codegraph/repomap 주입 시 근접, 완전 동일 X |
| Vercel **프리뷰 배포**(라이브 URL) | ❌ 불가 | 호스팅 인프라 — 리뷰 아님. Cloudflare Pages/Netlify 무료 등 별도 |

## 6. 검증 (DONE WHEN)
- 의도적으로 버그/보안 결함 심은 PR → `--review`가 finding + score를 코멘트로 게시.
- 깨끗한 PR → score 5/5, blocking 없음.
- security finding + `--fail-on-security` → 체크 fail.
- pr-guard-bot tests green + astate-brain PR에서 review 코멘트 실측.

## 7. 다음 액션
1. 이 계획을 pr-guard-bot `docs/plans/review-mode.md`로 커밋 + GitHub 이슈화.
2. PR #1(provider 메서드)부터 2-모델 루프로 구현(Opus 설계·리뷰 + Codex 실행).
3. astate-brain `pr-guard.yml`에 `--review`(advisory) 켜기.

## 8. PR #33 리뷰 반영 (Codex)
- **#1 Hermes 어댑터 `task:"review"` 미지원** — `HermesWebhookProvider.review_diff`가 `task:"review"`를 POST하지만 번들 어댑터(`adapter/pr_guard_adapter/core.py`)는 `seed_fix`/`code_fix`/`blocking_drift_classification`만 처리 → Hermes 경로 리뷰는 UNKNOWN으로 떨어진다. **슬라이스 1b로 분리**: 어댑터에 review 핸들러 추가. (현재 PR은 provider-only 범위라 의도적으로 제외. Anthropic 직접 경로는 동작.)
- **#2 score 누락 시 UNKNOWN** — `findings`는 있고 `score`가 빠진 응답을 3/5로 보고하던 것을 `UNKNOWN_SCORE`로 수정(루프/코멘트 오판 방지). 테스트 추가.

## 9. 핵심 발견 — 구독으로 일반 리뷰는 이미 가능
- **Codex GitHub 리뷰**(`chatgpt-codex-connector`)가 ChatGPT 구독 트랙으로 PR을 이미 자동 리뷰(API 키 불필요; 클라우드/GitHub 기능은 구독 전용, API 키 모드는 제거됨). → Greptile/Vercel-Agent의 일반 리뷰는 **이미 구독으로 대체됨**. pr-guard-bot review-mode는 "결정적·repo-제어·score 게이트"가 필요할 때의 보완재.
- pr-guard-bot 자체 LLM(드리프트/리뷰)은 Hermes webhook 또는 `ANTHROPIC_API_KEY`(과금). 구독을 쓰려면 Hermes를 구독-백엔드로 라우팅하거나, 별도로 Claude Max `CLAUDE_CODE_OAUTH_TOKEN`(`claude-code-action`) 경로를 쓴다.
