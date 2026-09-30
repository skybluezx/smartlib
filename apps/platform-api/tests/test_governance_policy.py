from datetime import UTC, datetime, timedelta

from smartlib_platform.governance.service import effective_license_state


def test_only_current_approved_license_is_effective() -> None:
    now = datetime(2026, 8, 26, tzinfo=UTC)
    assert (
        effective_license_state("approved", now - timedelta(days=1), now + timedelta(days=1), now=now)
        == "effective"
    )


def test_unknown_or_pending_authorization_never_defaults_to_allow() -> None:
    now = datetime(2026, 8, 26, tzinfo=UTC)
    assert effective_license_state("pending", None, None, now=now) == "review_required"
    assert effective_license_state("unknown", None, None, now=now) == "denied"


def test_expired_and_future_licenses_are_not_effective() -> None:
    now = datetime(2026, 8, 26, tzinfo=UTC)
    assert effective_license_state("approved", None, now - timedelta(seconds=1), now=now) == "expired"
    assert effective_license_state("approved", now + timedelta(seconds=1), None, now=now) == "not_yet_valid"
