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
    ↓ ooo evaluate (L1: 정적 PR ↔ PRD/SEED 정합성)
Drift / 오구현 / 미구현 판정
    ↓
├─ PR 코멘트 (요약 + 발견사항)
├─ Slack 알림 (incoming webhook)
└─ "수정 PR" 자동 생성
   · PRD 어김 → code-fix PR
   · SEED 어김 → seed-fix PR
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
| 4 | `pr_guard/main.py` — `ooo evaluate` 호출 로직 구현 | 본인 + 봇 (dogfood) |
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

## 라이선스

Personal use only. 공개·배포 계획 없음.
