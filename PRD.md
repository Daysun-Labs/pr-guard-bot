# PRD — pr-guard-bot

> **PRD (Product Requirements Document)** — 봇이 *왜* 존재하고
> *누구를 위해* 무엇을 해주는지의 의도 명세.
> 봇은 PR 검증 시 이 문서의 의도와 PR diff를 의미적으로 대조한다.

## 한 줄 정의

본인이 AI 코딩 도구로 Vibecoding 하면서도 만드는 모든 제품이
*그 제품의 PRD/SEED가 정의한* Production 기준을 충족하도록
GitHub PR 단위로 검증·교정해주는 personal 봇.

## 타겟 사용자

- 본인 1명 (자칭 "비개발자 인디 메이커")
- 도구 무관 — Claude Code · Codex · Hermes Agent 등을 자유 이동
- "MAU 10K 규모의 Production 제품"을 다수 만들고 싶어함

## 가치 제안

| 기존 페인 | 봇이 해결하는 방식 |
|---|---|
| AI가 만든 코드가 의도와 어긋나도 알아채기 어려움 | PRD/SEED 대비 drift 자동 감지 |
| 도구를 바꿀 때마다 검증 워크플로우가 달라짐 | GitHub PR이라는 도구-무관 단일 게이트 |
| 실시간 개입은 vibe(흐름)를 깨뜨림 | 비동기 PR-after 동작만 |
| 수정 제안이 원본을 망쳐버림 | "수정 PR"을 별도 생성, 원본 미변경 |
| 봇의 universal 기준이 내 제품 의도와 맞지 않음 | 자체 기준 없음, per-repo PRD/SEED 기반만 |

## 공개 배포 포지션

`pr-guard-bot`은 public repository로 유지하되, 아직 대외 홍보 전인 dogfood-stage 개발자 도구다. 공개 상태의 목적은 다른 Hermes/DS 리포가 특정 commit SHA 또는 release tag로 안전하게 pin해서 쓰기 쉽게 만드는 것이다.

공개 repo로 운영하는 동안 기본 workflow는 fork PR에서 secrets/write side effect를 쓰지 않고 artifact-only로 동작해야 하며, 자동 fix PR 생성은 trusted same-repository PR에서만 명시적 opt-in으로 허용한다.

## 비-목표 (이 봇이 의도적으로 하지 않는 것)

- 코딩 중 실시간 알림 / 인터럽트
- Universal lint·style 규칙 강제
- 자동 머지·자동 배포
- Multi-tenant·SaaS화·과금
- 봇이 만드는 제품의 비즈니스 모델 결정

## 성공 기준 (이 봇 자체의)

| # | 기준 | 측정 방법 |
|---|---|---|
| 1 | 봇이 PR에 5분 내 응답하고 PR Guard 코멘트와 Slack incoming-webhook 알림을 게시 | 임의 리포 PR 생성 → GitHub Actions 로그, PR 코멘트, Slack 알림 도착 시각 |
| 2 | drift 감지 시 구조화된 pr-guard-report.json, 분류된 PR 코멘트, fail-on-drift 종료코드가 일관됨 | 의도적 drift PR 시나리오에서 JSON verdict=fail, drift_count ≥1, Action 실패 확인 |
| 3 | Hermes webhook이 설정되면 Hermes Agent가 code-fix 또는 seed-fix 수정 PR 생성을 제안·대행 | HERMES_PR_GUARD_WEBHOOK_URL/TOKEN 설정 후 provider 호출과 fix PR 링크 확인 |
| 4 | PRD/SEED 없는 리포에 안내 PR 또는 안내 코멘트 생성 | 빈 리포 PR → "ooo interview 실행" 안내 확인 |
| 5 | 30일 정착 | 본인의 모든 제품 리포 PR이 PR Guard 파이프라인을 통과 |

## 규모 가정

- 봇 사용자: 1 (본인)
- 봇이 watch 하는 리포: 5~20개 (본인의 사이드/프로덕트들)
- 처리량: 일 평균 PR 0~10건
- 응답 SLA: 5분 (GitHub Actions cold start 포함)
- 비용: GitHub Actions 무료 티어 + Slack 무료 + Hermes/LLM 토큰 비용만

## 봇과 Hermes/Ouroboros의 관계

봇은 GitHub Actions에서 deterministic PR Guard 게이트를 실행하고,
선택적 semantic/fix 단계는 Hermes Agent webhook 뒤로 위임한다.

- GitHub Actions는 PR diff, PRD.md, SEED.md, SEED.yaml을 읽고 정적 drift report를 만든다.
- Hermes Agent는 webhook provider로 붙어 code-fix 또는 seed-fix 제안을 생성할 수 있다.
- Ouroboros는 Hermes 뒤의 선택적 semantic/evaluation engine으로 재사용한다.
- 신규 리포의 첫 PRD/SEED는 여전히 `ooo interview` / `ooo seed`로 만들 수 있다.

## Open Questions (운영하며 결정)

- 봇 인터뷰 채널: Slack DM 우선이지만 Hermes/Codex와의 연동 필요 여부
- L2 (자동 테스트 실행) oracle 도입 시점
- 봇 자신의 PR drift는 누가 검증하는가 (자기 자신? Ouroboros core?)
