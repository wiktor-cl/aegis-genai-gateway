from aegis.governance.secrets import find_secrets


def test_detects_aws_access_key() -> None:
    hits = find_secrets("here is the key AKIAABCDEFGHIJKLMNOP for the demo")
    assert any(h.kind == "aws_access_key" for h in hits)


def test_detects_private_key_block() -> None:
    hits = find_secrets("-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----")
    assert any(h.kind == "private_key_block" for h in hits)


def test_detects_generic_api_key_assignment() -> None:
    # Deliberately not shaped like any real vendor's key prefix (e.g. Stripe's
    # sk_live_...) so this fixture doesn't itself trip secret-scanning tools.
    hits = find_secrets('api_key: "not_a_real_credential_just_test_fixture_data"')
    assert any(h.kind == "generic_api_key_assignment" for h in hits)


def test_detects_jwt_like_string() -> None:
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ-abc123"
    hits = find_secrets(f"token={token}")
    assert any(h.kind == "jwt_like" for h in hits)


def test_benign_text_has_no_hits() -> None:
    hits = find_secrets("The weather today is sunny with a high of 22C.")
    assert hits == []
