"""Static cross-check: every cross-module call in the pipeline's
orchestration modules must bind against the real target function's
signature.

This exists because a real bug shipped past code review and `pytest tests/unit`
straight into GitHub Actions CI: scripts/aeronautica_testing/suites.py called
``client_smoke.run_headless_session(..., timeout_seconds=...)`` while the
function itself was defined to accept ``timeout`` (not ``timeout_seconds``).
No existing unit test imported both suites.py and client_smoke.py and
actually tried to bind one against the other, so nothing caught it locally --
it only surfaced ~10 minutes into a real Java/Docker CI job as
``TypeError: run_headless_session() got an unexpected keyword argument
'timeout_seconds'``.

This test parses each orchestration module's own source with ``ast`` and,
for every ``name.attr(...)`` or bare ``name(...)`` call whose target can be
statically resolved through that module's *own* namespace (so it sees
exactly the same names/aliases the real code sees), binds the call's keyword
arguments against ``inspect.signature(target)``. A renamed parameter on
either side now fails in milliseconds, with no Java, Docker, or network
involved.

Scope/limitations (deliberate, not oversights):
- Only statically resolvable ``module.function`` / bare-function calls are
  checked -- calls on local instances (``report.record(...)``,
  ``ctx.timeout(...)``) can't be resolved without type inference and are
  silently skipped. That's fine: the bug class this guards against is
  cross-module orchestration calls, which in this codebase always go
  through a module-level import.
- Only *keyword* arguments are validated (the exact bug class: "unexpected
  keyword argument"). Positional arity is not checked.
- A target that declares ``**kwargs`` is skipped, since any keyword name
  binds.
"""
from __future__ import annotations

import ast
import importlib
import inspect
from types import ModuleType

# Every module in the pipeline that orchestrates calls into a sibling
# module. If a new suite/module is added that calls across module
# boundaries, add it here too.
ORCHESTRATION_MODULES = [
    "aeronautica_testing.suites",
    "aeronautica_testing.cli",
    "aeronautica_testing.client_smoke",
    "aeronautica_testing.server_smoke",
    "aeronautica_testing.gametest_runner",
    "aeronautica_testing.worldgen_perf",
    "aeronautica_testing.installer_check",
    "aeronautica_testing.reproducible",
    "aeronautica_testing.modrinth_hashes",
    "aeronautica_testing.mrpack_validate",
    "aeronautica_testing.prereqs",
]


def _resolve_call_target(node: ast.Call, namespace: dict):
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        owner = namespace.get(func.value.id)
        if isinstance(owner, ModuleType):
            return getattr(owner, func.attr, None)
        return None
    if isinstance(func, ast.Name):
        return namespace.get(func.id)
    return None


def _iter_keyword_calls(module: ModuleType):
    """Yields (lineno, target_callable, [keyword_names]) for every call in
    `module`'s source with >=1 keyword argument and a statically resolvable
    target.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source, filename=getattr(module, "__file__", module.__name__))
    namespace = vars(module)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kwargs = [kw.arg for kw in node.keywords if kw.arg is not None]
        if not kwargs:
            continue
        target = _resolve_call_target(node, namespace)
        if target is None or not (inspect.isfunction(target) or inspect.isbuiltin(target)):
            continue
        yield node.lineno, target, kwargs


def _mismatches_for_module(module: ModuleType) -> tuple[list[str], int]:
    failures = []
    checked = 0
    for lineno, target, kwargs in _iter_keyword_calls(module):
        checked += 1
        sig = inspect.signature(target)
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            continue
        valid_names = set(sig.parameters)
        for name in kwargs:
            if name not in valid_names:
                qualname = getattr(target, "__qualname__", getattr(target, "__name__", repr(target)))
                failures.append(
                    f"{module.__name__}:{lineno} calls {qualname}(..., {name}=...) but its real "
                    f"signature is {qualname}{sig} -- no such parameter."
                )
    return failures, checked


def test_every_resolvable_cross_module_call_binds_its_real_signature():
    all_failures: list[str] = []
    total_checked = 0
    for module_name in ORCHESTRATION_MODULES:
        module = importlib.import_module(module_name)
        failures, checked = _mismatches_for_module(module)
        all_failures.extend(failures)
        total_checked += checked

    # This is a floor, not an exact count: it exists so that if the AST
    # resolution logic itself silently breaks (e.g. an import style changes
    # such that names stop resolving), this test fails loudly instead of
    # quietly checking nothing and always passing. Real refactors may move
    # this number around; a large drop is the signal to investigate,
    # not to raise the floor to make the test pass again.
    assert total_checked >= 20, (
        f"only statically resolved {total_checked} keyword-bearing cross-module calls across "
        f"{ORCHESTRATION_MODULES} -- the AST walk's name resolution may be broken, silently "
        "checking nothing. Investigate before trusting this test's green."
    )
    assert not all_failures, "signature/call-site mismatch(es):\n" + "\n".join(all_failures)
