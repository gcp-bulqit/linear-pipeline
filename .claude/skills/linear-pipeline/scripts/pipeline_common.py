"""Shared helpers for the linear-pipeline scripts. Not a command; imported by the others.

Every script runs from the target repository's root, reads `.agent/config.json` through
`load_config()` (so the documented defaults live in exactly one place), and writes
`.agent/state.json` through `save_state()` (temp file, then rename, so a kill mid-write never
leaves a truncated file).

Standard library only. Python 3.8 or later.
"""

import copy
import json
import os
import re
import subprocess
import sys

CONFIG_PATH = os.path.join(".agent", "config.json")
STATE_PATH = os.path.join(".agent", "state.json")

# The defaults documented in config.md. A field absent from .agent/config.json takes these values.
DEFAULTS = {
    "linear": {
        "ingestState": "Todo",
        "ingestLabel": None,
        "reviewState": None,
        "unparkIgnorePatterns": [],
    },
    "verifyKnownFlakes": [],
    "gate": {
        "preCommands": [],
        "perSlotEnv": {},
        "unsetEnv": [],
        "maxLoadAvg": None,
        "loadWaitSeconds": 600,
        "flakeParser": "none",
        "logTailChars": 20000,
    },
    "git": {
        "baseBranch": None,  # detected at setup; required by the scripts that need it
        "branchPrefix": "agent",
        "worktreeDir": ".claude/worktrees",
        "prMode": "draft",
        "attribution": "none",
        "attributionMarkers": ["Co-Authored-By", "Generated with", "Claude Code"],
        "requireSigned": False,
    },
    "pr": {
        "titleFormat": "{summary}",
        "templatePath": ".github/pull_request_template.md",
    },
    "docs": {"root": "docs/"},
    "limits": {
        "maxCycles": 3,
        "maxRediscovery": 1,
        "workerStepRetries": 2,
        "maxConcurrent": 1,
    },
    "admission": {"serializeMigrations": True},
    "clock": {"minSeconds": 1200, "maxSeconds": 1800},
    "lock": {"staleAfterMinutes": 30},
}

PIPELINE_SCRIPTS = os.path.dirname(os.path.abspath(__file__))


def fail(code, message, prog=None):
    """Print one line to stderr and exit with `code`."""
    name = prog or os.path.basename(sys.argv[0])
    print(f"{name}: {message}", file=sys.stderr)
    sys.exit(code)


def _merge(base, override):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config():
    """Return .agent/config.json merged over DEFAULTS. Exit 2 if the file is missing or invalid."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        fail(2, f"{CONFIG_PATH} not found; run from the repo root, after setup mode")
    except json.JSONDecodeError as e:
        fail(2, f"{CONFIG_PATH} is not valid JSON ({e.msg} at line {e.lineno})")
    return _merge(DEFAULTS, raw)


def base_branch(cfg):
    base = cfg["git"].get("baseBranch")
    if not base:
        fail(2, "git.baseBranch is not set in .agent/config.json")
    return base


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        fail(2, f"{STATE_PATH} not found")


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, STATE_PATH)


def get_slot(state, n):
    if not str(n).isdigit() or int(n) < 1:
        fail(2, f"slot must be a positive integer, got {n!r}")
    slot = (state.get("slots") or {}).get(str(int(n)))
    if not slot:
        fail(2, f"slot {n} is empty")
    return slot


def require_stage(slot, *stages):
    if slot.get("stage") not in stages:
        fail(2, f"slot {slot.get('slot')} is at {slot.get('stage')}, expected {' or '.join(stages)}")


def run(args, cwd=None, env=None, shell=False):
    """Run a command, capturing output as text. Never raises on a non-zero exit."""
    return subprocess.run(args, cwd=cwd, env=env, shell=shell, capture_output=True, text=True)


def slug(title, limit=50):
    """Lowercase, non-alphanumerics collapsed to single hyphens, trimmed, cut on a hyphen boundary."""
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    if len(s) > limit:
        s = s[: limit + 1].rsplit("-", 1)[0]
    return s or "issue"


def issue_title(issue_id):
    """Read the title from the cached ticket that fetch_issue.py wrote (`# ID — title`)."""
    path = os.path.join(".issues", issue_id, "issue.md")
    try:
        with open(path, encoding="utf-8") as fh:
            first = fh.readline().strip()
    except FileNotFoundError:
        fail(2, f"{path} not found; cache the ticket with fetch_issue.py first")
    m = re.match(r"^#\s+\S+\s+[—-]\s+(.*)$", first)
    if not m:
        fail(2, f"{path} does not start with a '# ID — title' line")
    return m.group(1)


# ---------------------------------------------------------------------------------------------
# Footprint globs.
#
# Dialect (documented in config.md and SKILL.md §3.3):
#   *    any run of characters within one path segment
#   ?    one character within one path segment
#   **   any run of characters, crossing segments (so `db/**` is everything under db/)
#   a path with no wildcard names that file, or that directory and everything under it
# ---------------------------------------------------------------------------------------------

_WILD = re.compile(r"[*?\[]")


def has_wildcard(pattern):
    return bool(_WILD.search(pattern))


def glob_to_regex(pattern):
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")  # zero or more whole segments
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def _norm(p):
    p = p.strip()
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def glob_match(path, pattern):
    """True if `path` (a file) is covered by `pattern` in the footprint dialect."""
    path, pattern = _norm(path), _norm(pattern)
    if not has_wildcard(pattern):
        return path == pattern or path.startswith(pattern + "/")
    if glob_to_regex(pattern).match(path):
        return True
    # `dir/**` also covers `dir` itself.
    return pattern.endswith("/**") and path == pattern[:-3]


def _static_prefix(pattern):
    parts = []
    for seg in _norm(pattern).split("/"):
        if has_wildcard(seg):
            break
        parts.append(seg)
    return parts


def paths_overlap(a, b):
    """Conservative overlap test between two footprint entries.

    Exact when either side has no wildcard. When both are globs, they overlap if one's static prefix
    (the segments before the first wildcard) is a prefix of the other's. That can report an overlap
    two globs do not really share; a false overlap only delays an issue, a missed one lets two
    branches edit one file.
    """
    a, b = _norm(a), _norm(b)
    if not has_wildcard(a) and not has_wildcard(b):
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")
    if not has_wildcard(a):
        a, b = b, a  # now `a` is a glob
    if not has_wildcard(b):
        # glob vs literal: the literal file is covered, or the literal names a directory the glob
        # reaches into.
        if glob_match(b, a):
            return True
        pa = _static_prefix(a)
        lb = b.split("/")
        return pa[: len(lb)] == lb
    pa, pb = _static_prefix(a), _static_prefix(b)
    n = min(len(pa), len(pb))
    return pa[:n] == pb[:n]
