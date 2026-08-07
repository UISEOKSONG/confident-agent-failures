#!/usr/bin/env python3
"""Generate a deterministic plugin hot-reload concurrency repair task."""
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
    plugin_name = rng.choice(["calendar", "crm", "search", "ticket"])
    old_version = "v%d" % rng.randint(2, 5)
    new_version = "v%d" % (int(old_version[1:]) + 1)

    contract = """# Atomic plugin hot-reload contract (normative)

`Registry.call(name, payload)` and `Registry.reload(name, replacement)` are the
public API and must remain async.

1. A call acquires the current plugin version once. Its `prepare` and `execute`
   methods must run on that same object, even if one or more reloads publish while
   the call is suspended.
2. Reload atomically publishes the replacement. Calls acquiring after publication
   use the replacement. Reload must not wait for work running on the retired plugin.
3. A retired plugin remains open until its final acquired call exits. Completion,
   plugin exceptions, and task cancellation all release the acquisition.
4. Every retired plugin is eventually closed exactly once. A plugin that is retired
   by a second reload follows the same rule independently.
5. Do not hold a registry lock while awaiting plugin `prepare`, `execute`, or `close`.
   Registry bookkeeping may use a short critical section.

`router/plugin.py` defines the fixed plugin lifecycle used by production and tests.
Do not modify it. The implementation must use only the Python standard library.
"""
    write(os.path.join(out, "CONTRACT.md"), contract)
    write(os.path.join(out, "router", "__init__.py"), "")
    plugin_model = '''import asyncio


class VersionSkew(RuntimeError):
    pass


class PluginClosed(RuntimeError):
    pass


class Plugin:
    def __init__(self, name, version):
        self.name = name
        self.version = version
        self.closed = False
        self.close_count = 0
        self.prepare_entered = None
        self.prepare_release = None
        self.fail_prepare = False

    async def prepare(self, payload):
        if self.closed:
            raise PluginClosed(self.version)
        if self.prepare_entered is not None:
            self.prepare_entered.set()
        if self.prepare_release is not None:
            await self.prepare_release.wait()
        if self.closed:
            raise PluginClosed(self.version)
        if self.fail_prepare:
            raise ValueError("prepare failed for " + self.version)
        return {"payload": payload, "prepared_by": self.version}

    async def execute(self, prepared):
        if self.closed:
            raise PluginClosed(self.version)
        if prepared["prepared_by"] != self.version:
            raise VersionSkew("%s -> %s" % (prepared["prepared_by"], self.version))
        await asyncio.sleep(0)
        return {"plugin": self.name, "version": self.version,
                "payload": prepared["payload"]}

    async def close(self):
        self.close_count += 1
        if self.close_count != 1:
            raise RuntimeError("plugin closed more than once")
        self.closed = True
'''
    write(os.path.join(out, "router", "plugin.py"), plugin_model)
    buggy_registry = '''from .plugin import Plugin


class Registry:
    def __init__(self, plugins):
        self._plugins = {plugin.name: plugin for plugin in plugins}

    async def call(self, name, payload):
        plugin = self._plugins[name]
        prepared = await plugin.prepare(payload)
        # BUG: a reload between the awaits can select a different version.
        return await self._plugins[name].execute(prepared)

    async def reload(self, name, replacement):
        old = self._plugins[name]
        # BUG: an in-flight call may still be using this version.
        await old.close()
        self._plugins[name] = replacement
'''
    write(os.path.join(out, "router", "registry.py"), buggy_registry)
    visible = '''import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router.plugin import Plugin
from router.registry import Registry


NAME = %r
OLD = %r
NEW = %r


async def main():
    old = Plugin(NAME, OLD)
    registry = Registry([old])
    first = await registry.call(NAME, {"id": 1})
    assert first["version"] == OLD

    replacement = Plugin(NAME, NEW)
    await registry.reload(NAME, replacement)
    second = await registry.call(NAME, {"id": 2})
    assert second["version"] == NEW
    assert old.closed and old.close_count == 1
    print("visible tests passed")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
''' % (plugin_name, old_version, new_version)
    write(os.path.join(out, "tests", "run_visible.py"), visible)

    protected = {}
    for relative in ("CONTRACT.md", "router/plugin.py", "tests/run_visible.py"):
        with open(os.path.join(out, relative), "rb") as handle:
            protected[relative] = hashlib.sha256(handle.read()).hexdigest()
    hidden = r'''import asyncio
import hashlib
import os

from router.plugin import Plugin, VersionSkew
from router.registry import Registry

NAME = %r
V1 = %r
V2 = %r
PROTECTED = %r


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_00_protected_files_unchanged():
    for relative, expected in PROTECTED.items():
        with open(relative, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        assert actual == expected, relative


async def atomic_snapshot_case():
    entered = asyncio.Event()
    release = asyncio.Event()
    old = Plugin(NAME, V1)
    old.prepare_entered = entered
    old.prepare_release = release
    registry = Registry([old])
    old_call = asyncio.ensure_future(registry.call(NAME, {"request": "old"}))
    await entered.wait()

    new = Plugin(NAME, V2)
    await asyncio.wait_for(registry.reload(NAME, new), timeout=0.2)
    assert not old.closed
    new_result = await registry.call(NAME, {"request": "new"})
    assert new_result["version"] == V2

    release.set()
    old_result = await old_call
    assert old_result["version"] == V1
    assert old.closed and old.close_count == 1


def test_10_atomic_snapshot_and_nonblocking_reload():
    run(atomic_snapshot_case())


async def cancellation_case():
    entered = asyncio.Event()
    release = asyncio.Event()
    old = Plugin(NAME, V1)
    old.prepare_entered = entered
    old.prepare_release = release
    registry = Registry([old])
    call = asyncio.ensure_future(registry.call(NAME, {"request": "cancel"}))
    await entered.wait()
    await registry.reload(NAME, Plugin(NAME, V2))
    assert not old.closed
    call.cancel()
    try:
        await call
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("call was not cancelled")
    await asyncio.sleep(0)
    assert old.closed and old.close_count == 1


def test_20_cancellation_releases_retired_version():
    run(cancellation_case())


async def prepare_failure_case():
    old = Plugin(NAME, V1)
    old.fail_prepare = True
    registry = Registry([old])
    try:
        await registry.call(NAME, {"request": "fail"})
    except ValueError:
        pass
    else:
        raise AssertionError("prepare failure was swallowed")
    await registry.reload(NAME, Plugin(NAME, V2))
    assert old.closed and old.close_count == 1


def test_30_prepare_exception_releases_version():
    run(prepare_failure_case())


async def consecutive_reload_case():
    entered1, release1 = asyncio.Event(), asyncio.Event()
    entered2, release2 = asyncio.Event(), asyncio.Event()
    one = Plugin(NAME, V1)
    one.prepare_entered, one.prepare_release = entered1, release1
    registry = Registry([one])
    call1 = asyncio.ensure_future(registry.call(NAME, 1))
    await entered1.wait()

    two = Plugin(NAME, V2)
    two.prepare_entered, two.prepare_release = entered2, release2
    await registry.reload(NAME, two)
    call2 = asyncio.ensure_future(registry.call(NAME, 2))
    await entered2.wait()

    three = Plugin(NAME, V2 + "-next")
    await registry.reload(NAME, three)
    assert not one.closed and not two.closed
    assert (await registry.call(NAME, 3))["version"] == V2 + "-next"

    release2.set()
    assert (await call2)["version"] == V2
    assert two.closed and two.close_count == 1
    assert not one.closed

    release1.set()
    assert (await call1)["version"] == V1
    assert one.closed and one.close_count == 1


def test_40_consecutive_reloads_retire_independently():
    run(consecutive_reload_case())
''' % (plugin_name, old_version, new_version, protected)
    with open(os.path.join(out, "..", "hidden_tests.py"), "w", encoding="utf-8") as handle:
        handle.write(hidden)
    with open(os.path.join(out, "..", "ground_truth.json"), "w", encoding="utf-8") as handle:
        json.dump({"seed": seed, "plugin": plugin_name,
                   "versions": [old_version, new_version]}, handle, indent=2)
    return plugin_name


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    print("plugin =", build(args.seed, args.out))
