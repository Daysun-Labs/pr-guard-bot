import hashlib
import hmac

import pytest

from pr_guard.signature import (
    InvalidSignature,
    compute_signature,
    require_signature,
    verify_signature,
)


SECRET = "s3cr3t"
BODY = b'{"action":"opened"}'


def _valid_header(secret=SECRET, body=BODY):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_compute_signature_matches_hmac_sha256():
    assert compute_signature(SECRET, BODY) == _valid_header()


def test_compute_signature_accepts_bytes_secret():
    assert compute_signature(SECRET.encode(), BODY) == _valid_header()


def test_verify_valid_signature():
    assert verify_signature(SECRET, BODY, _valid_header()) is True


def test_verify_forged_signature():
    bad = "sha256=" + "0" * 64
    assert verify_signature(SECRET, BODY, bad) is False


def test_verify_wrong_secret():
    bogus = _valid_header(secret="other")
    assert verify_signature(SECRET, BODY, bogus) is False


def test_verify_tampered_body():
    assert verify_signature(SECRET, b'{"action":"closed"}', _valid_header()) is False


def test_verify_missing_header():
    assert verify_signature(SECRET, BODY, None) is False
    assert verify_signature(SECRET, BODY, "") is False


def test_verify_wrong_prefix():
    h = _valid_header().replace("sha256=", "sha1=")
    assert verify_signature(SECRET, BODY, h) is False


def test_verify_malformed_header():
    assert verify_signature(SECRET, BODY, "not-a-signature") is False


def test_require_signature_passes():
    require_signature(SECRET, BODY, _valid_header())


def test_require_signature_raises_on_forged():
    with pytest.raises(InvalidSignature):
        require_signature(SECRET, BODY, "sha256=" + "0" * 64)


def test_require_signature_raises_on_missing():
    with pytest.raises(InvalidSignature):
        require_signature(SECRET, BODY, None)
