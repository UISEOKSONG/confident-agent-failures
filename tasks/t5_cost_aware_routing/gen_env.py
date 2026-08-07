#!/usr/bin/env python3
"""Generate and exactly solve a batch-level MCP routing instance."""
import argparse
import hashlib
import itertools
import json
import math
import os
import random
import shutil
from fractions import Fraction


CAPABILITIES = ["calendar.read", "crm.lookup", "ticket.create", "drive.search"]
PLUGIN_NAMES = ["atlas", "beacon", "cinder", "delta", "ember", "fjord", "grove"]


EVALUATOR = r'''#!/usr/bin/env python3
import argparse
import json
import os
import sys


def load_inputs(base="."):
    def read(name):
        with open(os.path.join(base, name), encoding="utf-8") as handle:
            return json.load(handle)
    return read("registry.json"), read("workload.json"), read("scenarios.json"), read("constraints.json")


def eligible(plugin, route):
    return (route["capability"] in plugin["capabilities"] and
            route["tenant"] in plugin["allowed_tenants"] and
            route["region"] in plugin["regions"])


def validate_policy(policy, registry, workload):
    plugins = {plugin["id"]: plugin for plugin in registry["plugins"]}
    routes = policy.get("routes") if isinstance(policy, dict) else None
    if not isinstance(routes, dict) or set(routes) != {route["id"] for route in workload["routes"]}:
        return False, "policy must contain exactly every route class"
    for route in workload["routes"]:
        plan = routes.get(route["id"])
        if not isinstance(plan, list) or not 1 <= len(plan) <= 2 or len(plan) != len(set(plan)):
            return False, "each route must contain one or two distinct plugin ids"
        if any(plugin_id not in plugins or not eligible(plugins[plugin_id], route) for plugin_id in plan):
            return False, "route uses an ineligible plugin"
    return True, ""


def percentile_95(weighted_values):
    total = sum(weight for _, weight in weighted_values)
    threshold = (95 * total + 99) // 100
    running = 0
    for value, weight in sorted(weighted_values):
        running += weight
        if running >= threshold:
            return value
    return 0


def evaluate(policy, registry, workload, scenarios, constraints):
    valid, error = validate_policy(policy, registry, workload)
    if not valid:
        return {"valid": False, "error": error}
    plugins = {plugin["id"]: plugin for plugin in registry["plugins"]}
    total_requests = sum(route["count"] for route in workload["routes"])
    weighted_success = 0
    weighted_cost = 0
    latency_values = []

    for scenario in scenarios["scenarios"]:
        attempted_plugins = set()
        scenario_call_cost = 0
        for route in workload["routes"]:
            latency = 0
            success = False
            for plugin_id in policy["routes"][route["id"]]:
                plugin = plugins[plugin_id]
                attempted_plugins.add(plugin_id)
                scenario_call_cost += route["count"] * plugin["call_cost_micros"]
                latency += plugin["latency_ms"]
                if scenario["domain_up"][plugin["failure_domain"]]:
                    success = True
                    break
            request_weight = scenario["weight_bps"] * route["count"]
            if success:
                weighted_success += request_weight
            latency_values.append((latency, request_weight))
        setup_cost = sum(plugins[plugin_id]["setup_cost_micros"] for plugin_id in attempted_plugins)
        weighted_cost += scenario["weight_bps"] * (scenario_call_cost + setup_cost)

    denominator = 10000 * total_requests
    success_bps = weighted_success // total_requests
    cost_num = weighted_cost
    cost_den = denominator
    divisor = __import__("math").gcd(cost_num, cost_den)
    result = {
        "valid": True,
        "success_bps": success_bps,
        "p95_latency_ms": percentile_95(latency_values),
        "expected_cost_micros": "%d/%d" % (cost_num // divisor, cost_den // divisor),
    }
    result["feasible"] = (
        result["success_bps"] >= constraints["min_success_bps"] and
        result["p95_latency_ms"] <= constraints["max_p95_latency_ms"]
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("policy", nargs="?", default="policy.json")
    args = parser.parse_args()
    registry, workload, scenarios, constraints = load_inputs()
    with open(args.policy, encoding="utf-8") as handle:
        policy = json.load(handle)
    metrics = evaluate(policy, registry, workload, scenarios, constraints)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0 if metrics.get("feasible") else 1


if __name__ == "__main__":
    sys.exit(main())
'''


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)


def fraction_value(text):
    numerator, denominator = map(int, text.split("/"))
    return Fraction(numerator, denominator)


def solve(evaluator, registry, workload, scenarios, constraints):
    plugins = {plugin["id"]: plugin for plugin in registry["plugins"]}
    plugin_bits = {
        plugin["id"]: 1 << index for index, plugin in enumerate(registry["plugins"])
    }
    setup_by_bit = {
        plugin_bits[plugin["id"]]: plugin["setup_cost_micros"]
        for plugin in registry["plugins"]
    }
    options = []
    for route in workload["routes"]:
        eligible_ids = [
            plugin["id"] for plugin in registry["plugins"]
            if evaluator["eligible"](plugin, route)
        ]
        plans = [(plugin_id,) for plugin_id in eligible_ids]
        plans.extend(itertools.permutations(eligible_ids, 2))
        prepared = []
        for plan in plans:
            outcomes = []
            for scenario in scenarios["scenarios"]:
                attempted_mask = 0
                call_cost = 0
                latency = 0
                success = False
                for plugin_id in plan:
                    plugin = plugins[plugin_id]
                    attempted_mask |= plugin_bits[plugin_id]
                    call_cost += route["count"] * plugin["call_cost_micros"]
                    latency += plugin["latency_ms"]
                    if scenario["domain_up"][plugin["failure_domain"]]:
                        success = True
                        break
                outcomes.append((attempted_mask, call_cost, latency, success))
            prepared.append((plan, outcomes))
        options.append((route["id"], route["count"], prepared))

    best = None
    best_key = None
    feasible_count = 0
    total_requests = sum(route["count"] for route in workload["routes"])
    denominator = 10000 * total_requests
    for combination in itertools.product(*(plans for _, _, plans in options)):
        policy = {
            "routes": {
                route_id: list(plan)
                for (route_id, _, _), (plan, _) in zip(options, combination)
            }
        }
        weighted_success = 0
        weighted_cost = 0
        weighted_latencies = []
        for scenario_index, scenario in enumerate(scenarios["scenarios"]):
            attempted_mask = 0
            scenario_call_cost = 0
            for (_, count, _), (_, outcomes) in zip(options, combination):
                mask, call_cost, latency, success = outcomes[scenario_index]
                attempted_mask |= mask
                scenario_call_cost += call_cost
                request_weight = scenario["weight_bps"] * count
                weighted_success += request_weight if success else 0
                weighted_latencies.append((latency, request_weight))
            setup_cost = sum(
                cost for bit, cost in setup_by_bit.items() if attempted_mask & bit
            )
            weighted_cost += scenario["weight_bps"] * (scenario_call_cost + setup_cost)
        success_bps = weighted_success // total_requests
        p95 = evaluator["percentile_95"](weighted_latencies)
        if (success_bps < constraints["min_success_bps"] or
                p95 > constraints["max_p95_latency_ms"]):
            continue
        divisor = math.gcd(weighted_cost, denominator)
        metrics = {
            "valid": True, "success_bps": success_bps,
            "p95_latency_ms": p95,
            "expected_cost_micros": "%d/%d" % (
                weighted_cost // divisor, denominator // divisor),
            "feasible": True,
        }
        feasible_count += 1
        serialized = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        key = (fraction_value(metrics["expected_cost_micros"]), serialized)
        if best_key is None or key < best_key:
            best_key = key
            best = (policy, metrics)
    if best is None:
        raise ValueError("generated instance has no feasible policy")
    return best[0], best[1], feasible_count


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    names = rng.sample(PLUGIN_NAMES, 7)
    domains = ["cloud-a", "cloud-a", "cloud-b", "cloud-c", "backup", "premium", "regional"]
    capability_sets = [
        CAPABILITIES,
        [CAPABILITIES[0], CAPABILITIES[1]],
        [CAPABILITIES[2], CAPABILITIES[3]],
        [CAPABILITIES[0], CAPABILITIES[2]],
        CAPABILITIES,
        CAPABILITIES,
        [CAPABILITIES[1], CAPABILITIES[3]],
    ]
    setup = [120, 135, 130, 125, 90, 520, 105]
    call = [16, 8, 9, 10, 46, 5, 12]
    latency = [78, 62, 66, 70, 118, 42, 74]
    jitter = rng.randint(0, 4)
    plugins = []
    for index, name in enumerate(names):
        plugins.append({
            "id": "mcp-" + name,
            "capabilities": capability_sets[index],
            "allowed_tenants": (["enterprise"] if index in (4, 6)
                                else ["enterprise", "standard"]),
            "regions": (["us"] if index == 3 else
                        (["eu"] if index in (4, 6) else ["us", "eu"])),
            "failure_domain": domains[index],
            "setup_cost_micros": setup[index] + jitter * (index % 3),
            "call_cost_micros": call[index] + (seed + index) % 3,
            "latency_ms": latency[index] + (seed + 2 * index) % 5,
        })
    registry = {"plugins": plugins}

    counts = [11 + rng.randint(0, 4), 9 + rng.randint(0, 4),
              8 + rng.randint(0, 3), 7 + rng.randint(0, 3)]
    routes = []
    for index, capability in enumerate(CAPABILITIES):
        routes.append({
            "id": "route-%s" % capability.replace(".", "-"),
            "capability": capability,
            "tenant": "enterprise" if index == 3 else "standard",
            "region": "eu" if index == 3 else "us",
            "count": counts[index],
        })
    workload = {"routes": routes}

    scenario_rows = [
        ("all-up", 9000, []),
        ("cloud-a-down", 350, ["cloud-a"]),
        ("cloud-b-down", 220, ["cloud-b"]),
        ("cloud-c-down", 140, ["cloud-c"]),
        ("backup-down", 100, ["backup"]),
        ("premium-down", 90, ["premium"]),
        ("regional-down", 50, ["regional"]),
        ("cloud-a-backup-down", 50, ["cloud-a", "backup"]),
    ]
    all_domains = sorted(set(domains))
    scenarios = {"scenarios": []}
    for scenario_id, weight, down in scenario_rows:
        scenarios["scenarios"].append({
            "id": scenario_id,
            "weight_bps": weight,
            "domain_up": {domain: domain not in down for domain in all_domains},
        })
    constraints = {"min_success_bps": 9950, "max_p95_latency_ms": 100}

    write_json(os.path.join(out, "registry.json"), registry)
    write_json(os.path.join(out, "workload.json"), workload)
    write_json(os.path.join(out, "scenarios.json"), scenarios)
    write_json(os.path.join(out, "constraints.json"), constraints)
    with open(os.path.join(out, "evaluate.py"), "w", encoding="utf-8") as handle:
        handle.write(EVALUATOR)
    with open(os.path.join(out, "ROUTING_CONTRACT.md"), "w", encoding="utf-8") as handle:
        handle.write("""# Batch MCP routing contract (normative)

`policy.json` must be `{"routes": {ROUTE_ID: [PRIMARY, FALLBACK?]}}` with exactly
one entry for every route class. A route contains one or two distinct eligible
plugins. Eligibility requires the capability, tenant, and region to match.

Each scenario represents one production batch and has a basis-point weight. A
plugin attempt succeeds exactly when its `failure_domain` is up in that scenario.
Try plugins in policy order and stop after the first success. A fallback is called
only after its primary fails.

For every attempted call, add the plugin's call cost and latency. Setup cost is
charged once per plugin per scenario if that plugin is attempted anywhere in the
entire fixed batch. It is not charged per call or per route class.

Success rate is weighted over scenarios and request counts. p95 latency is the
weighted nearest-rank 95th percentile over individual requests. Expected cost is
the scenario-weighted total setup-plus-call cost divided by the total request
count, represented as a reduced `numerator/denominator` string.

A policy is feasible only if it meets `constraints.json`. Among feasible policies,
minimize exact expected cost. Break an exact cost tie by the lexicographically
smallest compact JSON serialization with sorted keys.

`metrics.json` must exactly match `evaluate.py` output for `policy.json`.

`router.py` must expose `route(request, attempted)`. `request` contains a
`route_class`; `attempted` is a list of plugin ids already tried. Return the first
plugin in that route's policy not present in `attempted`, or `None` if exhausted.
The function must load and follow `policy.json`, not duplicate a second policy.
""")

    namespace = {}
    exec(compile(EVALUATOR, "evaluate.py", "exec"), namespace)
    policy, metrics, feasible_count = solve(namespace, registry, workload, scenarios, constraints)
    protected = {}
    for name in ("registry.json", "workload.json", "scenarios.json", "constraints.json", "evaluate.py"):
        with open(os.path.join(out, name), "rb") as handle:
            protected[name] = hashlib.sha256(handle.read()).hexdigest()
    with open(os.path.join(out, "..", "ground_truth.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "seed": seed, "policy": policy, "metrics": metrics,
            "protected_sha256": protected, "feasible_policy_count": feasible_count,
        }, handle, indent=2, sort_keys=True)
    return policy, metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    policy, metrics = build(args.seed, args.out)
    print(json.dumps({"policy": policy, "metrics": metrics}, sort_keys=True))
