#!/usr/bin/env python3
"""admit.py <slot> -- may this slot proceed past discovery? (SKILL.md §3.3, ADR-0014)

Reads `.issues/<ID>/footprint.json` for slot <slot> and for every other slot past discovery, and
applies the two admission rules:

  one migration at a time   at most one slot past discovery with "migration": true
                            (skipped when admission.serializeMigrations is false)
  no shared paths           no footprint path of this slot overlaps one of another's

A missing footprint collides with everything: the slot waits until it is the only one past
discovery. Glob dialect: see pipeline_common.py.

Prints exactly one line and exits:
  ADMIT                       exit 0
  WAIT:<slot>:<reason>        exit 3   reason is migration | paths | nofootprint
  (usage or state error)      exit 2

The exit code matters as much as the line: `admit.py 2 && ...` must not proceed on a WAIT.
This script only reads; the supervisor records `waitingOn` and the next stage itself.

Run from the repo root. Standard library only.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline_common import fail, get_slot, load_config, load_state, paths_overlap  # noqa: E402

# Stages at which a slot has not yet passed discovery, and so is not compared against.
NOT_PAST_DISCOVERY = {"QUEUED", "DISCOVERY_STARTED", "DISCOVERY_COMPLETE"}


def footprint(issue_id):
    path = os.path.join(".issues", issue_id, "footprint.json")
    try:
        with open(path, encoding="utf-8") as fh:
            fp = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(fp, dict) or not isinstance(fp.get("paths", []), list):
        return None
    return fp


def main(argv):
    if len(argv) != 1:
        fail(2, "usage: admit.py <slot>")
    cfg = load_config()
    state = load_state()
    me = str(int(argv[0])) if argv[0].isdigit() else argv[0]
    mine = footprint(get_slot(state, me)["issue"])
    serialize = cfg["admission"].get("serializeMigrations", True)

    others = [
        (k, v) for k, v in sorted((state.get("slots") or {}).items())
        if k != me and v.get("stage") not in NOT_PAST_DISCOVERY
    ]
    for k, other in others:
        theirs = footprint(other["issue"])
        if mine is None or theirs is None:
            print(f"WAIT:{k}:nofootprint")
            sys.exit(3)
        if serialize and mine.get("migration") and theirs.get("migration"):
            print(f"WAIT:{k}:migration")
            sys.exit(3)
        for a in mine.get("paths", []):
            for b in theirs.get("paths", []):
                if paths_overlap(a, b):
                    print(f"WAIT:{k}:paths")
                    sys.exit(3)

    # No other slot past discovery: even a missing footprint may proceed alone.
    print("ADMIT")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
