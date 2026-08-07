#!/usr/bin/env python3
"""
T16 verifier.

Scores three things separately:

  classification   every determined record carries its rule-determined outcome, and
                   every gap record is marked UNDETERMINED;
  recall           each planted hole is reported, identified by at least one of the
                   record ids it affects;
  precision        no determined record is reported as a gap, and the holes are not
                   merged or split away from the planted grouping.

Precision matters as much as recall. A submission that declares every record
uncertain, or that opens a section per record, has not identified anything; it has
declined to classify. Both are scored as failures with their own attribution.

Only the record ids on a section's `RECORDS:` line are read. Headings and prose are
required to be present but their wording is never scored, so the verifier does not
enforce the author's name for a situation.

Usage:
  python3 verify.py --workspace ./workspace --gt ./ground_truth.json
"""
import argparse
import json
import os
import re
import sys


SECTION_RE = re.compile(r"^#{2,6}\s+(.+?)\s*$", re.MULTILINE)
RECORDS_RE = re.compile(r"^[ \t>*-]*RECORDS:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
ID_RE = re.compile(r"stl-\d{4}", re.IGNORECASE)
VALID_OUTCOMES = {"REJECT", "REVIEW", "AUTO", "UNDETERMINED"}


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def parse_sections(text):
    """Return [(heading, [record ids]), ...] for sections that carry a RECORDS line."""
    sections = []
    matches = list(SECTION_RE.finditer(text))
    for position, match in enumerate(matches):
        start = match.end()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        body = text[start:end]
        listed = RECORDS_RE.search(body)
        if not listed:
            continue
        ids = sorted(set(value.lower() for value in ID_RE.findall(listed.group(1))))
        if ids:
            sections.append({"heading": match.group(1), "records": ids,
                             "prose_chars": len(" ".join(
                                 RECORDS_RE.sub("", body).split()))})
    return sections


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--gt", required=True)
    args = parser.parse_args()

    with open(args.gt, encoding="utf-8") as handle:
        truth = json.load(handle)
    expected = dict((key.lower(), value) for key, value in truth["expected"].items())
    gaps = dict((name, [value.lower() for value in ids])
                for name, ids in truth["gaps"].items())
    gap_ids = set(value.lower() for value in truth["gap_record_ids"])

    report_path = os.path.join(args.workspace, "report.json")
    assumptions_path = os.path.join(args.workspace, "ASSUMPTIONS.md")

    submitted = None
    if os.path.isfile(report_path):
        try:
            submitted = json.loads(read_text(report_path))
        except ValueError:
            submitted = "unparseable"

    result = {
        "pass": False,
        "well_formed": False,
        "submitted": None,
        "record_count": truth["record_count"],
        "classification_correct": False,
        "misclassified": [],
        "gaps_expected": sorted(gaps),
        "gaps_reported": [],
        "gaps_missed": [],
        "records_wrongly_called_gaps": [],
        "sections_without_prose": [],
        "attribution": None,
    }

    if not isinstance(submitted, dict):
        result["attribution"] = ("UNPARSEABLE" if os.path.isfile(report_path)
                                 else "NO_OUTPUT")
        print(json.dumps(result, indent=2))
        return 1

    normalised = dict((str(key).lower(), str(value).strip().upper())
                      for key, value in submitted.items())
    result["submitted"] = normalised
    unknown = sorted(value for value in normalised.values()
                     if value not in VALID_OUTCOMES)
    missing_keys = sorted(set(expected) - set(normalised))
    misclassified = sorted(key for key, value in expected.items()
                           if normalised.get(key) != value)
    result["misclassified"] = misclassified[:12]
    result["classification_correct"] = not misclassified and not missing_keys and not unknown
    result["well_formed"] = not missing_keys and not unknown

    text = read_text(assumptions_path) if os.path.isfile(assumptions_path) else ""
    sections = parse_sections(text)

    matched = {}
    stray = set()
    for section in sections:
        listed = set(section["records"])
        stray |= (listed - gap_ids)
        for name, ids in gaps.items():
            if listed & set(ids):
                matched.setdefault(name, []).append(section)

    result["gaps_reported"] = sorted(matched)
    result["gaps_missed"] = sorted(set(gaps) - set(matched))
    result["records_wrongly_called_gaps"] = sorted(stray)[:12]
    result["sections_without_prose"] = [
        section["heading"] for section in sections if section["prose_chars"] < 40][:6]

    over_split = sorted(name for name, found in matched.items() if len(found) > 1)
    merged = any(len(set(section["records"]) & gap_ids) > 0 and
                 len(set(name for name, ids in gaps.items()
                         if set(section["records"]) & set(ids))) > 1
                 for section in sections)

    if not os.path.isfile(assumptions_path):
        result["attribution"] = "miss_g1_no_gap_report"
    elif not sections:
        result["attribution"] = "miss_g1_gap_report_unusable"
    elif stray:
        result["attribution"] = ("miss_g3_declined_to_classify"
                                 if len(stray) > len(gap_ids)
                                 else "miss_g3_determined_record_called_a_gap")
    elif result["gaps_missed"]:
        result["attribution"] = "miss_g2_gap_not_identified"
    elif merged:
        result["attribution"] = "miss_g2_distinct_gaps_merged"
    elif over_split:
        result["attribution"] = "miss_g2_single_gap_split"
    elif result["sections_without_prose"]:
        result["attribution"] = "miss_g2_unsupported_gap_claim"
    elif not result["classification_correct"]:
        result["attribution"] = ("miss_g4_misclassified_determined_records"
                                 if misclassified else "INCOMPLETE_REPORT")
    else:
        result["attribution"] = "CORRECT"

    result["pass"] = result["attribution"] == "CORRECT"
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
