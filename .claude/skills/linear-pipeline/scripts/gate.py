#!/usr/bin/env python3
"""gate.py <slot> <attempt> -- run the verify gate for one slot (SKILL.md §7.2, ADR-0014)

Runs every `verify` entry from .agent/config.json, in order, inside the slot's worktree, against the
slot's own resources, and stops at the first failure. Everything goes to
`<repo root>/.issues/<ID>/cycle-<attempt>/gate.log`; stdout carries one short line per entry, then
`GATE_PASS [known-flake:<names>]` or `GATE_FAIL <name>`.

Before the first entry, in this order:
  - refuse to start unless `gate` in .agent/state.json names this slot (the supervisor takes the
    mutex; this script never writes the state file)
  - build the environment: remove `gate.unsetEnv`, export `gate.perSlotEnv` with {root} and {slot}
    filled in, and, when `database` is a block, export the slot's URL under every name in
    `database.urlEnvNames` (default [database.baseUrlEnv])
  - when `database` is a block, ping the server (`slot_db.py ping`)
  - wait for the one-minute load average to drop below `gate.maxLoadAvg`, if set
  - run `gate.preCommands` (e.g. a dependency install)
  - run `database.siblingMigrateCommand` against each `database.siblingSuffixes` sibling

Known flakes (`verifyKnownFlakes`) are honoured only when `gate.flakeParser` names a parser. The one
shipped parser, "vitest", reads Vitest output, optionally prefixed by Turborepo's `<package>:<task>:`.
It is an EXAMPLE of runner-specific parsing: add a function to PARSERS for another runner.

Exit codes:
  0  every entry passed (possibly through a known-flake exemption)
  1  an entry failed; the supervisor records VERIFY_FAIL
  2  usage, config or state error (including: the gate mutex does not name this slot)
  4  the environment needs the operator: the database did not answer, or a pre-command failed

Run from the repo root, ideally as a background command (a full suite can outlast a foreground
timeout). Standard library only.
"""

import os
import re
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline_common import (  # noqa: E402
    PIPELINE_SCRIPTS, base_branch, fail, get_slot, glob_match, load_config, load_state, run,
)


# ---------------------------------------------------------------------------------------------
# Runner-specific output parsing for known flakes. Each parser takes the combined output of one
# failing verify entry and returns a Failures record, or None when it cannot tell.
# ---------------------------------------------------------------------------------------------

class Failures:
    def __init__(self, packages, files, unhandled, unhandled_unattributed):
        self.packages = packages            # packages the runner reported as failing (may be empty)
        self.files = files                  # failing test files
        self.unhandled = unhandled          # {(package or None, file)} unhandled errors attributed
        self.unhandled_unattributed = unhandled_unattributed  # errors no file was blamed for


def parse_vitest(out):
    """EXAMPLE parser: Vitest, optionally behind Turborepo's `<package>:<task>:` line prefix."""
    prefix = r"^(?:(\S+?):\S+:\s+)?"
    packages = {p for p in re.findall(prefix + r"\s*Test Files\s+\d+ failed", out, re.M) if p}
    files = set(re.findall(r"FAIL\s+(\S+\.(?:test|spec)\.[cm]?[jt]sx?)", out))
    unhandled = {(p or None, f) for p, f in re.findall(prefix + r'.*?This error originated in "([^"]+)"', out, re.M)}
    reported = sum(int(x) for x in re.findall(r"Errors\s+(\d+) errors?", out))
    attributed = len(re.findall(r"This error originated in", out))
    return Failures(packages, files, unhandled, max(0, reported - attributed))


PARSERS = {"vitest": parse_vitest}
DEFAULT_RERUN = {"vitest": "npx vitest run {file}"}


class Gate:
    def __init__(self, n, attempt):
        self.n, self.attempt = n, attempt
        self.cfg = load_config()
        self.base = base_branch(self.cfg)
        self.root = os.getcwd()
        state = load_state()
        held = state.get("gate") or {}
        if str(held.get("slot")) != n:
            fail(2, f"the gate mutex names slot {held.get('slot')!r}, not {n}; take it first")
        slot = get_slot(state, n)
        self.issue = slot["issue"]
        if not slot.get("worktree"):
            fail(2, f"slot {n} has no worktree")
        self.tree = os.path.join(self.root, slot["worktree"])
        if not os.path.isdir(self.tree):
            fail(2, f"worktree {slot['worktree']} does not exist")
        self.log_path = os.path.join(self.root, ".issues", self.issue, f"cycle-{attempt}", "gate.log")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.tail = int(self.cfg["gate"].get("logTailChars") or 20000)
        self.env = self.build_env()
        self.used_flakes = []

    # -- logging -----------------------------------------------------------------------------

    def log(self, text):
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")

    # -- environment -------------------------------------------------------------------------

    def build_env(self):
        g = self.cfg["gate"]
        env = dict(os.environ)
        for name in g.get("unsetEnv") or []:
            env.pop(name, None)
        for name, value in (g.get("perSlotEnv") or {}).items():
            value = str(value).replace("{root}", self.root).replace("{slot}", self.n)
            env[name] = value
            if os.path.isabs(value) and name.endswith(("_DIR", "_DIRECTORY")):
                os.makedirs(value, exist_ok=True)
        self.db_url = None
        db = self.cfg.get("database")
        if isinstance(db, dict):
            r = run([sys.executable, os.path.join(PIPELINE_SCRIPTS, "slot_db.py"), "url", self.n])
            if r.returncode:
                fail(2, "slot_db.py url failed: " + r.stderr.strip())
            self.db_url = r.stdout.strip()
            self.url_names = db.get("urlEnvNames") or [db.get("baseUrlEnv") or "DB_URL"]
            for name in self.url_names:
                env[name] = self.db_url
        return env

    def with_db(self, url):
        env = dict(self.env)
        for name in self.url_names:
            env[name] = url
        return env

    # -- steps -------------------------------------------------------------------------------

    def shell(self, command, env=None, cwd=None):
        return run(command, cwd=cwd or self.tree, env=env or self.env, shell=True)

    def ping_db(self):
        if self.db_url is None:
            return
        r = run([sys.executable, os.path.join(PIPELINE_SCRIPTS, "slot_db.py"), "ping", self.n])
        if r.returncode:
            self.log("ENV database did not answer: " + r.stderr.strip())
            print(f"GATE_ENV database: run `slot_db.py ping {self.n}` until it passes")
            sys.exit(4)

    def wait_for_load(self):
        limit = self.cfg["gate"].get("maxLoadAvg")
        if not limit or not hasattr(os, "getloadavg"):
            return
        deadline = time.time() + int(self.cfg["gate"].get("loadWaitSeconds") or 600)
        while os.getloadavg()[0] >= float(limit):
            if time.time() > deadline:
                self.log(f"LOAD still {os.getloadavg()[0]:.1f} >= {limit} after waiting; running anyway")
                return
            time.sleep(15)

    def pre_commands(self):
        for command in self.cfg["gate"].get("preCommands") or []:
            r = self.shell(command)
            self.log(f"=== pre: {command} rc={r.returncode}")
            if r.returncode:
                self.log((r.stdout + r.stderr)[-self.tail:])
                print(f"GATE_ENV pre-command failed: {command}")
                sys.exit(4)

    def migrate_siblings(self):
        db = self.cfg.get("database")
        if not isinstance(db, dict) or not db.get("siblingMigrateCommand"):
            return
        for suffix in db.get("siblingSuffixes") or []:
            r = self.shell(db["siblingMigrateCommand"], env=self.with_db(self.db_url + suffix))
            self.log(f"=== migrate sibling {suffix} rc={r.returncode}")
            if r.returncode:
                self.log((r.stdout + r.stderr)[-self.tail:])
                print(f"FAIL migrate{suffix}")
                print(f"GATE_FAIL migrate{suffix}")
                sys.exit(1)

    # -- known flakes ------------------------------------------------------------------------

    def touched(self):
        r = run(["git", "diff", "--name-only", f"origin/{self.base}...HEAD"], cwd=self.tree)
        return [x for x in r.stdout.split("\n") if x]

    def applicable_flakes(self, step):
        out = []
        for f in self.cfg.get("verifyKnownFlakes") or []:
            if f.get("step") != step:
                continue
            exempt = f.get("exemptIfBranchTouches") or []
            if exempt and any(glob_match(p, g) for p in self.touched() for g in exempt):
                continue
            out.append(f)
        return out

    def known_flakes_only(self, step, output):
        """Return the flake entries that account for every failure in `output`, or None."""
        parser = PARSERS.get(self.cfg["gate"].get("flakeParser") or "none")
        flakes = self.applicable_flakes(step)
        if not parser or not flakes:
            return None
        found = parser(output)
        if not (found.files or found.unhandled) or found.unhandled_unattributed:
            return None
        test_flakes = [f for f in flakes if f.get("kind", "testFailure") == "testFailure"]
        error_flakes = [f for f in flakes if f.get("kind") == "unhandledError"]
        if found.packages and not found.packages <= {f["package"] for f in test_flakes}:
            return None
        if not found.files <= {f["file"] for f in test_flakes}:
            return None
        for pkg, file in found.unhandled:
            if not any(f["file"] == file and (pkg is None or f["package"] == pkg) for f in error_flakes):
                return None
        hits = [f for f in test_flakes if f["file"] in found.files]
        hits += [f for f in error_flakes if any(f["file"] == file for _, file in found.unhandled)]
        return hits

    def rerun_in_isolation(self, flakes):
        parser = self.cfg["gate"].get("flakeParser")
        for f in flakes:
            template = f.get("rerunCommand") or DEFAULT_RERUN.get(parser)
            if not template:
                return False
            command = template.replace("{file}", shlex.quote(f["file"]))
            r = self.shell(command, cwd=os.path.join(self.tree, f.get("packageDir") or "."))
            self.log(f"--- isolated rerun {f['file']} rc={r.returncode}\n" + (r.stdout + r.stderr)[-1500:])
            if r.returncode:
                return False
        return True

    # -- the gate ----------------------------------------------------------------------------

    def run(self):
        if not self.cfg.get("verify"):
            fail(2, "verify is empty; refusing to report a pass for a gate that ran nothing")
        with open(self.log_path, "w", encoding="utf-8") as fh:
            fh.write(f"gate slot {self.n} {self.issue} attempt {self.attempt} "
                     f"db {self.db_url.rsplit('/', 1)[-1] if self.db_url else 'none'}\n")
        self.ping_db()
        self.wait_for_load()
        self.pre_commands()
        self.migrate_siblings()
        for entry in self.cfg.get("verify") or []:
            name, command = entry["name"], entry["command"]
            r = self.shell(command)
            output = r.stdout + r.stderr
            self.log(f"=== {name} rc={r.returncode}")
            if r.returncode:
                flakes = self.known_flakes_only(name, output)
                if flakes is not None:
                    ok = self.rerun_in_isolation(flakes)
                    self.log(output[-self.tail:])
                    self.log(f"=== {name} KNOWN_FLAKE_ONLY isolated-rerun={'pass' if ok else 'fail'}")
                    if ok:
                        self.used_flakes.append(name)
                        print(f"PASS {name} (known flake: {', '.join(f['file'] for f in flakes)} re-run in isolation)")
                        continue
                self.log(output[-self.tail:])
                print(f"FAIL {name}")
                print(f"GATE_FAIL {name}")
                sys.exit(1)
            print(f"PASS {name}")
        print("GATE_PASS" + (" known-flake:" + ",".join(self.used_flakes) if self.used_flakes else ""))


def main(argv):
    if len(argv) != 2 or not argv[0].isdigit() or not argv[1].isdigit():
        fail(2, "usage: gate.py <slot> <attempt>")
    Gate(str(int(argv[0])), int(argv[1])).run()


if __name__ == "__main__":
    main(sys.argv[1:])
