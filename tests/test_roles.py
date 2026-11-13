from vnmacro import roles


def test_verdict():
    assert roles.verdict("ok", None)
    assert not roles.verdict("ok", roles.INSUFFICIENT_PRIVILEGE)
    assert roles.verdict("blocked", roles.INSUFFICIENT_PRIVILEGE)
    assert roles.verdict("blocked", roles.READ_ONLY_TRANSACTION)
    assert not roles.verdict("blocked", None)  # a write that succeeded is a failure
    assert not roles.verdict("blocked", roles.QUERY_CANCELED)
    assert roles.verdict("timeout", roles.QUERY_CANCELED)
    assert not roles.verdict("timeout", None)


def test_outcome_text():
    assert roles.outcome_text(None, None) == "succeeded"
    assert roles.outcome_text("42501", "InsufficientPrivilege") == (
        "InsufficientPrivilege (42501)"
    )
