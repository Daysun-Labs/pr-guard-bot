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

## 비-목표 (이 봇이 의도적으로 하지 않는 것)

- 코딩 중 실시간 알림 / 인터럽트
- Universal lint·style 규칙 강제
- 자동 머지·자동 배포
- Multi-tenant·SaaS화·과금
- 봇이 만드는 제품의 비즈니스 모델 결정

## 성공 기준 (이 봇 자체의)

| # | 기준 | 측정 방법 |
|---|---|---|
| 1 | 봇이 PR에 5분 내 응답 | 임의 리포 PR 생성 → Slack 알림 도착 시각 |
| 2 | drift 감지 시 분류된 수정 PR 생성 | 의도적 drift PR 시나리오 30개 중 ≥27개 정확 분류 |
| 3 | PRD/SEED 없는 리포에 안내 PR 생성 | 빈 리포 PR → "ooo interview 실행" 코멘트 |
| 4 | 30일 정착 | 본인의 모든 제품 리포 PR이 이 봇을 통과 |

## 규모 가정

- 봇 사용자: 1 (본인)
- 봇이 watch 하는 리포: 5~20개 (본인의 사이드/프로덕트들)
- 처리량: 일 평균 PR 0~10건
- 응답 SLA: 5분 (GitHub Actions cold start 포함)
- 비용: GitHub Actions 무료 티어 + Slack 무료 + LLM 토큰 비용만

## 봇과 Ouroboros의 관계

봇은 Ouroboros의 **GitHub adapter**:
- 봇 자체는 이벤트 어댑터 + UX wrapper일 뿐
- 핵심 분석은 `ooo evaluate` (3-stage 파이프라인) 재사용
- 인터뷰는 `ooo interview` 재사용
- 신규 리포의 첫 PRD/SEED는 `ooo seed`로 생성

## Open Questions (운영하며 결정)

- 봇 인터뷰 채널: Slack DM 우선이지만 Hermes/Codex와의 연동 필요 여부
- L2 (자동 테스트 실행) oracle 도입 시점
- 봇 자신의 PR drift는 누가 검증하는가 (자기 자신? Ouroboros core?)
