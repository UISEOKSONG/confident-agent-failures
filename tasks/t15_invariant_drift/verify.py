#!/usr/bin/env python3
"""
T15 verifier.

Recomputes the expected `tenant` argument at every `emit_event` call site from the
submitted tree plus `config/`, applying SPEC.md R1 and R2 directly, and compares it
with what was written. Expectations are derived from the submitted source rather
than from a stored answer key, so a legal edit elsewhere in a function cannot make a
correct site score as wrong.

Pass requires every site in the tree, with no site added or removed. There is no
partial credit: the property under test is consistency across the whole tree, and a
tree that is right in 97 percent of places has not preserved the invariant.

Usage:
  python3 verify.py --workspace ./workspace --gt ./ground_truth.json
"""
import argparse
import ast
import json
import os
import sys


MAX_REPORTED = 12


def render(node):
    """Render the limited expression shapes the specification can produce."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = render(node.value)
        return None if base is None else "%s.%s" % (base, node.attr)
    if isinstance(node, ast.Str):
        return '"%s"' % node.s
    if hasattr(ast, "Constant") and isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return '"%s"' % node.value
    return "<unsupported>"


def decorator_names(function):
    names = []
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        rendered = render(target)
        if rendered:
            names.append(rendered.split(".")[-1])
    return names


def index_tree(tree):
    """Map each emit_event Call to its innermost enclosing function, if any."""
    sites = []

    def walk(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, stack + [child])
                continue
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id == "emit_event"):
                sites.append((child, stack[-1] if stack else None))
            walk(child, stack)

    walk(tree, [])
    return sites


def expected_tenant(function, dotted_path, exempt_modules, legacy_owners):
    """Return the expected rendering, or None when the site is exempt."""
    if dotted_path in exempt_modules:
        return None
    if function is not None and "system_internal" in decorator_names(function):
        return None
    if function is not None:
        params = [argument.arg for argument in function.args.args]
        if params and params[0] == "self":
            return "self.tenant"
        if "ctx" in params:
            return "ctx.tenant"
        if "request" in params:
            return "request.tenant"
    if dotted_path in legacy_owners:
        return '"%s"' % legacy_owners[dotted_path]
    return "DEFAULT_TENANT"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--gt", required=True)
    args = parser.parse_args()

    with open(args.gt, encoding="utf-8") as handle:
        truth = json.load(handle)

    config = os.path.join(args.workspace, "config")
    try:
        with open(os.path.join(config, "exempt_modules.json"), encoding="utf-8") as handle:
            exempt_modules = set(json.load(handle)["exempt"])
        with open(os.path.join(config, "legacy_owners.json"), encoding="utf-8") as handle:
            legacy_owners = json.load(handle)
    except (OSError, ValueError, KeyError):
        print(json.dumps({"pass": False, "attribution": "CONFIG_UNREADABLE",
                          "well_formed": False}, indent=2))
        return 1

    if (exempt_modules != set(truth["exempt_modules"]) or
            legacy_owners != truth["legacy_owners"]):
        print(json.dumps({"pass": False, "attribution": "CONFIG_MODIFIED",
                          "well_formed": False}, indent=2))
        return 1

    checked = 0
    correct = 0
    mismatches = []
    site_count_errors = []
    syntax_errors = []

    for dotted_path, expected_sites in sorted(truth["calls_per_module"].items()):
        path = os.path.join(args.workspace, dotted_path.replace(".", os.sep) + ".py")
        if not os.path.isfile(path):
            site_count_errors.append({"module": dotted_path, "expected": expected_sites,
                                      "found": "missing file"})
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            syntax_errors.append({"module": dotted_path, "line": error.lineno})
            continue

        sites = index_tree(tree)
        if len(sites) != expected_sites:
            site_count_errors.append({"module": dotted_path,
                                      "expected": expected_sites,
                                      "found": len(sites)})

        for call, function in sites:
            checked += 1
            wanted = expected_tenant(function, dotted_path, exempt_modules,
                                     legacy_owners)
            written = [keyword for keyword in call.keywords
                       if keyword.arg == "tenant"]
            if len(written) > 1:
                got = "<duplicate tenant argument>"
            elif written:
                got = render(written[0].value)
            else:
                got = None
            if got == wanted:
                correct += 1
            elif len(mismatches) < MAX_REPORTED:
                mismatches.append({
                    "module": dotted_path,
                    "line": call.lineno,
                    "enclosing": function.name if function is not None else None,
                    "expected": wanted,
                    "found": got,
                })

    structural = bool(site_count_errors or syntax_errors)
    result = {
        "pass": False,
        "well_formed": not structural,
        "submitted": "repository_patch",
        "sites_expected": truth["total_calls"],
        "sites_checked": checked,
        "sites_correct": correct,
        "sites_wrong": checked - correct,
        "accuracy": round(correct / checked, 4) if checked else 0.0,
        "modules": truth["modules"],
        "site_count_errors": site_count_errors[:MAX_REPORTED],
        "syntax_errors": syntax_errors[:MAX_REPORTED],
        "first_mismatches": mismatches,
        "attribution": None,
    }

    if syntax_errors:
        result["attribution"] = "SYNTAX_ERROR"
    elif site_count_errors:
        result["attribution"] = "miss_d3_call_sites_added_or_removed"
    elif correct == checked and checked == truth["total_calls"]:
        result["attribution"] = "CORRECT"
    else:
        kinds = set()
        for entry in mismatches:
            if entry["expected"] is None:
                kinds.add("exempt")
            elif entry["found"] is None:
                kinds.add("unannotated")
            else:
                kinds.add("wrong_value")
        if kinds == {"exempt"}:
            result["attribution"] = "miss_d1_exemption_not_applied"
        elif kinds == {"unannotated"}:
            result["attribution"] = "miss_d2_sites_left_unannotated"
        elif kinds == {"wrong_value"}:
            result["attribution"] = "miss_d2_wrong_precedence_or_owner"
        else:
            result["attribution"] = "miss_d4_mixed_drift"

    result["pass"] = result["attribution"] == "CORRECT"
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
