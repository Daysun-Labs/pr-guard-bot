# pr-guard-bot

**Personal Ouroboros GitHub adapter** — 본인이 다양한 AI 코딩 도구로
Vibecoding 하면서도 만드는 모든 제품이 Production 수준에 도달하도록
GitHub PR 단위로 검증·교정해주는 봇.

> 본 리포는 봇의 첫 dogfooding 케이스이기도 합니다. 자기 자신의
> `PRD.md` + `SEED.md` + `SEED.yaml`을 가지고 있어, 향후 PR이
> 올라오면 봇 자신이 자신을 검증합니다.

## 무엇을 하는가

```
GitHub PR event
    ↓ webhook
GitHub Actions (이 봇)
    ↓ 정적 PR ↔ PRD/SEED 정합성 게이트
Drift / 오구현 / 미구현 판정
    ↓
├─ Required check: drift가 남으면 실패
├─ pr-guard-report.json (CI artifact / 기계 판독)
├─ PR 코멘트 (요약 + 발견사항)
├─ Slack 알림 (incoming webhook)
└─ "수정 PR" 자동 생성
   · PRD 어김 → code-fix proposal PR
   · SEED 어김 → seed-fix PR
   · Hermes webhook 우선, Anthropic API key는 legacy fallback
```

## 무엇을 하지 않는가

- 원본 PR을 직접 수정하지 않음 (모든 수정은 별도 PR로)
- 코딩 중 실시간 개입하지 않음 (vibe 보호)
- 자체 "production 기준"을 hardcode 하지 않음 (per-repo PRD/SEED만 봄)
- 멀티테넌트·SaaS·결제·온보딩 흐름 일체 없음 (personal use)

## 디렉토리 구조

```
pr-guard-bot/
├── README.md                          ← 지금 보고 있는 파일
├── PRD.md                             ← 봇 자체의 제품 정의 (사람용)
├── SEED.md                            ← 봇 자체의 구현 명세 (사람용)
├── SEED.yaml                          ← 정식 Ouroboros seed (기계용)
├── pyproject.toml                     ← Python 패키지 설정
├── .github/
│   └── workflows/
│       └── pr-guard.yml               ← GH Action skeleton
└── src/
    └── pr_guard/
        ├── __init__.py
        └── main.py                    ← entrypoint skeleton
```

## 다음 단계 (구현 로드맵)

| 단계 | 작업 | 책임 |
|---|---|---|
| 1 | `gh repo create pr-guard-bot --private` | 본인 |
| 2 | 이 디렉토리 내용을 신규 리포에 push | 본인 |
| 3 | Slack incoming webhook 생성, `SLACK_WEBHOOK_URL` secret 등록 | 본인 |
| 4 | 선택/권장: Hermes webhook endpoint 생성 후 `HERMES_PR_GUARD_WEBHOOK_URL` secret 등록 | 본인 + Hermes |
| 5 | 본인의 다른 리포 하나에 PRD.md+SEED.md 추가하고 첫 PR로 검증 | 본인 |

## 첫 사용

```bash
# 1) 새 리포에 PRD/SEED 부트스트랩
cd <your-other-repo>
ooo interview "이 제품의 의도와 명세를 정의하고 싶다"
ooo seed                 # → PRD.md + SEED.md 첫 PR 생성

# 2) 그 리포의 .github/workflows에 pr-guard.yml 복사
cp /path/to/pr-guard-bot/.github/workflows/pr-guard.yml \
   .github/workflows/

# 3) 다음 PR부터 자동 검증
```

## CI 게이트 모드

`pr-guard`는 이제 GitHub Required Check로 쓸 수 있는 구조화 리포트를 냅니다.

```bash
python -m pr_guard \
  --repo "$REPO" \
  --pr-number "$PR_NUMBER" \
  --base-ref "$BASE_REF" \
  --head-ref "$HEAD_REF" \
  --json-output pr-guard-report.json \
  --fail-on-drift
```

- `--json-output`: `schema_version`, `verdict`, `drifts`, `fix_prs`, `suppressed`를 포함한 기계 판독용 리포트 작성.
- `--fail-on-drift`: `verdict != pass`이면 non-zero exit로 Required Check를 실패시킴. 이 플래그를 빼면 기존처럼 advisory/comment bot으로 동작합니다.
- `--no-publish`: 로컬/테스트용 dry-run. GitHub 코멘트, Slack, onboarding PR, fix PR 생성을 모두 건너뜀.
- PR 코멘트는 `<!-- pr-guard:drift-report -->` marker가 있는 기존 코멘트를 업데이트합니다. 같은 PR에서 push가 반복되어도 새 코멘트를 계속 쌓지 않습니다.

GitHub에서 실제 Required Check로 쓰려면 repository settings → Branch protection rules → target branch → **Require status checks to pass before merging**에서 workflow job 이름 `PR Guard`를 required로 선택합니다. 검증은 테스트 PR에서 `PR Guard` check가 초록/빨강으로 보이는지, 실패 시 `pr-guard-report` artifact가 업로드되는지 확인하면 됩니다.

## Hermes / LLM 연동

fix PR 생성은 다음 순서로 provider를 고릅니다.

1. `HERMES_PR_GUARD_WEBHOOK_URL`: 권장 경로. Hermes가 연결된 OAuth/LLM 런타임에서 drift context를 받아 `{ "action": "update", "new_content": "...", "message": "...", "rationale": "..." }` 형태로 응답합니다. `HERMES_PR_GUARD_WEBHOOK_TOKEN`이 있으면 `Authorization: Bearer <token>` 헤더로 함께 전송합니다.
2. `ANTHROPIC_API_KEY`: 마지막 수단용 legacy fallback입니다. Daysun Labs 기본 운영에서는 직접 API key보다 Hermes webhook 경로를 우선합니다.
3. 둘 다 없으면 LLM fix PR 생성은 비활성화되고, 정적 drift 게이트/코멘트/Slack 알림만 수행합니다.

현재 Daysun Labs 설정에서는 `SLACK_WEBHOOK_URL`이 `C0B6XNQCYFJ` 채널로 향하도록 secret을 등록해 두면 PR-guard 알림이 해당 채널에 올라옵니다. Ouroboros는 DS 런타임에 설치되어 있어 PRD/SEED 작성·진단에는 유용하지만, GitHub Action 자체에는 필수 의존성으로 넣지 않습니다. 더 깊은 의미 평가가 필요하면 Hermes webhook 뒤에서 Ouroboros를 호출하는 방식이 안전합니다.

## 라이선스

Personal use only. 공개·배포 계획 없음.
