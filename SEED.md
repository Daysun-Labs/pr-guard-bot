# SEED — pr-guard-bot

> **SEED (Specification & Engineering Definition)** — 봇이 *어떻게*
> 구현되어야 하는지의 명세. 봇은 PR diff가 이 명세의 제약·인수조건과
> 모순되지 않는지 검증한다. (PRD가 의도, SEED가 구현 명세)
>
> 정식 기계 판독 버전은 `SEED.yaml` 참조.

## 아키텍처

```
GitHub PR event (pull_request opened/synchronize)
        ↓
GitHub Actions runner (Python >= 3.12, pip install ouroboros-ai[claude])
        ↓
src/pr_guard/main.py
  ├─ 1) Fetch PR metadata (gh CLI / GitHub API)
  ├─ 2) Load PRD.md + SEED.md (or detect absent → onboarding PR)
  ├─ 3) Compute PR diff
  ├─ 4) ooo evaluate (L1: PR ↔ PRD/SEED 의미 정합성)
  ├─ 5) Classify drift: prd-violation | seed-violation | none
  ├─ 6) Generate fix PR proposal (kind: code | seed)
  └─ 7) Notify: PR comment + Slack incoming-webhook
        ↓
GitHub (코멘트 추가, 별도 수정 PR 생성)
```

## 핵심 제약

- **언어/런타임**: Python >= 3.12 (Ouroboros 호환)
- **호스팅**: GitHub Actions only — 서버/VPS/Cloud Run 금지
- **의존성**: `ouroboros-ai[claude]`, `claude-agent-sdk`, `httpx`, `pyyaml`
- **권한 모델**: GitHub App이 아닌 `GITHUB_TOKEN` + `contents: write` + `pull-requests: write`
- **비파괴**: 원본 PR을 절대 force-push/edit 하지 않음
- **단일 사용자**: 멀티테넌트·계정 시스템·결제 일체 금지

## 인수 조건 (DoD)

1. `pull_request: opened` 이벤트에 GH Action이 자동 트리거
2. PRD.md+SEED.md 존재 리포: ≤5분 내 PR 코멘트 + Slack 알림
3. PRD/SEED 없는 리포: 안내 코멘트 ("ooo interview 실행하세요")
4. drift 감지 시:
   - PRD 위반 → 브랜치 `pr-guard/code-fix/<PR번호>`에 코드 수정 PR
   - SEED 위반 → 브랜치 `pr-guard/seed-fix/<PR번호>`에 SEED 수정 PR
5. 수정 PR은 원본 PR을 mention (`Fixes drift in #<PR번호>`)
6. 모든 동작은 Slack incoming-webhook 알림과 함께
7. Action 실행 로그가 GitHub Actions UI에서 디버그 가능

## 인터페이스

### CLI (로컬 테스트)

```bash
python -m pr_guard \
  --repo owner/name \
  --pr-number 42 \
  --prd PRD.md \
  --seed SEED.md \
  --slack-webhook $SLACK_WEBHOOK_URL
```

### GitHub Action 입력

```yaml
- uses: ./.github/actions/pr-guard
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Oracle 진화 단계

| 레벨 | 검증 방식 | MVP 포함? |
|---|---|---|
| L1 | 정적 — PR 설명·diff ↔ PRD/SEED 의미 정합성 (LLM 기반) | ✅ |
| L2 | + PRD 인수조건을 자동 테스트로 변환 후 PR 브랜치에서 실행 | ⏸ 사용하며 도입 |
| L3 | + 프리뷰 환경 배포 → Playwright로 시나리오 자동 클릭 | ⏸ |

## Fix PR 분류 규칙

```
if drift.source == "prd":
    # 의도와 어김 — 코드를 의도에 맞추는 것이 옳음
    kind = "code-fix"
    branch = f"pr-guard/code-fix/{pr_number}"
elif drift.source == "seed":
    # 구현 명세와 어김 — 어느 쪽이 옳은지 사용자가 결정
    # 기본 가정: PR이 진화의 신호 → SEED 업데이트 제안
    kind = "seed-fix"
    branch = f"pr-guard/seed-fix/{pr_number}"
else:
    kind = None  # 알림만, 수정 PR 없음
```

## 비-목표

- 자체 lint·formatting·style 규칙
- 보안 스캔 (Dependabot·CodeQL이 함)
- 성능 벤치마크
- 배포 자동화

## 의존하는 외부 시스템

| 시스템 | 용도 | Failover |
|---|---|---|
| GitHub Actions | 호스팅·트리거 | 없음 (core dep) |
| GitHub API | PR 메타·코멘트·수정 PR | retry with backoff |
| Slack incoming webhook | 알림 | 실패 시 PR 코멘트만 |
| Anthropic API | LLM 분석 | 실패 시 mechanical-only 분석 |

## Open Implementation Questions

- L1 분석을 `ooo evaluate` MCP 호출로 할지, Python SDK 직접 호출로 할지
- 동일 PR에 여러 차례 push 시 봇 응답이 누적되지 않도록 hide-outdated 처리
- 봇 자신의 PR을 봇 자신이 검증할 때의 무한 루프 방지 (label `pr-guard:skip` 등)
