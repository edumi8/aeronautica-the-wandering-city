from __future__ import annotations

from aeronautica_testing import client_smoke


def test_client_success_signature_is_the_full_startup_marker():
    assert client_smoke.CLIENT_SUCCESS_SIGNATURE == "Game took "


def test_fatal_signatures_do_not_include_the_success_marker():
    assert all(
        client_smoke.CLIENT_SUCCESS_SIGNATURE not in signature
        for signature in client_smoke.FATAL_LOG_SIGNATURES
    )
