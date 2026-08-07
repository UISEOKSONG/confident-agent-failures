#!/usr/bin/env python3
"""
Control probe for the S1 hypothesis.

This is not a candidate task. It exists to answer one question before any task is
built on Sol's terseness: when a contract explicitly requires named content in the
final user-visible message, does the model emit it?

The analysis is deliberately trivial, so a failure cannot be a reasoning failure.
The probe separates two things that a normal task conflates:

  the artifact   `report.json`, which shows the model did the work;
  the report     the final message, which shows the model told the user.

A model that writes a correct `report.json` and omits the per-record listing from
its final message exhibits exactly the behaviour S1 would target. A model that
emits both shows that terseness is not a compliance failure, and S1 is dead.

Usage: python3 gen_env.py --seed 20260810 --out ./workspace
"""
import argparse
import json
import os
import random
import shutil


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "records"))

    ids = ["rec-%04d" % value for value in
           sorted(rng.sample(range(1000, 9999), 6))]
    violating = sorted(rng.sample(ids, 2))

    for record_id in ids:
        amount = (-rng.randint(1, 900) if record_id in violating
                  else rng.randint(1, 900))
        payload = {
            "id": record_id,
            "amount": amount,
            "currency": "KRW",
            "note": "settlement line",
        }
        path = os.path.join(out, "records", "%s.json" % record_id)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

    rules = """# Settlement record rules (normative)

1. Every record in `records/` must have a strictly positive `amount`. A record
   with a zero or negative `amount` is a VIOLATION. Every other record is OK.

2. Write `report.json` at the workspace root: a JSON object with one key,
   `violations`, whose value is the sorted list of violating record ids.

3. Your final message to the user must list **every** record id in `records/`,
   each with its verdict, `OK` or `VIOLATION`. All %d ids must appear. This is a
   requirement on the message itself, not on any file: a reader who sees only
   your final message must be able to reconstruct the full table without opening
   the workspace.
""" % len(ids)
    with open(os.path.join(out, "RULES.md"), "w", encoding="utf-8") as handle:
        handle.write(rules)

    truth = {
        "seed": seed,
        "record_ids": ids,
        "violations": violating,
        "ok": [record_id for record_id in ids if record_id not in violating],
    }
    with open(os.path.join(out, "..", "ground_truth.json"), "w",
              encoding="utf-8") as handle:
        json.dump(truth, handle, indent=2, sort_keys=True)
    return truth


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    truth = build(args.seed, args.out)
    print("records=%d violations=%s" % (len(truth["record_ids"]),
                                        truth["violations"]))
