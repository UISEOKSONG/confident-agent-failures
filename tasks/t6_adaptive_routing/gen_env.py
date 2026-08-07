#!/usr/bin/env python3
"""Generate an adaptive MCP routing task with an exact finite-world solution."""
import argparse
import functools
import hashlib
import itertools
import json
import math
import os
import random
import shutil


CAPABILITIES = ["calendar.sync", "crm.enrich", "incident.open"]
NAMES = ["amber", "birch", "coral", "dune", "elm", "flint"]


SIMULATOR = r'''#!/usr/bin/env python3
import importlib.util
import json
import math
import os
import sys


def read_json(name):
    with open(name, encoding="utf-8") as handle:
        return json.load(handle)


def eligible(plugin, request):
    return (request["capability"] in plugin["capabilities"] and
            request["tenant"] in plugin["allowed_tenants"] and
            request["region"] in plugin["regions"])


def load_router(path="router.py"):
    spec = importlib.util.spec_from_file_location("candidate_router", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def simulate(router):
    registry = read_json("registry.json")
    routes = read_json("routes.json")
    scenarios = read_json("scenarios.json")
    plugins = {plugin["id"]: plugin for plugin in registry["plugins"]}
    root_policy = {}
    metrics = {}
    for request in routes["routes"]:
        success_weight = 0
        cost_weight = 0
        first_actions = set()
        for world in scenarios["scenarios"]:
            attempts = []
            remaining = request["initial_budget"]
            spent = 0
            succeeded = False
            for _ in range(len(plugins) + 1):
                action = router.choose_next(dict(request), list(attempts), remaining)
                if not attempts:
                    first_actions.add(action)
                if action is None:
                    break
                if (action not in plugins or action in {a["plugin_id"] for a in attempts} or
                        not eligible(plugins[action], request) or
                        plugins[action]["cost_units"] > remaining):
                    raise ValueError("router returned an invalid action")
                cost = plugins[action]["cost_units"]
                spent += cost
                remaining -= cost
                if world["plugin_success"][action]:
                    succeeded = True
                    break
                attempts.append({"plugin_id": action, "outcome": "failure"})
            if succeeded:
                success_weight += world["weight_bps"]
            cost_weight += world["weight_bps"] * spent
        if len(first_actions) != 1:
            raise ValueError("first action must not depend on the hidden scenario")
        root_policy[request["id"]] = next(iter(first_actions))
        divisor = math.gcd(cost_weight, 10000)
        metrics[request["id"]] = {
            "success_bps": success_weight,
            "expected_cost_units": "%d/%d" % (cost_weight // divisor, 10000 // divisor),
        }
    return {"root_policy": root_policy, "metrics": metrics}


def main():
    try:
        result = simulate(load_router())
    except Exception as exc:
        print(json.dumps({"valid": False, "error": "%s: %s" % (type(exc).__name__, exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)


def solver_for_route(request, plugins, worlds):
    eligible_plugins = sorted(
        plugin["id"] for plugin in plugins
        if (request["capability"] in plugin["capabilities"] and
            request["tenant"] in plugin["allowed_tenants"] and
            request["region"] in plugin["regions"])
    )
    plugin_map = {plugin["id"]: plugin for plugin in plugins}
    weights = [world["weight_bps"] for world in worlds]

    @functools.lru_cache(maxsize=None)
    def solve(world_indices, failed, budget):
        current_weight = sum(weights[index] for index in world_indices)
        best = (0, 0, None)
        for plugin_id in eligible_plugins:
            if plugin_id in failed or plugin_map[plugin_id]["cost_units"] > budget:
                continue
            success_indices = tuple(
                index for index in world_indices
                if worlds[index]["plugin_success"][plugin_id]
            )
            failure_indices = tuple(
                index for index in world_indices
                if not worlds[index]["plugin_success"][plugin_id]
            )
            immediate_success = sum(weights[index] for index in success_indices)
            future_success = 0
            future_cost = 0
            if failure_indices:
                future_success, future_cost, _ = solve(
                    failure_indices, tuple(sorted(failed + (plugin_id,))),
                    budget - plugin_map[plugin_id]["cost_units"],
                )
            total_success = immediate_success + future_success
            total_cost = current_weight * plugin_map[plugin_id]["cost_units"] + future_cost
            candidate = (total_success, total_cost, plugin_id)
            if (candidate[0] > best[0] or
                    (candidate[0] == best[0] and candidate[1] < best[1]) or
                    (candidate[0] == best[0] and candidate[1] == best[1] and
                     candidate[2] is not None and
                     (best[2] is None or candidate[2] < best[2]))):
                best = candidate
        return best

    def state_for(failed):
        return tuple(
            index for index, world in enumerate(worlds)
            if all(not world["plugin_success"][plugin_id] for plugin_id in failed)
        )

    return eligible_plugins, solve, state_for


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    names = rng.sample(NAMES, 6)
    domains = ["cloud-a", "cloud-a", "cloud-b", "cloud-c", "premium", "cloud-b"]
    capability_sets = [
        CAPABILITIES,
        CAPABILITIES[:2],
        CAPABILITIES,
        CAPABILITIES[1:],
        CAPABILITIES,
        [CAPABILITIES[0], CAPABILITIES[2]],
    ]
    base_costs = [4, 5, 7, 9, 12, 6]
    plugins = []
    for index, name in enumerate(names):
        plugins.append({
            "id": "mcp-" + name,
            "capabilities": capability_sets[index],
            "allowed_tenants": ["standard", "enterprise"],
            "regions": ["us", "eu"],
            "failure_domain": domains[index],
            "cost_units": base_costs[index] + ((seed + index) % 2),
        })
    registry = {"plugins": plugins}
    ids = [plugin["id"] for plugin in plugins]

    success_patterns = [
        [1, 1, 1, 1, 1, 1],
        [0, 0, 1, 1, 1, 1],
        [0, 1, 1, 1, 1, 1],
        [1, 1, 0, 1, 1, 0],
        [0, 0, 0, 1, 1, 0],
        [1, 1, 1, 0, 1, 1],
        [0, 1, 0, 1, 1, 1],
        [0, 0, 0, 0, 1, 0],
        [0, 0, 0, 0, 0, 0],
    ]
    weights = [6500, 1000, 700, 500, 400, 300, 250, 200, 150]
    worlds = []
    for index, (pattern, weight) in enumerate(zip(success_patterns, weights)):
        worlds.append({
            "id": "world-%02d" % index,
            "weight_bps": weight,
            "plugin_success": {plugin_id: bool(value) for plugin_id, value in zip(ids, pattern)},
        })
    scenarios = {"scenarios": worlds}
    budgets = [15 + rng.randint(0, 2), 17 + rng.randint(0, 2), 18 + rng.randint(0, 2)]
    routes = {"routes": []}
    for index, capability in enumerate(CAPABILITIES):
        routes["routes"].append({
            "id": "route-" + capability.replace(".", "-"),
            "capability": capability,
            "tenant": "enterprise" if index == 2 else "standard",
            "region": "eu" if index == 1 else "us",
            "initial_budget": budgets[index],
        })

    write_json(os.path.join(out, "registry.json"), registry)
    write_json(os.path.join(out, "routes.json"), routes)
    write_json(os.path.join(out, "scenarios.json"), scenarios)
    with open(os.path.join(out, "simulate.py"), "w", encoding="utf-8") as handle:
        handle.write(SIMULATOR)
    with open(os.path.join(out, "ADAPTIVE_CONTRACT.md"), "w", encoding="utf-8") as handle:
        handle.write("""# Adaptive MCP routing contract (normative)

The scenario table is a finite prior over production worlds. Weights sum to
10,000 basis points. `plugin_success` is deterministic within a world and is the
normative outcome model; failure-domain labels explain correlation but do not
replace the explicit table.

`choose_next(request, attempts, remaining_budget)` receives a route record, a list
of prior `{\"plugin_id\": ..., \"outcome\": \"failure\"|\"success\"}` objects, and
an integer budget. Return an eligible, untried plugin whose cost fits, or `None`.
If any attempt succeeded, return `None`.

Condition the prior on every observed failure. At each state, choose a policy that
lexicographically (1) maximizes the conditional probability of eventual success,
then (2) minimizes conditional expected total cost from that state. Break a full
tie by lexicographically smallest plugin id. A plugin's cost is paid in every world
where it is attempted; after failure, subtract it from the remaining budget and
optimize the continuation recursively. Returning `None` has zero success and cost.

`root_policy.json` maps each route id to the first action at its initial budget.
`metrics.json` maps each route id to `success_bps` and reduced-fraction
`expected_cost_units` under the complete adaptive policy. Run `simulate.py` to
obtain both outputs for a candidate router.
""")

    actions = []
    root_policy = {}
    metrics = {}
    for request in routes["routes"]:
        eligible_ids, solve, state_for = solver_for_route(request, plugins, worlds)
        for budget in range(0, 23):
            for size in range(len(eligible_ids) + 1):
                for failed in itertools.combinations(eligible_ids, size):
                    state = state_for(failed)
                    if not state:
                        action = None
                    else:
                        action = solve(state, tuple(sorted(failed)), budget)[2]
                    actions.append({
                        "route_id": request["id"], "remaining_budget": budget,
                        "failed": list(failed), "action": action,
                    })
        initial_worlds = tuple(range(len(worlds)))
        success_weight, cost_weight, action = solve(
            initial_worlds, tuple(), request["initial_budget"]
        )
        root_policy[request["id"]] = action
        divisor = math.gcd(cost_weight, 10000)
        metrics[request["id"]] = {
            "success_bps": success_weight,
            "expected_cost_units": "%d/%d" % (
                cost_weight // divisor, 10000 // divisor),
        }

    protected = {}
    for name in ("registry.json", "routes.json", "scenarios.json", "simulate.py", "ADAPTIVE_CONTRACT.md"):
        with open(os.path.join(out, name), "rb") as handle:
            protected[name] = hashlib.sha256(handle.read()).hexdigest()
    with open(os.path.join(out, "..", "ground_truth.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "seed": seed, "root_policy": root_policy, "metrics": metrics,
            "actions": actions, "protected_sha256": protected,
        }, handle, indent=2, sort_keys=True)
    return root_policy, metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    root_policy, metrics = build(args.seed, args.out)
    print(json.dumps({"root_policy": root_policy, "metrics": metrics}, sort_keys=True))
