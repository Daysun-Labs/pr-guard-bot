"""Hermes PR Guard adapter package.

The adapter is intentionally separate from the `pr_guard` CLI package: the CLI
runs inside GitHub Actions, while this package runs near a Hermes API Server and
turns strict PR Guard proposal requests into bounded JSON responses.
"""

from .core import AdapterConfig, ForbiddenRequest, InMemoryIdempotencyCache, ProposalService

__all__ = [
    "AdapterConfig",
    "ForbiddenRequest",
    "InMemoryIdempotencyCache",
    "ProposalService",
]
