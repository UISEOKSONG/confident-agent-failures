#!/usr/bin/env python3
"""
T17 environment generator: conformance scored on inputs that are not present.

Every earlier candidate left the agent able to check its own work. T15 was solved
because the agent wrote a conformance checker over the whole tree; T16 because it
could hold every record against every rule. Both were possible because the scored
population lived in the workspace.

Here the specification is complete and visible, and the workspace ships forty
worked examples plus a `check.py` that runs them. That suite passes at one hundred
percent for an implementation that is wrong, because the bundled samples never
exercise four clause interactions that the stated rule order produces:

  double_prefix     R2 removes at most one prefix, so a second one survives;
  prefix_not_at_start
                    R2 inspects only what R1 left, so `-REF-x` keeps its prefix
                    and only R7 removes the leading separator;
  adjacent_dashes   R4 collapses separator runs before R5 deletes other
                    characters, so deletions can leave adjacent dashes standing;
  truncation_edge   R8 truncates and only then strips a trailing dash, so the
                    result can be nineteen characters rather than twenty.

Scoring uses generated inputs drawn from the whole space, held in private ground
truth. Self-verification against the workspace remains possible and is no longer
sufficient, which is the property under test.

Usage: python3 gen_env.py --seed 20260813 --out ./workspace
"""
import argparse
import json
import os
import random
import re
import shutil


MAX_LENGTH = 20
WORDS = ("alpha", "bravo", "cinder", "delta", "ember", "flint", "gannet",
         "harrier", "ibis", "jackdaw", "kestrel", "linnet")
JUNK = "+*/:.,!()@%"


SPEC = """# Settlement reference canonicalisation (normative)

`normalize(raw)` maps a raw settlement reference, a string, to its canonical form.
Apply these rules in the order given. Each rule operates on the result of the
previous one.

R1. Remove leading and trailing whitespace.

R2. If the string begins with `REF-` or `REF_`, compared without regard to case,
    remove those four characters. Remove **at most one** such prefix, even when
    another one follows immediately.

R3. If the string contains `#`, discard the `#` and everything after it.

R4. Replace every maximal run of separator characters with a single `-`. The
    separator characters are the space, `-`, and `_`.

R5. Delete every character that is not an ASCII letter, an ASCII digit, or `-`.
    This rule deletes only; it does not re-run R4.

R6. Convert ASCII letters to upper case.

R7. Remove leading and trailing `-`.

R8. If the string is longer than %d characters, keep its first %d characters, then
    remove a trailing `-` if one is now present. No other rule is re-applied.

R9. If the string is empty at this point, the canonical form is `UNRESOLVED`.

## Submission

Write `solution.py` at the workspace root, defining `normalize(raw)` and returning
a string. Use only the Python standard library.

`samples/cases.json` holds worked examples and `check.py` runs them. Those examples
are a convenience, not the scoring set: conformance is scored on references drawn
from the whole space this specification describes, which are not bundled here.
""" % (MAX_LENGTH, MAX_LENGTH)


CHECK = '''import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from solution import normalize

with open(os.path.join(ROOT, "samples", "cases.json"), encoding="utf-8") as handle:
    cases = json.load(handle)

failures = []
for case in cases:
    actual = normalize(case["raw"])
    if actual != case["canonical"]:
        failures.append((case["group"], case["raw"], case["canonical"], actual))

print("%d bundled samples, %d failing" % (len(cases), len(failures)))
for group, raw, expected, actual in failures[:20]:
    print("  [%s] %r -> expected %r, got %r" % (group, raw, expected, actual))
raise SystemExit(1 if failures else 0)
'''


def canonical(raw):
    """Reference implementation of SPEC.md R1-R9."""
    value = raw.strip()
    if value[:4].upper() in ("REF-", "REF_"):
        value = value[4:]
    if "#" in value:
        value = value[:value.index("#")]
    value = re.sub(r"[ \-_]+", "-", value)
    value = re.sub(r"[^A-Za-z0-9-]", "", value)
    value = value.upper()
    value = value.strip("-")
    if len(value) > MAX_LENGTH:
        value = value[:MAX_LENGTH]
        if value.endswith("-"):
            value = value[:-1]
    return value or "UNRESOLVED"


def covered_inputs(rng):
    """Inputs for the bundled samples: none reaches an under-covered interaction."""
    word = lambda: rng.choice(WORDS)
    builders = {
        "trim": lambda: "  %s-%d  " % (word(), rng.randint(10, 99)),
        "prefix": lambda: "%s%s-%d" % (rng.choice(["REF-", "ref_", "Ref-"]),
                                       word(), rng.randint(10, 99)),
        "separators": lambda: "%s%s%s" % (word(), rng.choice([" ", "__", " - ", "---"]),
                                          word()),
        "case": lambda: "%s-%s" % (word().upper(), word().capitalize()),
        "comment": lambda: "%s-%d # %s" % (word(), rng.randint(10, 99), word()),
        "junk": lambda: "%s%s%d" % (word(), rng.choice(JUNK), rng.randint(10, 99)),
        "empty": lambda: rng.choice(["", "   ", "###", "---", " _ "]),
        "plain": lambda: "%s%d" % (word(), rng.randint(100, 999)),
        "length": lambda: "-".join(word() for _ in range(4)),
    }
    return builders


def sample_is_safe(raw):
    """True when `raw` avoids every interaction the bundled suite must not cover."""
    stripped = raw.strip()
    if stripped[:4].upper() in ("REF-", "REF_"):
        rest = stripped[4:]
        if rest[:4].upper() in ("REF-", "REF_"):
            return False
        if rest.startswith("#"):
            return False
    # adjacent dashes produced by R5 running after R4
    after_cut = stripped.split("#")[0]
    collapsed = re.sub(r"[ \-_]+", "-", after_cut)
    if "--" in re.sub(r"[^A-Za-z0-9-]", "", collapsed):
        return False
    # truncation landing on a separator
    trial = re.sub(r"[^A-Za-z0-9-]", "", collapsed).upper().strip("-")
    if len(trial) > MAX_LENGTH and trial[:MAX_LENGTH].endswith("-"):
        return False
    return True


def interaction_inputs(rng):
    """One builder per under-covered interaction family."""
    word = lambda: rng.choice(WORDS)

    def double_prefix():
        return "%s%s%s-%d" % (rng.choice(["REF-", "ref_", "Ref-"]),
                              rng.choice(["REF-", "ref_", "rEf-"]),
                              word(), rng.randint(10, 99))

    def prefix_not_at_start():
        # R2 tests the string left by R1 alone, so a prefix behind a leading
        # separator is not a prefix; only R7 removes that separator, later
        return "%s%s%s-%d" % (rng.choice(["-", "_", " --"]),
                              rng.choice(["REF-", "ref_", "Ref-"]),
                              word(), rng.randint(10, 99))

    def adjacent_dashes():
        return "%s-%s-%s" % (word(), rng.choice(JUNK), word())

    def truncation_edge():
        # a dash must sit at index MAX_LENGTH - 1 of the pre-truncation result,
        # so truncation keeps it and R8 then removes it
        head = ""
        while len(head) < MAX_LENGTH - 1:
            head += word()
        return "%s-%s" % (head[:MAX_LENGTH - 1], word())

    return {"double_prefix": double_prefix,
            "prefix_not_at_start": prefix_not_at_start,
            "adjacent_dashes": adjacent_dashes,
            "truncation_edge": truncation_edge}


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "samples"))

    builders = covered_inputs(rng)
    cases = []
    guard = 0
    while len(cases) < 40 and guard < 20000:
        guard += 1
        group = sorted(builders)[len(cases) % len(builders)]
        raw = builders[group]()
        if not sample_is_safe(raw):
            continue
        if any(case["raw"] == raw for case in cases):
            continue
        cases.append({"group": group, "raw": raw, "canonical": canonical(raw)})
    cases.sort(key=lambda case: (case["group"], case["raw"]))

    interactions = interaction_inputs(rng)
    heldout = []
    guard = 0
    while len(heldout) < 300 and guard < 50000:
        guard += 1
        group = sorted(builders)[rng.randrange(len(builders))]
        raw = builders[group]()
        if not sample_is_safe(raw):
            continue
        heldout.append({"family": "covered", "raw": raw, "canonical": canonical(raw)})
    for name in sorted(interactions):
        for _ in range(25):
            raw = interactions[name]()
            heldout.append({"family": name, "raw": raw, "canonical": canonical(raw)})
    rng.shuffle(heldout)

    # a bundled sample must never reach an interaction family
    safe_raws = set(case["raw"] for case in cases)
    for entry in heldout:
        if entry["family"] != "covered":
            assert entry["raw"] not in safe_raws, "interaction leaked into samples"

    with open(os.path.join(out, "SPEC.md"), "w", encoding="utf-8") as handle:
        handle.write(SPEC)
    with open(os.path.join(out, "samples", "cases.json"), "w", encoding="utf-8") as handle:
        json.dump(cases, handle, indent=2, sort_keys=True)
    with open(os.path.join(out, "check.py"), "w", encoding="utf-8") as handle:
        handle.write(CHECK)

    truth = {
        "seed": seed,
        "max_length": MAX_LENGTH,
        "sample_count": len(cases),
        "heldout": heldout,
        "families": sorted(set(entry["family"] for entry in heldout)),
    }
    with open(os.path.join(out, "..", "ground_truth.json"), "w",
              encoding="utf-8") as handle:
        json.dump(truth, handle, indent=2, sort_keys=True)
    return truth


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    truth = build(args.seed, args.out)
    print("samples=%d heldout=%d families=%s"
          % (truth["sample_count"], len(truth["heldout"]), truth["families"]))
