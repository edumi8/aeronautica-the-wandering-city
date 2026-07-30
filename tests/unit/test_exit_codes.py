from __future__ import annotations

from aeronautica_testing.exit_codes import ExitCode, worst


def test_worst_empty_is_ok():
    assert worst([]) == ExitCode.OK


def test_worst_all_ok_is_ok():
    assert worst([ExitCode.OK, ExitCode.OK]) == ExitCode.OK


def test_worst_prioritizes_internal_error_above_everything():
    codes = [ExitCode.OK, ExitCode.TESTS_FAILED, ExitCode.INTERNAL_ERROR, ExitCode.PREREQUISITE_MISSING]
    assert worst(codes) == ExitCode.INTERNAL_ERROR


def test_worst_prioritizes_usage_error_above_test_failures():
    codes = [ExitCode.TESTS_FAILED, ExitCode.USAGE_ERROR]
    assert worst(codes) == ExitCode.USAGE_ERROR


def test_worst_prerequisite_missing_above_test_failures():
    codes = [ExitCode.TESTS_FAILED, ExitCode.PREREQUISITE_MISSING]
    assert worst(codes) == ExitCode.PREREQUISITE_MISSING


def test_worst_test_failure_beats_ok():
    assert worst([ExitCode.OK, ExitCode.TESTS_FAILED]) == ExitCode.TESTS_FAILED


def test_exit_codes_are_stable_values():
    # These values are part of the documented CLI contract (TESTING.md) --
    # changing them is a breaking change for anything scripting around this
    # tool's exit code.
    assert ExitCode.OK == 0
    assert ExitCode.TESTS_FAILED == 1
    assert ExitCode.USAGE_ERROR == 2
    assert ExitCode.PREREQUISITE_MISSING == 3
    assert ExitCode.INTERNAL_ERROR == 4
    assert ExitCode.INTERRUPTED == 130
