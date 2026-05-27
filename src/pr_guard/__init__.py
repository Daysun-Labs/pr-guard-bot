"""pr-guard — PRD/SEED consistency gate for AI-generated pull requests.

PR 이벤트를 받아 PRD.md + SEED.md와 대조하여 drift를 감지하고
분류된 수정 PR을 생성하는 봇.

See SEED.yaml for the canonical specification.
"""

__version__ = "0.1.0"
