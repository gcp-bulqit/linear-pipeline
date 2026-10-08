#!/usr/bin/env python3
"""ship.py push|pr <slot> -- the supervisor's two outward git steps, one transition each (SKILL.md §7.1)

  ship.py push <slot>   DOCUMENTATION_COMPLETE -> PUSHED
      Runs the pre-push guards, then `git push -u origin <branch>` from the worktree.
  ship.py pr <slot>     PUSHED -> PR_OPEN
      Finds the pull request for the branch, or opens a draft one against `git.baseBranch` with the
      title and body the documentation agent wrote, and records its url on the slot.

Pre-push guards (each refusal names its reason):
  - the worktree is clean, and has no `.issues/` directory inside it (an agent resolved an artifact
    path relative to the worktree)
  - `.issues/<ID>/pr-title.txt` and `pr-body.md` exist, and the title fills `pr.titleFormat`
  - the branch has at least one commit ahead of `origin/<git.baseBranch>`
  - git.attribution == "none": no commit message, title or body contains a `git.attributionMarkers`
    string (case-insensitive)
  - git.requireSigned: every commit ahead of the base carries a good signature (%G? of G or U)
It also prints `WARN stray <path>` for each file the branch changed that is modified or untracked
in the main checkout too: the trace of an agent that wrote through the wrong root. That is a
warning, not a refusal, because the operator may be editing the same file deliberately.

Exit codes: 0 ok | 1 git or gh failed | 2 usage, config or state error | 3 a guard refused |
            5 unsigned commits under requireSigned (an operator step: unlock the key, re-sign)

Each subcommand writes its one stage to .agent/state.json atomically and prints one line.
Run from the repo root. Needs git and an authenticated gh. Standard library only.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline_common import (  # noqa: E402
    base_branch, fail, get_slot, load_config, load_state, require_stage, run, save_state,
)


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        fail(3, f"{path} is missing; re-run the documentation stage")


def title_pattern(fmt, issue):
    pattern = re.escape(fmt)
    pattern = pattern.replace(re.escape("{id}"), re.escape(issue))
    pattern = pattern.replace(re.escape("{summary}"), r"\S.*")
    return re.compile("^" + pattern + "$")


def guards(cfg, slot, base):
    issue, tree = slot["issue"], slot.get("worktree")
    if not tree or not slot.get("branch") or not os.path.isdir(tree):
        fail(2, f"slot {slot.get('slot')} has no branch or worktree on disk")
    title = read(os.path.join(".issues", issue, "pr-title.txt")).strip()
    body = read(os.path.join(".issues", issue, "pr-body.md"))

    fmt = cfg["pr"].get("titleFormat") or "{summary}"
    if "\n" in title or not title_pattern(fmt, issue).match(title):
        fail(3, f"pr-title.txt does not fill pr.titleFormat {fmt!r}: {title[:80]!r}")

    status = run(["git", "-C", tree, "status", "--porcelain"]).stdout.strip()
    if status:
        fail(3, "worktree is not clean: " + status.replace("\n", "; ")[:200])
    if os.path.isdir(os.path.join(tree, ".issues")):
        fail(3, f"stray .issues/ inside {tree}: move its files to the repo root's .issues/ and delete it")

    span = f"origin/{base}..HEAD"
    run(["git", "-C", tree, "fetch", "-q", "origin", base])
    shas = run(["git", "-C", tree, "rev-list", span]).stdout.split()
    if not shas:
        fail(3, f"the branch has no commits ahead of origin/{base}")

    if (cfg["git"].get("attribution") or "none") == "none":
        messages = run(["git", "-C", tree, "log", "--format=%B", span]).stdout
        haystack = "\n".join([title, body, messages]).lower()
        found = [m for m in cfg["git"].get("attributionMarkers") or [] if m.lower() in haystack]
        if found:
            fail(3, f"attribution marker(s) {found} in the commits, title or body; git.attribution is \"none\"")

    if cfg["git"].get("requireSigned"):
        sigs = run(["git", "-C", tree, "log", "--format=%G?", span]).stdout.split()
        if any(s not in ("G", "U") for s in sigs):
            fail(5, f"unsigned or badly signed commits on the branch ({sorted(set(sigs))}); "
                    "git.requireSigned is true")

    changed = set(run(["git", "-C", tree, "diff", "--name-only", f"origin/{base}...HEAD"]).stdout.split("\n"))
    dirty = set()
    for line in run(["git", "status", "--porcelain", "--untracked-files=all"]).stdout.split("\n"):
        if len(line) > 3:
            dirty.add(line[3:].split(" -> ")[-1].strip('"'))
    for path in sorted((changed & dirty) - {""}):
        print(f"WARN stray {path}")
    return title


def cmd_push(cfg, n):
    base = base_branch(cfg)
    state = load_state()
    slot = get_slot(state, n)
    require_stage(slot, "DOCUMENTATION_COMPLETE")
    guards(cfg, slot, base)
    r = run(["git", "-C", slot["worktree"], "push", "-u", "origin", slot["branch"]])
    if r.returncode:
        fail(1, "push failed: " + r.stderr.strip()[-300:])
    state = load_state()
    get_slot(state, n)["stage"] = "PUSHED"
    save_state(state)
    print(f"PUSHED {slot['issue']} {slot['branch']}")


def cmd_pr(cfg, n):
    base = base_branch(cfg)
    state = load_state()
    slot = get_slot(state, n)
    require_stage(slot, "PUSHED")
    issue, branch = slot["issue"], slot["branch"]
    if (cfg["git"].get("prMode") or "draft") != "draft":
        fail(2, "git.prMode must be \"draft\"")

    # Check first: a kill between the push and this step must never produce a second pull request.
    r = run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url", "--jq", ".[0].url"])
    url = r.stdout.strip() if r.returncode == 0 else ""
    if not url:
        title = read(os.path.join(".issues", issue, "pr-title.txt")).strip()
        r = run(["gh", "pr", "create", "--draft", "--base", base, "--head", branch,
                 "--title", title, "--body-file", os.path.join(".issues", issue, "pr-body.md")])
        if r.returncode:
            fail(1, "gh pr create failed: " + r.stderr.strip()[-300:])
        lines = [x for x in r.stdout.split() if x.startswith("https://")]
        url = lines[-1] if lines else ""
    if not url.startswith("https://"):
        fail(1, "could not determine the pull request url")

    state = load_state()
    slot = get_slot(state, n)
    slot["stage"] = "PR_OPEN"
    slot["pr"] = url
    save_state(state)
    print(f"PR_OPEN {issue} {url}")


def main(argv):
    if len(argv) != 2 or argv[0] not in ("push", "pr") or not argv[1].isdigit():
        fail(2, "usage: ship.py push|pr <slot>")
    cfg = load_config()
    n = str(int(argv[1]))
    {"push": cmd_push, "pr": cmd_pr}[argv[0]](cfg, n)


if __name__ == "__main__":
    main(sys.argv[1:])
