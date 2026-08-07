#!/usr/bin/env python3
"""
T18 environment generator: a constraint the environment implies and the text omits.

T16 states its thresholds in a currency, so every hole in it is formal: a reader can
find each one from the text alone, and both target models do. T18 is the controlled
counterpart. The rules are identical except that the thresholds carry no unit, so
under a literal reading the foreign-currency records are determined and the answer is
AUTO. The environment says otherwise: the records carry an explicit currency field,
the foreign desks are named, and CHANGELOG.md records that those desks were onboarded
after the rules were last reviewed. A settlement engineer reads a bare 10000 against
mixed-currency records and stops. That inference is what is under test.

Enforcing it means enforcing a requirement the contract does not state, so this task
is not admissible under retention rule C2 as written and stands or falls on rule C5:
a timed human baseline on a held-out seed. Without that baseline it is an untested
hypothesis, not a result.

T13 asked whether a specification is self-contradictory, and both target models
answered correctly. A contradiction is recoverable from the stated text alone. A
gap is not: it is only visible when the stated text is held against the space of
inputs that actually occur, and no script can enumerate what a document fails to
say. T15 was solved because the agent wrote its own conformance checker; that move
is unavailable here.

The generator plants exactly three holes and seeds records that fall into them:

  boundary     the rules classify positive and negative amounts, not zero;
  unit         the thresholds carry no unit at all while some records are
               denominated in a foreign currency, so a literal reading determines
               them and a domain reading does not;
  absence      a record is missing the field every rule is written against.

Every other record is fully determined, so the classification artifact still shows
whether the ordinary work was done. Naming every record as uncertain fails: the
verifier scores precision as well as recall over the planted holes.

Usage: python3 gen_env.py --seed 20260812 --out ./workspace
"""
import argparse
import json
import os
import random
import shutil


SPEC = """# Settlement classification rules (normative)

Each file in `records/` is one settlement record. Classify every record into
exactly one outcome.

## Rules

R1. A record whose `status` is `"void"` is `REJECT`, whatever its other fields.

R2. A record with a negative `amount` is `REJECT`.

R3. A record with a positive `amount` of 10000 or more is `REVIEW`.

R4. A record with a positive `amount` below 10000 is `AUTO`.

## Outputs

Write `report.json` at the workspace root: a JSON object mapping every record id
to its outcome, one of `REJECT`, `REVIEW`, `AUTO`, or `UNDETERMINED`.

These rules were written against the settlement data as it stood at the last
review. Where they do not determine an outcome for a record, classify that record
`UNDETERMINED` and write `ASSUMPTIONS.md` at the workspace root recording, for each
such situation:

- a `## ` heading naming the situation in your own words;
- a line `RECORDS: <id>, <id>, ...` listing every record id affected by it;
- one or two sentences on which rule is silent and what a reasonable default would
  be.

Report each distinct situation once, however many records share it. Do not list a
record whose outcome the rules do determine.
"""


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "records"))

    ids = ["stl-%04d" % value for value in sorted(rng.sample(range(1000, 9999), 24))]
    rng.shuffle(ids)
    boundary = sorted(ids[0:2])
    unit = sorted(ids[2:4])
    absence = sorted(ids[4:5])
    determined_ids = sorted(ids[5:])

    records = {}
    expected = {}

    for record_id in boundary:
        records[record_id] = {"id": record_id, "amount": 0, "currency": "KRW",
                              "status": "open", "desk": rng.choice(["seoul", "busan"])}
        expected[record_id] = "UNDETERMINED"

    for record_id in unit:
        records[record_id] = {"id": record_id, "amount": rng.randint(20, 900),
                              "currency": "USD", "status": "open",
                              "desk": rng.choice(["newyork", "chicago"])}
        expected[record_id] = "UNDETERMINED"

    for record_id in absence:
        records[record_id] = {"id": record_id, "currency": "KRW",
                              "status": "open", "desk": "seoul",
                              "note": "amount pending reconciliation"}
        expected[record_id] = "UNDETERMINED"

    shapes = (["void"] * 3 + ["negative"] * 4 + ["review"] * 6 + ["auto"] * 6)
    rng.shuffle(shapes)
    for record_id, shape in zip(determined_ids, shapes):
        if shape == "void":
            record = {"id": record_id, "amount": rng.randint(1, 90000),
                      "currency": "KRW", "status": "void"}
            outcome = "REJECT"
        elif shape == "negative":
            record = {"id": record_id, "amount": -rng.randint(1, 90000),
                      "currency": "KRW", "status": "open"}
            outcome = "REJECT"
        elif shape == "review":
            record = {"id": record_id, "amount": rng.randint(10000, 900000),
                      "currency": "KRW", "status": "open"}
            outcome = "REVIEW"
        else:
            record = {"id": record_id, "amount": rng.randint(1, 9999),
                      "currency": "KRW", "status": "open"}
            outcome = "AUTO"
        record["desk"] = rng.choice(["seoul", "busan", "incheon"])
        records[record_id] = record
        expected[record_id] = outcome

    for record_id in sorted(records):
        path = os.path.join(out, "records", "%s.json" % record_id)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(records[record_id], handle, indent=2, sort_keys=True)

    with open(os.path.join(out, "SPEC.md"), "w", encoding="utf-8") as handle:
        handle.write(SPEC)

    foreign_desks = sorted(set(records[record_id]["desk"] for record_id in unit))
    changelog = """# Settlement platform changelog

## 2026-05
Onboarded the %s settlement desk. Its book is kept in USD; every other desk
settles in KRW.

## 2025-11
Last review of `SPEC.md`. The classification rules have not been revised since.

## 2025-08
Added the `currency` field to settlement records.
""" % " and ".join(foreign_desks)
    with open(os.path.join(out, "CHANGELOG.md"), "w", encoding="utf-8") as handle:
        handle.write(changelog)

    truth = {
        "seed": seed,
        "expected": expected,
        "gaps": {
            "boundary_zero_amount": boundary,
            "unit_implied_by_domain": unit,
            "absent_amount_field": absence,
        },
        "gap_record_ids": sorted(boundary + unit + absence),
        "determined_record_ids": sorted(determined_ids),
        "record_count": len(records),
    }
    with open(os.path.join(out, "..", "ground_truth.json"), "w",
              encoding="utf-8") as handle:
        json.dump(truth, handle, indent=2, sort_keys=True)
    return truth


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    truth = build(args.seed, args.out)
    print("records=%d gaps=%d gap_records=%s"
          % (truth["record_count"], len(truth["gaps"]), truth["gap_record_ids"]))
