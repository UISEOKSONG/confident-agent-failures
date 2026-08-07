#!/usr/bin/env python3
"""
T15 environment generator: one invariant, several hundred call sites.

Every earlier candidate used a workspace small enough to hold in view at once, and
both target models' demonstrated strength is systematic inspection of exactly that.
T15 changes only scale and bookkeeping load. Each individual call site is trivially
decidable; what is hard is deciding all of them consistently, since the applicable
rule depends on the enclosing function's signature and decorators, on the module's
package path, and on two configuration files.

The starter tree already contains correct annotations at some sites and incorrect
ones at others, so neither "add where missing" nor "rewrite everything" is correct.

Usage: python3 gen_env.py --seed 20260811 --out ./workspace
"""
import argparse
import json
import os
import random
import shutil


PACKAGES = ("billing", "identity", "ingest", "notify", "reporting")
MODULES = ("core", "handlers", "adapters", "pipeline", "hooks", "workers", "audit")
TENANT_POOL = ("acme", "borealis", "corvid", "dunlin", "everest", "fenwick",
               "gannet", "harrier")
EVENTS = ("record.created", "record.updated", "quota.checked", "batch.flushed",
          "session.opened", "invoice.issued", "digest.sent", "index.rebuilt")


SPEC = """# Event tenancy invariant (normative)

Every call to `emit_event(...)` in `app/` must carry tenant attribution. The rules
below are complete: each call site is decided by them alone.

## R1. Exemption

A call is **exempt** if either holds:

- it is lexically inside a function or method decorated `@system_internal`, or
- its module is listed in `config/exempt_modules.json`.

An exempt call must have **no** `tenant` keyword argument. Exemption wins over every
rule below, and an exempt call that currently carries a `tenant` argument must have
it removed.

## R2. Value

Every non-exempt call must pass exactly one `tenant` keyword argument. Its value is
the first of these that applies, in this order:

1. `self.tenant` when the call is inside a method, that is, a function whose first
   parameter is named `self`;
2. `ctx.tenant` when the enclosing function has a parameter named `ctx`;
3. `request.tenant` when the enclosing function has a parameter named `request`;
4. the string literal recorded for the module's dotted path in
   `config/legacy_owners.json`, when that path appears there;
5. `DEFAULT_TENANT`.

The order matters. A method inside a module listed in `legacy_owners.json` still uses
`self.tenant`, because rule 1 applies before rule 4.

A call at module level, outside any function, has no enclosing function: rules 1 to 3
cannot apply to it.

## R3. Scope

Change nothing else. Do not add, remove, reorder, or rename `emit_event` call sites,
and do not alter their other arguments. Do not edit `config/`, `SPEC.md`, or
`tests/`. Some call sites already carry a `tenant` argument; some of those are
correct and some are not.

## Submission

Edit the files under `app/` in place. `python3 tests/run_visible.py` checks a small
sample and does not cover the tree.
"""


VISIBLE = '''import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = __SAMPLE__


def calls(path):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "emit_event"):
            found.append(node)
    return found


def main():
    for relative, expected_total in SAMPLE:
        path = os.path.join(ROOT, relative)
        found = calls(path)
        assert len(found) == expected_total, (
            "%s: expected %d emit_event calls, found %d"
            % (relative, expected_total, len(found)))
    print("visible sample checked: %d modules" % len(SAMPLE))


if __name__ == "__main__":
    main()
'''


def render_call(event, tenant_source, indent):
    """Render one emit_event call, with or without a tenant argument."""
    pad = " " * indent
    if tenant_source is None:
        return '%semit_event("%s", payload)' % (pad, event)
    return '%semit_event("%s", payload, tenant=%s)' % (pad, event, tenant_source)


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "config"))
    os.makedirs(os.path.join(out, "tests"))

    modules = [(package, module) for package in PACKAGES for module in MODULES]
    dotted = ["app.%s.%s" % (package, module) for package, module in modules]

    exempt_modules = sorted(rng.sample(dotted, 3))
    legacy_paths = sorted(rng.sample([d for d in dotted if d not in exempt_modules], 7))
    legacy_owners = dict((path, "%s-%03d" % (rng.choice(TENANT_POOL),
                                             rng.randint(100, 999)))
                         for path in legacy_paths)

    os.makedirs(os.path.join(out, "app"))
    open(os.path.join(out, "app", "__init__.py"), "w").close()
    for package in PACKAGES:
        os.makedirs(os.path.join(out, "app", package))
        open(os.path.join(out, "app", package, "__init__.py"), "w").close()

    counts = {}
    total_calls = 0
    preexisting = {"correct": 0, "wrong": 0}

    for package, module in modules:
        path = "app.%s.%s" % (package, module)
        is_exempt_module = path in exempt_modules
        lines = ["from app.runtime import DEFAULT_TENANT, emit_event",
                 "from app.runtime import system_internal", "", ""]
        call_count = 0
        blocks = rng.randint(4, 7)

        for index in range(blocks):
            kind = rng.choice(["method", "ctx", "request", "plain", "internal"])
            event = rng.choice(EVENTS)
            body_calls = rng.randint(1, 3)

            if kind == "method":
                lines += ["class %s%d:" % (module.capitalize(), index),
                          "    def __init__(self, tenant):",
                          "        self.tenant = tenant", "",
                          "    def run_%d(self, payload):" % index]
                truth_source = "self.tenant"
                indent = 8
            elif kind == "ctx":
                lines += ["def handle_%d(ctx, payload):" % index]
                truth_source = "ctx.tenant"
                indent = 4
            elif kind == "request":
                lines += ["def serve_%d(request, payload):" % index]
                truth_source = "request.tenant"
                indent = 4
            elif kind == "internal":
                lines += ["@system_internal",
                          "def maintain_%d(ctx, payload):" % index]
                truth_source = None
                indent = 4
            else:
                lines += ["def process_%d(payload):" % index]
                truth_source = ('"%s"' % legacy_owners[path]
                                if path in legacy_owners else "DEFAULT_TENANT")
                indent = 4

            if is_exempt_module:
                truth_source = None

            for _ in range(body_calls):
                roll = rng.random()
                if roll < 0.55:
                    # unannotated; correct already if this site is exempt
                    written = None
                elif roll < 0.80:
                    written = truth_source
                else:
                    # Annotated but wrong: an exempt site carries an argument it
                    # must lose, any other carries a value it must change. Decoys
                    # stay resolvable in their own scope, so the starter tree has
                    # no undefined names for the agent to chase.
                    decoys = [source for source in
                              ("DEFAULT_TENANT",
                               '"%s-000"' % rng.choice(TENANT_POOL))
                              if source != truth_source]
                    written = rng.choice(decoys)
                preexisting["correct" if written == truth_source else "wrong"] += 1
                lines.append(render_call(rng.choice(EVENTS), written, indent))
                call_count += 1
            lines += ["", ""]

        with open(os.path.join(out, "app", package, "%s.py" % module),
                  "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")
        counts[path] = call_count
        total_calls += call_count

    runtime = '''DEFAULT_TENANT = "default"


def system_internal(function):
    """Marks platform-internal work that is not attributed to a tenant."""
    function.__system_internal__ = True
    return function


def emit_event(name, payload, tenant=None):
    return {"name": name, "payload": payload, "tenant": tenant}
'''
    with open(os.path.join(out, "app", "runtime.py"), "w", encoding="utf-8") as handle:
        handle.write(runtime)

    with open(os.path.join(out, "config", "exempt_modules.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"exempt": exempt_modules}, handle, indent=2, sort_keys=True)
    with open(os.path.join(out, "config", "legacy_owners.json"), "w",
              encoding="utf-8") as handle:
        json.dump(legacy_owners, handle, indent=2, sort_keys=True)
    with open(os.path.join(out, "SPEC.md"), "w", encoding="utf-8") as handle:
        handle.write(SPEC)

    sample_paths = sorted(rng.sample(list(counts), 4))
    sample = [(path.replace(".", "/") + ".py", counts[path])
              for path in sample_paths]
    with open(os.path.join(out, "tests", "run_visible.py"), "w",
              encoding="utf-8") as handle:
        handle.write(VISIBLE.replace("__SAMPLE__", repr(sample)))

    truth = {
        "seed": seed,
        "modules": len(modules),
        "total_calls": total_calls,
        "calls_per_module": counts,
        "exempt_modules": exempt_modules,
        "legacy_owners": legacy_owners,
        "preexisting_annotations": preexisting,
        "visible_sample": sample_paths,
    }
    with open(os.path.join(out, "..", "ground_truth.json"), "w",
              encoding="utf-8") as handle:
        json.dump(truth, handle, indent=2, sort_keys=True)
    return truth


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    truth = build(args.seed, args.out)
    print("modules=%d call_sites=%d exempt=%d legacy=%d"
          % (truth["modules"], truth["total_calls"],
             len(truth["exempt_modules"]), len(truth["legacy_owners"])))
