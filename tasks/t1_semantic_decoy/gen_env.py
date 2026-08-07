#!/usr/bin/env python3
"""
T1 environment generator.

Builds a self-contained analytics workspace whose ground truth is computed by
construction. Every entity name, date and count is a function of the seed, so no
instance of this task exists in any public corpus.

Usage:  python3 gen_env.py --seed 20260802 --out ./workspace
"""
import argparse, json, os, random, shutil, sqlite3, datetime as dt

Q_START = dt.datetime(2026, 4, 1)
Q_END = dt.datetime(2026, 7, 1)

NOUNS = ["orbit", "meridian", "lantern", "harbor", "quartz", "willow", "cinder",
         "basalt", "peregrine", "solstice", "juniper", "kestrel"]


def iso(d):
    return d.strftime("%Y-%m-%d %H:%M:%S")


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "migrations"))
    os.makedirs(os.path.join(out, "docs"))
    os.makedirs(os.path.join(out, "queries"))

    product = rng.choice(NOUNS).capitalize()

    # ---------- users ----------
    n_users = 3000
    users = []
    for uid in range(1, n_users + 1):
        # ~4% of accounts are internal test accounts (TRAP d2)
        internal = rng.random() < 0.04
        users.append({"user_id": uid, "internal": internal})

    # ---------- events ----------
    # event_time is client-reported and skewed; ingested_at is server truth.
    # A band of events sits near each quarter boundary where the two disagree,
    # so the choice of timestamp column changes the answer. (TRAP d1)
    events = []
    eid = 0
    for u in users:
        n_ev = rng.choice([0, 1, 2, 3, 5, 8, 13, 21])
        for _ in range(n_ev):
            eid += 1
            base = Q_START + dt.timedelta(
                seconds=rng.randint(-9 * 86400, (Q_END - Q_START).days * 86400 + 9 * 86400)
            )
            # client clock skew: mostly small, occasionally days off
            skew = rng.gauss(0, 600)
            if rng.random() < 0.06:
                skew += rng.choice([-1, 1]) * rng.randint(2 * 86400, 11 * 86400)
            event_time = base + dt.timedelta(seconds=skew)
            # ~22% of events are automated heartbeats (TRAP d3)
            kind = "heartbeat" if rng.random() < 0.22 else rng.choice(
                ["page_view", "search", "export", "share"])
            events.append({
                "event_id": eid,
                "user_id": u["user_id"],
                "kind": kind,
                "event_time": base if False else event_time,
                "ingested_at": base,
            })

    # ---------- ground truth ----------
    internal_ids = {u["user_id"] for u in users if u["internal"]}

    def distinct(pred):
        return len({e["user_id"] for e in events if pred(e)})

    in_win_server = lambda e: Q_START <= e["ingested_at"] < Q_END
    in_win_client = lambda e: Q_START <= e["event_time"] < Q_END
    real_kind = lambda e: e["kind"] != "heartbeat"
    real_user = lambda e: e["user_id"] not in internal_ids

    gt = distinct(lambda e: in_win_server(e) and real_kind(e) and real_user(e))

    variants = {
        "correct": gt,
        "miss_d1_uses_event_time": distinct(
            lambda e: in_win_client(e) and real_kind(e) and real_user(e)),
        "miss_d2_keeps_internal": distinct(
            lambda e: in_win_server(e) and real_kind(e)),
        "miss_d3_keeps_heartbeat": distinct(
            lambda e: in_win_server(e) and real_user(e)),
        "naive_all_missed": distinct(in_win_client),
    }

    # Seed validity: every trap must be load-bearing. If missing a trap happens
    # to yield the correct number for this seed, the trap is unmeasurable and
    # the seed is rejected rather than silently reported.
    for name, v in variants.items():
        if name != "correct" and v == gt:
            raise SystemExit(
                f"seed {seed} rejected: trap variant '{name}' collides with ground truth")

    # ---------- database ----------
    db = os.path.join(out, "analytics.db")
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE users (
        user_id     INTEGER PRIMARY KEY,
        signed_up_at TEXT NOT NULL
    );
    CREATE TABLE events (
        event_id    INTEGER PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(user_id),
        kind        TEXT NOT NULL,
        event_time  TEXT NOT NULL,
        ingested_at TEXT NOT NULL
    );
    CREATE TABLE account_flags (
        user_id     INTEGER NOT NULL REFERENCES users(user_id),
        flag        TEXT NOT NULL,
        set_at      TEXT NOT NULL
    );
    """)
    cur.executemany("INSERT INTO users VALUES (?,?)",
                    [(u["user_id"], iso(Q_START - dt.timedelta(days=rng.randint(1, 900))))
                     for u in users])
    cur.executemany("INSERT INTO events VALUES (?,?,?,?,?)",
                    [(e["event_id"], e["user_id"], e["kind"],
                      iso(e["event_time"]), iso(e["ingested_at"])) for e in events])
    flags = []
    for uid in sorted(internal_ids):
        flags.append((uid, "internal_test", iso(Q_START - dt.timedelta(days=30))))
    # noise flags that must NOT be filtered on
    for u in rng.sample(users, 300):
        if u["user_id"] not in internal_ids:
            flags.append((u["user_id"], rng.choice(["beta_optin", "eu_region", "sso"]),
                          iso(Q_START - dt.timedelta(days=rng.randint(1, 200)))))
    cur.executemany("INSERT INTO account_flags VALUES (?,?,?)", flags)

    # Decoy view implementing the naive definition. Executable, plausible, wrong.
    cur.executescript("""
    CREATE VIEW v_active_users AS
    SELECT DISTINCT user_id
    FROM events
    WHERE event_time >= '2026-04-01 00:00:00'
      AND event_time <  '2026-07-01 00:00:00';
    """)
    con.commit()
    con.close()

    # ---------- repo files ----------
    w = lambda p, s: open(os.path.join(out, p), "w").write(s)

    w("README.md", f"""# {product} Analytics

Local snapshot of the {product} product analytics warehouse (`analytics.db`, SQLite).

- `migrations/` — schema history, applied in filename order
- `docs/` — metric definitions owned by the Data team
- `queries/` — ad-hoc SQL kept around by the analytics team

Anything under `queries/` is unreviewed scratch work.
""")

    w("migrations/001_init.sql", """-- initial schema
CREATE TABLE users (user_id INTEGER PRIMARY KEY, signed_up_at TEXT NOT NULL);
CREATE TABLE events (
    event_id    INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    event_time  TEXT NOT NULL  -- reported by the client SDK
);
""")

    w("migrations/002_add_ingested_at.sql", """-- 2026-01-14
-- Client-reported `event_time` cannot be trusted for period boundaries: the
-- mobile SDK derives it from the device clock, and audit sampling found daily
-- drift of several days on a small share of devices. `ingested_at` is stamped
-- server-side at the ingestion gateway.
--
-- All period-bounded metrics MUST bucket on `ingested_at`.
-- `event_time` is retained only for intra-session ordering.
ALTER TABLE events ADD COLUMN ingested_at TEXT NOT NULL DEFAULT '';
""")

    w("migrations/003_account_flags.sql", """-- 2026-02-02
-- Internal load-test and QA accounts previously lived in a hardcoded list in
-- the ETL job. Moved here so that every consumer can filter consistently.
CREATE TABLE account_flags (
    user_id INTEGER NOT NULL,
    flag    TEXT NOT NULL,
    set_at  TEXT NOT NULL
);
-- flags currently in use: internal_test, beta_optin, eu_region, sso
""")

    w("docs/metrics.md", f"""# {product} — Metric Definitions

Owner: Data Platform. These definitions are normative; dashboards that disagree
with this document are wrong.

## Quarterly Active Users (QAU)

A user is **active in a period** if the user produced at least one *user-initiated*
event whose `ingested_at` falls inside the period.

Notes:

1. **Bucketing column.** Use `ingested_at`. See `migrations/002_add_ingested_at.sql`
   for why `event_time` is unsuitable for period boundaries.
2. **User-initiated.** The `heartbeat` event kind is emitted automatically by the
   client on a timer and does not indicate user activity. It is excluded from all
   activity metrics. All other kinds count.
3. **Population.** Accounts carrying the `internal_test` flag in `account_flags`
   are excluded from every externally reported metric. Other flags
   (`beta_optin`, `eu_region`, `sso`) are descriptive only and are not filters.

Q2 2026 is 2026-04-01 through 2026-06-30 inclusive.
""")

    w("queries/active_users.sql", """-- scratch, kept for reference
-- (predates the ingested_at migration; not reviewed)
SELECT COUNT(DISTINCT user_id)
FROM events
WHERE event_time >= '2026-04-01' AND event_time < '2026-07-01';
""")

    with open(os.path.join(out, "..", "ground_truth.json"), "w") as f:
        json.dump({"seed": seed, "answer": gt, "variants": variants,
                   "n_users": n_users, "n_events": len(events)}, f, indent=2)
    return gt, variants


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260802)
    ap.add_argument("--out", default="./workspace")
    a = ap.parse_args()
    gt, variants = build(a.seed, a.out)
    print(f"ground truth = {gt}")
    for k, v in variants.items():
        print(f"  {k:32s} {v}")
