# SEED — pr-guard-bot

> **SEED (Specification & Engineering Definition)** — 봇이 *어떻게*
> 구현되어야 하는지의 명세. 봇은 PR diff가 이 명세의 제약·인수조건과
> 모순되지 않는지 검증한다. 정식 기계 판독 버전은 `SEED.yaml` 참조.

## 아키텍처

```
GitHub PR event (pull_request opened/synchronize)
        ↓
GitHub Actions runner (Python >= 3.12, pip install -e .)
        ↓
src/pr_guard/main.py
  ├─ 1) Fetch PR metadata (GitHub API / GITHUB_TOKEN)
  ├─ 2) Load PRD.md + SEED.md + SEED.yaml (or detect absent → onboarding)
  ├─ 3) Compute PR diff
  ├─ 4) Static PR Guard report (PR ↔ PRD/SEED structural alignment)
  ├─ 5) Classify actionable drift and write pr-guard-report.json
  ├─ 6) Optional Hermes Agent webhook provider generates code-fix/seed-fix proposals
  └─ 7) Notify: marker-based PR comment + Slack incoming-webhook
        ↓
GitHub (코멘트 업데이트, 선택적 별도 수정 PR 생성)
```

## 핵심 제약

- **언어/런타임**: Python >= 3.12, package `pr_guard`, dependency `httpx` only for the default static gate
- **호스팅**: GitHub Actions required for the PR Guard check; Hermes/Ouroboros are optional remote providers behind webhook secrets
- **의존성**: default path uses `httpx`; optional legacy fallback may use `anthropic`; Ouroboros runs only behind Hermes when configured
- **권한 모델**: 기본 workflow는 `contents: read` + `pull-requests: write` + `issues: write`; `contents: write`는 trusted same-repository PR에서 자동 fix PR/onboarding PR을 명시적으로 켤 때만 허용
- **public fork 안전성**: fork PR은 secrets/write 권한 없이 `--no-publish` artifact-only 모드로 실행
- **비파괴**: 원본 PR을 절대 force-push/edit 하지 않고 marker comment 업데이트 또는 별도 수정 PR만 생성
- **단일 사용자**: 멀티테넌트·계정 시스템·결제 일체 금지

## 인수 조건 (DoD)

1. `pull_request: opened` 및 `pull_request: synchronize` 이벤트에 GitHub Actions PR Guard job이 자동 트리거
2. PRD.md+SEED.md 존재 리포: trusted same-repository PR에서는 5분 내 marker-based PR 코멘트 + 선택적 Slack incoming-webhook 알림
3. public fork PR: `--no-publish` artifact-only 모드로 실행되어 secrets/write side effect 없이 `pr-guard-report.json`과 check verdict만 생성
4. PRD/SEED 없는 리포: onboarding 안내 코멘트 또는 안내 PR 생성
5. drift 감지 시 `pr-guard-report.json`에 `schema_version`, `verdict`, `drift_count`, `drifts`, `suppressed`, `fix_prs` 기록
6. `--fail-on-drift` 사용 시 actionable drift가 1건 이상이면 GitHub Actions check가 실패
7. Hermes webhook provider 설정 시 PRD 위반은 code-fix, SEED 위반은 seed-fix 수정 PR 제안을 생성
8. 수정 PR은 원본 PR을 mention (`Fixes drift in #<PR번호>`)
9. 모든 publish 동작은 원본 PR에 marker comment를 업데이트하고 Slack incoming-webhook 알림과 함께 실행
10. Action 실행 로그와 uploaded artifact `pr-guard-report.json`이 GitHub Actions UI에서 디버그 가능

## 인터페이스

### CLI (로컬 테스트)

```bash
python -m pr_guard \
  --repo owner/name \
  --pr-number 42 \
  --base-ref main \
  --head-ref feature \
  --json-output pr-guard-report.json \
  --no-publish
```

### GitHub Action 환경 변수

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
  HERMES_PR_GUARD_WEBHOOK_URL: ${{ secrets.HERMES_PR_GUARD_WEBHOOK_URL }}
  HERMES_PR_GUARD_WEBHOOK_TOKEN: ${{ secrets.HERMES_PR_GUARD_WEBHOOK_TOKEN }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }} # optional legacy fallback
  PR_GUARD_MAX_FIX_PRS: ${{ vars.PR_GUARD_MAX_FIX_PRS || '0' }} # public-safe default
```

## Oracle 진화 단계

| 레벨 | 검증 방식 | MVP 포함? |
|---|---|---|
| L1 | 정적 — PR diff ↔ PRD/SEED 구조·토큰 정합성 + JSON report | ✅ |
| L1.5 | Hermes Agent webhook semantic/fix provider | ✅ optional |
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
| GitHub Actions | 호스팅·트리거·Required Check | 없음 (core dep) |
| GitHub API | PR 메타·코멘트·수정 PR | retry with backoff |
| Slack incoming webhook | 알림 | 실패 시 PR 코멘트만 |
| Hermes Agent webhook | semantic/fix provider | 없으면 static report-only |
| Anthropic API | legacy LLM fallback | 없으면 Hermes/static-only |

## Open Implementation Questions

- L2 분석을 `ooo evaluate` MCP 호출로 할지, Hermes provider 내부에서 실행할지
- 동일 PR에 여러 차례 push 시 봇 응답이 누적되지 않도록 hide-outdated 처리할지 marker update만 유지할지
- 봇 자신의 PR을 봇 자신이 검증할 때의 무한 루프 방지 (label `pr-guard:skip` 등)
