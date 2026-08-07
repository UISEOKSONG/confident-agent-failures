#!/usr/bin/env python3
"""Generate deterministic delegated fallback and reload lifecycle task."""
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
    os.makedirs(os.path.join(out, "router"))
    os.makedirs(os.path.join(out, "tests"))
    route = rng.choice(["search", "calendar", "ticket", "crm"])
    v1 = "v%d" % rng.randint(2, 5)
    v2 = "v%d" % (int(v1[1:]) + 1)

    contract = '''# Delegated fallback lifecycle contract (normative)

`Router.call(route, request)` and `Router.reload(plugin_name, replacement)` are async
public APIs. A route is a `(primary, fallback)` plugin pair. `request` contains
`payload` and `delegation`.

1. Acquire the complete current route exactly once before the first plugin await.
   Primary and fallback for one request must come from that same route generation,
   even if either plugin is reloaded while primary is suspended.
2. Open every session with the request's original delegated token. Fallback must not
   substitute service identity or a refreshed token from another request.
3. Reload atomically publishes replacements and must not wait for plugin invocation.
   Calls acquiring after publication use the replacement. A retired plugin remains
   open until every request snapshot that leased it has exited.
4. Every opened session is closed exactly once after success, plugin failure, or task
   cancellation. Every retired plugin is eventually closed exactly once after its
   final snapshot lease exits. Do not swallow `asyncio.CancelledError`.
5. Do not hold the router lock while awaiting session invoke/close or plugin close.
   `plugin.py` is the fixed production lifecycle and must not be modified.

Use only the Python standard library.
'''
    errors = '''class DefiniteFailure(RuntimeError):
    pass


class PluginClosed(RuntimeError):
    pass
'''
    plugin = '''import asyncio

from .errors import DefiniteFailure, PluginClosed


class Session:
    def __init__(self, plugin, delegation):
        self.plugin = plugin
        self.delegation = delegation
        self.closed = False
        self.close_count = 0

    async def invoke(self, payload):
        plugin = self.plugin
        if plugin.closed:
            raise PluginClosed(plugin.version)
        if plugin.invoke_entered is not None:
            plugin.invoke_entered.set()
        if plugin.invoke_release is not None:
            await plugin.invoke_release.wait()
        if plugin.closed:
            raise PluginClosed(plugin.version)
        if plugin.fail:
            raise DefiniteFailure(plugin.version)
        return {"plugin": plugin.name, "version": plugin.version,
                "delegation": self.delegation, "payload": payload}

    async def close(self):
        self.close_count += 1
        if self.close_count != 1:
            raise RuntimeError("session closed more than once")
        self.closed = True


class Plugin:
    def __init__(self, name, version, fail=False):
        self.name = name
        self.version = version
        self.fail = fail
        self.closed = False
        self.close_count = 0
        self.sessions = []
        self.invoke_entered = None
        self.invoke_release = None

    def open_session(self, delegation):
        if self.closed:
            raise PluginClosed(self.version)
        session = Session(self, delegation)
        self.sessions.append(session)
        return session

    async def close(self):
        if any(not session.closed for session in self.sessions):
            raise RuntimeError("plugin closed with open session")
        self.close_count += 1
        if self.close_count != 1:
            raise RuntimeError("plugin closed more than once")
        self.closed = True
        await asyncio.sleep(0)
'''
    buggy = '''import asyncio

from .errors import DefiniteFailure


class Router:
    def __init__(self, routes):
        self._routes = dict(routes)
        self._lock = asyncio.Lock()

    async def call(self, route, request):
        primary = self._routes[route][0]
        primary_session = primary.open_session(request["delegation"])
        try:
            result = await primary_session.invoke(request["payload"])
            await primary_session.close()
            return result
        except DefiniteFailure:
            await primary_session.close()
            # BUG: fallback is resolved after the await and runs as service.
            fallback = self._routes[route][1]
            fallback_session = fallback.open_session("service")
            result = await fallback_session.invoke(request["payload"])
            await fallback_session.close()
            return result

    async def reload(self, plugin_name, replacement):
        async with self._lock:
            for route, pair in list(self._routes.items()):
                updated = list(pair)
                for index, plugin in enumerate(updated):
                    if plugin.name == plugin_name:
                        await plugin.close()
                        updated[index] = replacement
                self._routes[route] = tuple(updated)
'''
    visible = '''import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router.plugin import Plugin
from router.router import Router


async def main():
    primary = Plugin("primary", %r)
    fallback = Plugin("fallback", %r)
    router = Router({%r: (primary, fallback)})
    request = {"payload": {"id": 1}, "delegation": "user:visible"}
    result = await router.call(%r, request)
    assert result["version"] == %r
    assert result["delegation"] == "user:visible"
    assert primary.sessions[0].closed
    replacement = Plugin("primary", %r)
    await router.reload("primary", replacement)
    assert primary.closed and primary.close_count == 1
    print("visible tests passed")


if __name__ == "__main__":
    asyncio.run(main())
''' % (v1, v1, route, route, v1, v2)

    write(os.path.join(out, "CONTRACT.md"), contract)
    write(os.path.join(out, "router", "__init__.py"), "")
    write(os.path.join(out, "router", "errors.py"), errors)
    write(os.path.join(out, "router", "plugin.py"), plugin)
    write(os.path.join(out, "router", "router.py"), buggy)
    write(os.path.join(out, "tests", "run_visible.py"), visible)

    protected = {}
    for relative in ("CONTRACT.md", "router/errors.py", "router/plugin.py",
                     "tests/run_visible.py"):
        with open(os.path.join(out, relative), "rb") as handle:
            protected[relative] = hashlib.sha256(handle.read()).hexdigest()

    hidden = r'''import asyncio
import hashlib

from router.errors import DefiniteFailure
from router.plugin import Plugin
from router.router import Router

ROUTE = %r
V1 = %r
V2 = %r
PROTECTED = %r


def run(coro):
    return asyncio.run(coro)


def test_00_protected_files_unchanged():
    for relative, expected in PROTECTED.items():
        with open(relative, "rb") as handle:
            assert hashlib.sha256(handle.read()).hexdigest() == expected, relative


async def fallback_snapshot_case():
    entered, release = asyncio.Event(), asyncio.Event()
    primary = Plugin("primary", V1, fail=True)
    primary.invoke_entered, primary.invoke_release = entered, release
    old_fallback = Plugin("fallback", V1)
    router = Router({ROUTE: (primary, old_fallback)})
    request = {"payload": {"case": "snapshot"}, "delegation": "user:alpha"}
    call = asyncio.create_task(router.call(ROUTE, request))
    await entered.wait()
    new_fallback = Plugin("fallback", V2)
    await asyncio.wait_for(router.reload("fallback", new_fallback), timeout=0.2)
    assert not old_fallback.closed
    release.set()
    result = await call
    assert result["version"] == V1
    assert result["delegation"] == "user:alpha"
    assert old_fallback.closed and old_fallback.close_count == 1
    assert not new_fallback.sessions
    assert all(session.closed for session in primary.sessions + old_fallback.sessions)


def test_10_fallback_uses_original_snapshot_and_delegation():
    run(fallback_snapshot_case())


async def delegated_fallback_case():
    primary = Plugin("primary", V1, fail=True)
    fallback = Plugin("fallback", V1)
    router = Router({ROUTE: (primary, fallback)})
    result = await router.call(
        ROUTE, {"payload": 1, "delegation": "user:delegated"})
    assert result["delegation"] == "user:delegated"
    assert fallback.sessions[0].delegation == "user:delegated"
    assert primary.sessions[0].closed and fallback.sessions[0].closed


def test_15_fallback_preserves_delegated_identity_without_reload():
    run(delegated_fallback_case())


async def primary_reload_case():
    entered, release = asyncio.Event(), asyncio.Event()
    old_primary = Plugin("primary", V1)
    old_primary.invoke_entered, old_primary.invoke_release = entered, release
    fallback = Plugin("fallback", V1)
    router = Router({ROUTE: (old_primary, fallback)})
    call = asyncio.create_task(router.call(
        ROUTE, {"payload": 1, "delegation": "user:beta"}))
    await entered.wait()
    replacement = Plugin("primary", V2)
    await asyncio.wait_for(router.reload("primary", replacement), timeout=0.2)
    assert not old_primary.closed
    release.set()
    result = await call
    assert result["version"] == V1
    assert old_primary.closed and old_primary.close_count == 1
    later = await router.call(ROUTE, {"payload": 2, "delegation": "user:beta"})
    assert later["version"] == V2


def test_20_reload_is_nonblocking_and_retirement_waits_for_snapshot():
    run(primary_reload_case())


async def cancellation_case():
    entered, release = asyncio.Event(), asyncio.Event()
    old_primary = Plugin("primary", V1)
    old_primary.invoke_entered, old_primary.invoke_release = entered, release
    fallback = Plugin("fallback", V1)
    router = Router({ROUTE: (old_primary, fallback)})
    call = asyncio.create_task(router.call(
        ROUTE, {"payload": 1, "delegation": "user:cancel"}))
    await entered.wait()
    await router.reload("primary", Plugin("primary", V2))
    call.cancel()
    try:
        await call
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("cancellation was swallowed")
    assert old_primary.sessions and old_primary.sessions[0].closed
    assert old_primary.closed and old_primary.close_count == 1
    assert not fallback.sessions


def test_30_cancellation_closes_session_and_releases_snapshot():
    run(cancellation_case())


async def fallback_failure_case():
    primary = Plugin("primary", V1, fail=True)
    fallback = Plugin("fallback", V1, fail=True)
    router = Router({ROUTE: (primary, fallback)})
    try:
        await router.call(ROUTE, {"payload": 1, "delegation": "user:failure"})
    except DefiniteFailure:
        pass
    else:
        raise AssertionError("fallback failure was swallowed")
    assert primary.sessions[0].closed
    assert fallback.sessions[0].closed


def test_40_fallback_exception_closes_every_open_session():
    run(fallback_failure_case())
''' % (route, v1, v2, protected)
    write(os.path.join(out, "..", "hidden_tests.py"), hidden)
    with open(os.path.join(out, "..", "ground_truth.json"), "w", encoding="utf-8") as handle:
        json.dump({"seed": seed, "route": route, "versions": [v1, v2]},
                  handle, indent=2, sort_keys=True)
    return route


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    print("route =", build(args.seed, args.out))
