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


def test_role_settings():
    role_env = {"r1": ("PW1", "URL1"), "r2": ("PW2", "URL2")}
    env = {"PW1": "a", "URL1": "u1", "PW2": "", "URL2": "u2"}
    assert roles.role_settings(role_env, env, 0) == ({"r1": "a"}, ["PW2"])
    assert roles.role_settings(role_env, env, 1) == ({"r1": "u1", "r2": "u2"}, [])


def test_checks_cover_both_roles():
    assert {c[0] for c in roles.CHECKS} == {"vnmacro_reader", "vnmacro_logger"}
    assert all(c[3] in roles.EXPECTED_STATES for c in roles.CHECKS)
