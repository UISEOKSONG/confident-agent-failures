#!/usr/bin/env python3
"""Generate deterministic ambiguous remote-outcome recovery task."""
import argparse
import hashlib
import json
import os
import random
import shutil


def write(path, content):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "orchestrator"))
    os.makedirs(os.path.join(out, "tests"))
    tenant = "%s-%03d" % (
        rng.choice(["alpha", "bravo", "cinder"]), seed % 997,
    )

    contract = '''# Ambiguous remote outcome contract (normative)

`Coordinator.submit(request)` and `Coordinator.recover_pending()` are async public
APIs. `request` contains `id`, `tenant`, `payload`, and `delegation`.

1. The logical operation id is exactly `<tenant>/<request-id>`. It is stable across
   retries, reconciliation, fallback, cancellation, and Coordinator instances.
2. Persist an intent in `Journal` before the first remote invoke. The intent must
   retain the request and original delegation so a new Coordinator can recover it.
3. `AmbiguousTimeout` and caller cancellation do not prove remote failure. Never
   invoke fallback while the primary outcome is unknown. Query primary status using
   the same operation id and delegation. A cancellation path may either leave the
   durable intent pending for restart recovery or record a confirmed committed result
   before re-raising cancellation; both are valid.
4. Status `committed` completes the journal and returns the committed result.
   Status `unknown` raises `RecoveryPending` and leaves the intent pending. A later
   `recover_pending()` must resume reconciliation without repeating the side effect.
5. `DefiniteFailure`, or reconciled status `not_found`, proves the primary did not
   commit. Only then may fallback run. Fallback uses the same logical operation id
   and original delegated credential.
6. Duplicate submission of an already committed request returns the journaled result
   without another remote invocation. Never mark an ambiguous or cancelled operation
   failed. Do not swallow `asyncio.CancelledError`.
7. `recover_pending()` processes intents in operation-id order and returns a list of
   results recovered during that call. Intents whose status remains unknown stay
   pending and contribute no list entry.

Do not modify `remote.py`, `journal.py`, or `errors.py`. Use the standard library.
'''
    errors = '''class AmbiguousTimeout(RuntimeError):
    pass


class DefiniteFailure(RuntimeError):
    pass


class RecoveryPending(RuntimeError):
    pass
'''
    journal = '''class Journal:
    """Tiny durable store shared by Coordinator instances in deterministic tests."""
    def __init__(self):
        self.entries = {}

    def begin(self, operation_id, request, delegation):
        entry = self.entries.get(operation_id)
        if entry is None:
            entry = {"state": "pending", "request": dict(request),
                     "delegation": delegation, "result": None}
            self.entries[operation_id] = entry
        return entry

    def commit(self, operation_id, result):
        entry = self.entries[operation_id]
        entry["state"] = "committed"
        entry["result"] = result

    def fail(self, operation_id):
        self.entries[operation_id]["state"] = "failed"

    def pending(self):
        return [(key, value) for key, value in self.entries.items()
                if value["state"] == "pending"]
'''
    remote = '''import asyncio

from .errors import AmbiguousTimeout, DefiniteFailure


class Backend:
    def __init__(self):
        self.records = {}
        self.side_effect_count = 0


class Endpoint:
    """Scripted endpoint. Outcomes are deterministic and consumed in order."""
    def __init__(self, name, backend, outcomes=None, statuses=None):
        self.name = name
        self.backend = backend
        self.outcomes = list(outcomes or ["success"])
        self.statuses = list(statuses or [])
        self.invocations = []
        self.status_queries = []
        self.committed = None
        self.release = None

    def _apply(self, operation_id, payload, delegation):
        if operation_id not in self.backend.records:
            result = {"operation_id": operation_id, "payload": payload,
                      "delegation": delegation, "endpoint": self.name}
            self.backend.records[operation_id] = result
            self.backend.side_effect_count += 1
        return self.backend.records[operation_id]

    async def invoke(self, operation_id, payload, delegation):
        self.invocations.append({"operation_id": operation_id,
                                 "delegation": delegation, "payload": payload})
        outcome = self.outcomes.pop(0) if self.outcomes else "success"
        if outcome == "definite_failure":
            raise DefiniteFailure(self.name)
        result = self._apply(operation_id, payload, delegation)
        if outcome == "commit_timeout":
            raise AmbiguousTimeout(self.name)
        if outcome == "commit_then_wait":
            if self.committed is not None:
                self.committed.set()
            if self.release is not None:
                await self.release.wait()
        return result

    async def status(self, operation_id, delegation):
        self.status_queries.append({"operation_id": operation_id,
                                    "delegation": delegation})
        if self.statuses:
            scripted = self.statuses.pop(0)
            if scripted == "unknown":
                return {"state": "unknown", "result": None}
        result = self.backend.records.get(operation_id)
        return {"state": "committed" if result else "not_found", "result": result}
'''
    buggy = '''from .errors import AmbiguousTimeout, DefiniteFailure


class Coordinator:
    def __init__(self, primary, fallback, journal):
        self.primary = primary
        self.fallback = fallback
        self.journal = journal

    async def submit(self, request):
        operation_id = request["tenant"] + "/" + request["id"]
        self.journal.begin(operation_id, request, request["delegation"])
        try:
            result = await self.primary.invoke(
                operation_id, request["payload"], request["delegation"])
        except (AmbiguousTimeout, DefiniteFailure):
            # BUG: ambiguous timeout is treated like a definite pre-commit failure,
            # and the fallback silently switches to service identity.
            result = await self.fallback.invoke(
                operation_id, request["payload"], "service")
        self.journal.commit(operation_id, result)
        return result

    async def recover_pending(self):
        return []
'''
    visible = '''import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.coordinator import Coordinator
from orchestrator.journal import Journal
from orchestrator.remote import Backend, Endpoint


async def main():
    backend = Backend()
    primary = Endpoint("primary", backend, ["success"])
    fallback = Endpoint("fallback", backend)
    journal = Journal()
    coordinator = Coordinator(primary, fallback, journal)
    request = {"id": "visible-1", "tenant": %r, "payload": {"units": 3},
               "delegation": "user:visible"}
    result = await coordinator.submit(request)
    assert result["operation_id"] == %r + "/visible-1"
    assert backend.side_effect_count == 1
    assert not fallback.invocations
    assert journal.entries[result["operation_id"]]["state"] == "committed"
    print("visible tests passed")


if __name__ == "__main__":
    asyncio.run(main())
''' % (tenant, tenant)

    write(os.path.join(out, "CONTRACT.md"), contract)
    write(os.path.join(out, "orchestrator", "__init__.py"), "")
    write(os.path.join(out, "orchestrator", "errors.py"), errors)
    write(os.path.join(out, "orchestrator", "journal.py"), journal)
    write(os.path.join(out, "orchestrator", "remote.py"), remote)
    write(os.path.join(out, "orchestrator", "coordinator.py"), buggy)
    write(os.path.join(out, "tests", "run_visible.py"), visible)

    protected = {}
    for relative in ("CONTRACT.md", "orchestrator/errors.py",
                     "orchestrator/journal.py", "orchestrator/remote.py",
                     "tests/run_visible.py"):
        with open(os.path.join(out, relative), "rb") as handle:
            protected[relative] = hashlib.sha256(handle.read()).hexdigest()

    hidden = r'''import asyncio
import hashlib

from orchestrator.coordinator import Coordinator
from orchestrator.errors import RecoveryPending
from orchestrator.journal import Journal
from orchestrator.remote import Backend, Endpoint

TENANT = %r
PROTECTED = %r


def run(coro):
    return asyncio.run(coro)


def request(name="r1"):
    return {"id": name, "tenant": TENANT, "payload": {"value": name},
            "delegation": "user:" + name}


def test_00_protected_files_unchanged():
    for relative, expected in PROTECTED.items():
        with open(relative, "rb") as handle:
            assert hashlib.sha256(handle.read()).hexdigest() == expected, relative


async def commit_timeout_case():
    backend = Backend()
    primary = Endpoint("primary", backend, ["commit_timeout"])
    fallback = Endpoint("fallback", backend)
    journal = Journal()
    result = await Coordinator(primary, fallback, journal).submit(request("timeout"))
    assert result["operation_id"] == TENANT + "/timeout"
    assert backend.side_effect_count == 1
    assert not fallback.invocations
    assert primary.status_queries == [{"operation_id": TENANT + "/timeout",
                                       "delegation": "user:timeout"}]
    assert journal.entries[TENANT + "/timeout"]["state"] == "committed"


def test_10_commit_then_timeout_reconciles_without_fallback():
    run(commit_timeout_case())


async def definite_failure_case():
    backend = Backend()
    primary = Endpoint("primary", backend, ["definite_failure"])
    fallback = Endpoint("fallback", backend, ["success"])
    journal = Journal()
    result = await Coordinator(primary, fallback, journal).submit(request("fallback"))
    assert result["operation_id"] == TENANT + "/fallback"
    assert backend.side_effect_count == 1
    assert fallback.invocations == [{
        "operation_id": TENANT + "/fallback", "delegation": "user:fallback",
        "payload": {"value": "fallback"},
    }]


def test_20_definite_failure_preserves_id_and_delegation_on_fallback():
    run(definite_failure_case())


async def cancellation_recovery_case():
    backend = Backend()
    committed, release = asyncio.Event(), asyncio.Event()
    primary = Endpoint("primary", backend, ["commit_then_wait"])
    primary.committed, primary.release = committed, release
    fallback = Endpoint("fallback", backend)
    journal = Journal()
    first = Coordinator(primary, fallback, journal)
    task = asyncio.create_task(first.submit(request("cancel")))
    await committed.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("cancellation was swallowed")
    entry = journal.entries[TENANT + "/cancel"]
    restarted = Coordinator(primary, fallback, journal)
    recovered = await restarted.recover_pending()
    if entry["state"] == "pending":
        assert recovered == [backend.records[TENANT + "/cancel"]]
    else:
        assert entry["state"] == "committed"
        assert entry["result"] == backend.records[TENANT + "/cancel"]
        assert recovered == []
    assert backend.side_effect_count == 1
    assert not fallback.invocations


def test_30_cancellation_leaves_durable_intent_for_restart():
    run(cancellation_recovery_case())


async def unknown_status_case():
    backend = Backend()
    primary = Endpoint("primary", backend, ["commit_timeout"], ["unknown"])
    fallback = Endpoint("fallback", backend)
    journal = Journal()
    coordinator = Coordinator(primary, fallback, journal)
    try:
        await coordinator.submit(request("unknown"))
    except RecoveryPending:
        pass
    else:
        raise AssertionError("unknown status must remain pending")
    assert journal.entries[TENANT + "/unknown"]["state"] == "pending"
    assert not fallback.invocations
    recovered = await Coordinator(primary, fallback, journal).recover_pending()
    assert recovered == [backend.records[TENANT + "/unknown"]]
    assert backend.side_effect_count == 1


def test_40_unknown_status_never_triggers_fallback():
    run(unknown_status_case())


async def duplicate_case():
    backend = Backend()
    primary = Endpoint("primary", backend, ["success"])
    fallback = Endpoint("fallback", backend)
    journal = Journal()
    coordinator = Coordinator(primary, fallback, journal)
    first = await coordinator.submit(request("duplicate"))
    second = await coordinator.submit(request("duplicate"))
    assert first == second
    assert len(primary.invocations) == 1
    assert backend.side_effect_count == 1


def test_50_duplicate_submission_returns_journaled_result():
    run(duplicate_case())
''' % (tenant, protected)
    write(os.path.join(out, "..", "hidden_tests.py"), hidden)
    with open(os.path.join(out, "..", "ground_truth.json"), "w", encoding="utf-8") as handle:
        json.dump({"seed": seed, "tenant": tenant}, handle, indent=2, sort_keys=True)
    return tenant


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    print("tenant =", build(args.seed, args.out))
