from aegis.governance.pii import find_pii, redact


def test_finds_email() -> None:
    hits = find_pii("contact me at jane.doe@example.com please", ["email"])
    assert len(hits) == 1
    assert hits[0].entity == "email"
    assert hits[0].match == "jane.doe@example.com"


def test_finds_phone() -> None:
    hits = find_pii("call 555-123-4567 now", ["phone"])
    assert len(hits) == 1
    assert hits[0].entity == "phone"


def test_valid_credit_card_via_luhn() -> None:
    # 4111 1111 1111 1111 is a well-known Luhn-valid test Visa number
    hits = find_pii("card: 4111111111111111", ["credit_card"])
    assert len(hits) == 1


def test_invalid_credit_card_like_number_is_not_flagged() -> None:
    # 16 digits but fails Luhn -- should not be treated as a real card number
    hits = find_pii("id: 1234567890123456", ["credit_card"])
    assert hits == []


def test_ssn_like_pattern() -> None:
    hits = find_pii("ssn 123-45-6789 on file", ["ssn_like"])
    assert len(hits) == 1


def test_no_entities_requested_means_no_hits() -> None:
    hits = find_pii("jane.doe@example.com", [])
    assert hits == []


def test_redact_replaces_matches_and_keeps_surrounding_text() -> None:
    text = "email jane@example.com now"
    hits = find_pii(text, ["email"])
    redacted = redact(text, hits)
    assert redacted == "email [REDACTED_EMAIL] now"


def test_redact_multiple_hits_from_right_to_left_keeps_indices_valid() -> None:
    text = "a@b.com and c@d.com"
    hits = find_pii(text, ["email"])
    redacted = redact(text, hits)
    assert redacted == "[REDACTED_EMAIL] and [REDACTED_EMAIL]"
