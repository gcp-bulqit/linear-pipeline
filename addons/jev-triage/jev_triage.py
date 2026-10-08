#!/usr/bin/env python3
"""Classify Linear issues by whether a pull request alone can resolve them, using TypeSafe's Jev.

OPTIONAL ADD-ON. The linear-pipeline does not need it. It calls a third-party, paid API and sends
ticket text there; read README.md in this directory first.

Fetches issues (title, description, labels, project, comments) for one assignee in the given
workflow states, asks Jev a set of typed questions per issue, and decides in code which issues are
"pure PR" work. Ticket text goes from Linear to TypeSafe and to the output files; it is never printed.

Usage (from the target repo's root):
  jev_triage.py --repository repository.json [--assignee "Pipeline Bot"] [--states Todo,Backlog]
                [--base main] [--pathspec src] [--out .agent/jev-triage] [--workers 8]
  jev_triage.py --repository repository.json --ids ENG-1,ENG-2
                                             classify named issues regardless of assignee or state
  jev_triage.py --repository repository.json --eval labels.json [--no-evidence]
                                             score the classifier on labelled issues (see `run_eval`)
  jev_triage.py --rebucket [--emit-triage]   re-apply bucket() to results.json without calling Jev

Defaults come from .agent/config.json when it exists: --assignee from linear.user, --base from
git.baseBranch, --ignore-comment from linear.unparkIgnorePatterns. Arguments override them.

--repository names a JSON file describing what a pull request to this repository can and cannot
change: {"name": ..., "contains": [...], "does_not_contain": [...]}. See repository.example.json.
It is sent to TypeSafe with every issue, so describe the repository, not your business.

--emit-triage merges the buckets into .agent/triage.json in the schema the pipeline's
linear.codeChangesOnly reads (pure_pr -> CODE; not_pr, already_resolved -> NOT_CODE; the rest ->
AMBIGUOUS), never overwriting a row that is already there.

Each issue's state carries `code_evidence`, computed in code from this repository: pull requests and
commits that name the issue, and whether the files and symbols the ticket mentions exist on the base
branch. --no-evidence drops it and the questions that read it, which reproduces version 1.

Needs LINEAR_API_KEY and TYPESAFE_API_KEY in the environment, git, and an authenticated gh for the
pull request evidence. Python 3.8 or later, standard library only.

Outputs, in --out:
  results.json   raw Jev answers plus the code-derived bucket, per issue
  report.md      one table row per issue (id, state, title, bucket, path, flags, size)

The bucket policy lives in `bucket()` and reads only stored answers. Re-run with --rebucket to apply
a changed policy to results.json without calling Jev again.
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import subprocess
from functools import lru_cache

LINEAR_URL = "https://api.linear.app/graphql"
TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

DESC_LIMIT = 3500
COMMENT_LIMIT = 600
MAX_COMMENTS = 8
BASE = "origin/main"         # set from --base / git.baseBranch in main()
PATHSPEC = []                # set from --pathspec in main(); empty means the whole repository
PR_LIMIT = 1000              # set from --pr-limit in main()
MAX_REFS = 10

PATH_RE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:tsx?|jsx?|mjs|cjs|sql|md|json|ya?ml|py))\b")
TICK_RE = re.compile(r"`([^`\n]{3,80})`")
# Bundler output and stack-trace frames pasted into tickets are not source files. The defaults lean
# towards JavaScript bundlers (Next.js output, chunks, node_modules); extend them for your stack.
BUILD_ARTIFACT_RE = re.compile(r"(^|/)(__|\.next/|next/server|chunks/|node_modules/)|\._\.|^[\w-]{1,3}\.\w+$")
SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{3,}$")

# Comments that integrations write under a person's account (a feedback tool syncing a status, say)
# carry no information about the work. Set from --ignore-comment in main().
IGNORE_COMMENTS = []
# Some intake tools append session metadata or logs after the report itself; everything from the
# first match of one of these is dropped from the description. Set from --cut-description in main().
CUT_DESCRIPTION = []

# Loaded from --repository in main(). Describes what a pull request here can and cannot change.
REPOSITORY = None

PURE_PR_DEFINITION = (
    "A ticket is resolved purely by a pull request when merging changes to `repository` and "
    "deploying them is all that is needed. Deploying includes migrations that run on deploy and a "
    "routine redeploy of the workers. It is NOT purely a pull request if any person must also do "
    "something outside `repository`: change a third-party dashboard setting, set an environment "
    "variable, correct production data by hand, edit content managed outside the repository (CMS "
    "pages, copy stored in a database), or act on an external account."
)

QUESTIONS = {
    "path": {
        "type": "choice",
        "instructions": {
            "repository": "`repository` describes what can and cannot be changed by a pull request.",
            "definition": PURE_PR_DEFINITION,
            "question": "Read `issue` (its title, description and comments). What does resolving this ticket, as it currently stands, require?",
        },
        "criteria": {
            "pr_only": "Only code, schema, test or documentation changes in `repository`. Nothing must be done outside it, and nothing is waiting on a decision.",
            "pr_plus_ops": "Changes in `repository` AND at least one manual step outside it, such as a dashboard setting, an environment variable, a manual data fix, or an edit to content managed outside the repository.",
            "ops_only": "No change to `repository`. It is resolved entirely outside it: a dashboard or account setting, a data correction, a content edit, or a business task.",
            "decision_first": "A product, business or design decision must be made before anyone can say what to build. The ticket asks for something whose requirements are still open.",
            "question_or_info": "A question, notice, FYI, discussion, research or investigation request whose outcome is an answer or a report, not a change.",
            "already_resolved": "The comments show it was already fixed, shipped, declined, or is a duplicate of another ticket.",
        },
    },
    "needs_repo_change": {
        "type": "noul",
        "instructions": "Does resolving `issue` require changing code, database schema, tests or documentation inside `repository`?",
        "criteria": {
            "true": "At least one change inside `repository` is required.",
            "false": "Nothing inside `repository` needs to change.",
        },
    },
    "needs_outside_step": {
        "type": "noul",
        "instructions": {
            "repository": "`repository` lists what is outside the repository under `does_not_contain`.",
            "question": "Does resolving `issue` require a person to do at least one thing outside `repository`, such as changing a third-party dashboard setting, setting an environment variable, correcting production data by hand, editing content managed outside the repository, or acting on an external account?",
        },
        "criteria": {
            "true": "At least one manual step outside `repository` is required. A routine deploy of merged code does not count.",
            "false": "Merging and deploying code is enough; no manual step outside `repository` is required.",
        },
    },
    "needs_decision": {
        "type": "noul",
        "instructions": "Does `issue` leave open a product, business or design question that must be answered before implementation can start? Ordinary implementation details an engineer would decide do not count.",
        "criteria": {
            "true": "An open product, business or design question blocks implementation.",
            "false": "What to build is clear enough to start; any remaining choices are engineering details.",
        },
    },
    "needs_prod_investigation": {
        "type": "noul",
        "instructions": "Before the fix for `issue` can be designed, must someone inspect production data, logs, or a recorded user session to find out what actually happened?",
        "criteria": {
            "true": "The cause cannot be known from the ticket and the code alone; production evidence is needed first.",
            "false": "The ticket and the code are enough to design the change.",
        },
    },
    "already_resolved": {
        "type": "noul",
        "instructions": "Do the comments on `issue` say it is already fixed, shipped, declined, closed, or a duplicate of another ticket?",
        "criteria": {
            "true": "A comment says it is fixed, shipped, declined, closed or a duplicate.",
            "false": "No comment says that.",
        },
    },
    "evidence_shows_done": {
        "type": "noul",
        "evidence": True,
        "instructions": {
            "how_to_read": "`code_evidence` was computed from `repository` by code. `pull_requests` and `commits` name this ticket's id; `referenced_files` and `referenced_symbols` say whether names the ticket mentions exist on the base branch.",
            "question": "Does `code_evidence` show that the change `issue` asks for has already been delivered, through a merged pull request or a commit on the base branch that names this ticket?",
        },
        "criteria": {
            "true": "A merged pull request or a base-branch commit names this ticket and appears to deliver what it asks.",
            "false": "No merged pull request or commit names this ticket, or the ones that do are unmerged, closed without merging, or only partial.",
        },
    },
    "requested_thing_exists": {
        "type": "noul",
        "evidence": True,
        "instructions": {
            "how_to_read": "`code_evidence.referenced_files` and `code_evidence.referenced_symbols` list names from the ticket and whether they exist in `repository` today.",
            "question": "`issue` asks to add, create or build something new. Do the existing files or symbols in `code_evidence` show that the thing it asks for already exists in `repository`, possibly delivered under a different ticket? If `issue` is a bug report about behaviour of existing code, or asks to change existing code rather than add something, answer no.",
        },
        "criteria": {
            "true": "The ticket requests something new, and an existing file or symbol with that purpose is already in `repository`.",
            "false": "The ticket is a bug report or a change to existing code, or nothing in `code_evidence` shows the requested thing already exists.",
        },
    },
    "fix_location_known": {
        "type": "noul",
        "evidence": True,
        "instructions": "Using `issue` and `code_evidence.referenced_files` and `code_evidence.referenced_symbols`, is it known where in `repository` the change would be made? A file or symbol the ticket names that exists counts; a name that does not exist does not.",
        "criteria": {
            "true": "The ticket points at files or symbols that exist, or names a specific screen or flow precisely enough to find.",
            "false": "Nothing in the ticket locates the change, or the names it gives do not exist in `repository`.",
        },
    },
    "size": {
        "type": "score",
        "instructions": "If `issue` were implemented in `repository`, how large would the change be?",
        "criteria": [
            "Tiny: a copy, label or one-line change",
            "Small: a contained change to a few files in one area",
            "Medium: a feature or fix spanning one area, with tests",
            "Large: several areas, or schema plus UI plus background work",
            "Epic: too big for one pull request; it should be split into several tickets",
        ],
    },
}


def bucket(a, ev=None):
    """Code-owned policy. `a` is one issue's answers. Thresholds are starting points, not truths."""
    ev = ev or {}
    p = a["path"]["probabilities"]
    choice = a["path"]["choice"]
    outside = a["needs_outside_step"]["noul"]
    decision = a["needs_decision"]["noul"]
    resolved = a["already_resolved"]["noul"]
    repo = a["needs_repo_change"]["noul"]
    prod = a["needs_prod_investigation"]["noul"]
    done = a.get("evidence_shows_done", {}).get("noul", 0.0)
    size = a["size"]["score"]
    if resolved >= 0.6 or choice == "already_resolved":
        return "already_resolved"
    # Code evidence outranks the ticket text: a merged PR naming the ticket is a fact, not a reading.
    if done >= 0.6 and ev.get("merged_pr_count", 0) > 0:
        return "already_resolved"
    # Pure PR: the path answer and every independent flag agree, and nothing has to be looked up in
    # production first.
    if (
        choice == "pr_only"
        and p["pr_only"] >= 0.6
        and repo >= 0.6
        and outside < 0.35
        and decision < 0.35
        and prod < 0.5
        and size < 3.0
        and done < 0.4
        and a.get("requested_thing_exists", {}).get("noul", 0.0) < 0.5
    ):
        return "pure_pr"
    if p["pr_only"] >= 0.3 and repo >= 0.5 and outside < 0.5 and decision < 0.5:
        return "likely_pr_review"
    # Otherwise the path answer leads, and the flags only break ties.
    if choice in ("ops_only", "question_or_info"):
        return "not_pr"
    if choice == "decision_first" or decision >= 0.5:
        return "needs_decision"
    if choice == "pr_plus_ops" or (repo >= 0.5 and outside >= 0.5):
        return "pr_plus_ops"
    return "not_pr"


def post(url, body, headers, retries=6):
    data = json.dumps(body).encode()
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            # Never echo the response body: an error page can carry request context.
            raise RuntimeError(f"{url} HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise


def linear(query, variables):
    out = post(LINEAR_URL, {"query": query, "variables": variables}, {"Authorization": os.environ["LINEAR_API_KEY"]})
    if out.get("errors"):
        raise RuntimeError(f"Linear error: {out['errors']}")
    return out["data"]


ISSUES_QUERY = """
query($f: IssueFilter, $after: String) {
  issues(filter: $f, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      identifier title description priority updatedAt startedAt
      state { name } project { name } labels { nodes { name } }
      comments(first: 100) { nodes { createdAt body user { name } } }
    }
  }
}
"""


def fetch_issues(assignee, states):
    users = linear("query($n:String!){users(filter:{name:{eq:$n}}){nodes{id name}}}", {"n": assignee})["users"]["nodes"]
    if len(users) != 1:
        sys.exit(f"jev_triage: expected one Linear user named {assignee!r}, found {len(users)}")
    f = {"assignee": {"id": {"eq": users[0]["id"]}}, "state": {"name": {"in": states}}}
    issues, after = [], None
    while True:
        page = linear(ISSUES_QUERY, {"f": f, "after": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return issues
        after = page["pageInfo"]["endCursor"]


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


@lru_cache(maxsize=1)
def tree_files():
    return git("ls-tree", "-r", "--name-only", BASE).splitlines()


@lru_cache(maxsize=1)
def pr_index():
    r = subprocess.run(
        ["gh", "pr", "list", "--state", "all", "--limit", str(PR_LIMIT), "--json", "number,title,state,headRefName,mergedAt"],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout) if r.returncode == 0 else []


def refs_in(text):
    """Paths and code symbols the ticket text names, found by pattern, not by the model."""
    paths, symbols = [], []
    for m in PATH_RE.finditer(text):
        p = m.group(1).strip("./")
        if p not in paths and not p.startswith("http") and not BUILD_ARTIFACT_RE.search(p):
            paths.append(p)
    for m in TICK_RE.finditer(text):
        tok = m.group(1).strip()
        if SYMBOL_RE.match(tok) and tok not in symbols:
            symbols.append(tok)
    return paths[:MAX_REFS], symbols[:MAX_REFS]


def code_evidence(issue, comments, use_issue_links=True):
    ident = issue["identifier"]
    text = " ".join([issue["title"], issue.get("description") or "", *[c["body"] or "" for c in comments]])
    paths, symbols = refs_in(text)
    files = tree_files()
    ref_files = []
    for p in paths:
        hits = [f for f in files if f == p or f.endswith("/" + p)]
        ref_files.append({"name": p, "exists": bool(hits), "matches": hits[:3]})
    ref_syms = []
    for s in symbols:
        found = git("grep", "-l", "-w", "-I", s, BASE, "--", *PATHSPEC).splitlines()
        ref_syms.append({"name": s, "found_in_files": len(found), "examples": [f.split(":", 1)[-1] for f in found[:3]]})
    ev = {"referenced_files": ref_files, "referenced_symbols": ref_syms}
    if use_issue_links:
        key = ident.lower()
        prs = [
            {"number": p["number"], "title": p["title"], "state": p["state"], "merged": bool(p["mergedAt"])}
            for p in pr_index()
            if ident in p["title"] or key in p["headRefName"].lower()
        ]
        commits = [l for l in git("log", BASE, "--oneline", "-i", f"--grep={ident}\\b", "-n", "5").splitlines()]
        ev.update({
            "pull_requests": prs[:6],
            "merged_pr_count": sum(p["merged"] for p in prs),
            "commits": commits,
        })
    return ev


def fetch_by_ids(ids):
    nums = [int(i.split("-")[1]) for i in ids]
    team = ids[0].split("-")[0]
    f = {"number": {"in": nums}, "team": {"key": {"eq": team}}}
    issues, after = [], None
    while True:
        page = linear(ISSUES_QUERY, {"f": f, "after": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return issues
        after = page["pageInfo"]["endCursor"]


def clean_description(text):
    text = text or ""
    for pattern in CUT_DESCRIPTION:
        m = pattern.search(text)
        if m:
            text = text[: m.start()]
    text = text.strip()
    return text[:DESC_LIMIT] + (" [truncated]" if len(text) > DESC_LIMIT else "")


def visible_comments(issue, before=None):
    return [
        c for c in sorted(issue["comments"]["nodes"], key=lambda c: c["createdAt"])
        if c["body"] and not any(p.search(c["body"]) for p in IGNORE_COMMENTS)
        and (before is None or c["createdAt"] < before)
    ]


INCLUDE_AUTHORS = False  # set from --include-comment-authors in main()


def author(c, names):
    """Comment authors are pseudonymous by default: 'person 1', 'person 2', ... per issue."""
    name = (c["user"] or {}).get("name", "unknown")
    if INCLUDE_AUTHORS:
        return name
    return names.setdefault(name, f"person {len(names) + 1}")


def build_state(issue, comments, evidence):
    truncated = len(comments) > MAX_COMMENTS
    comments = comments[-MAX_COMMENTS:]
    names = {}
    state = {
        "repository": REPOSITORY,
        "issue": {
            "title": issue["title"],
            "workflow_state": issue["state"]["name"],
            "project": (issue.get("project") or {}).get("name"),
            "labels": [l["name"] for l in issue["labels"]["nodes"]],
            "description": clean_description(issue["description"]),
            "comments": [
                {
                    "author": author(c, names),
                    "text": c["body"][:COMMENT_LIMIT] + (" [truncated]" if len(c["body"]) > COMMENT_LIMIT else ""),
                }
                for c in comments
            ],
            "earlier_comments_omitted": truncated,
        },
    }
    if evidence is not None:
        state["code_evidence"] = evidence
    return state


def questions(with_evidence):
    out = {}
    for k, q in QUESTIONS.items():
        if q.get("evidence") and not with_evidence:
            continue
        out[k] = {kk: vv for kk, vv in q.items() if kk != "evidence"}
    return out


def classify(issue, with_evidence=True, as_of_pickup=False):
    before = issue.get("startedAt") if as_of_pickup else None
    comments = visible_comments(issue, before)
    # In an eval, links from the issue id to PRs and commits would leak the label, so only the
    # file and symbol lookups are kept.
    evidence = code_evidence(issue, comments, use_issue_links=not as_of_pickup) if with_evidence else None
    res = post(
        TYPESAFE_URL,
        {"state": build_state(issue, comments, evidence), "model": MODEL, "questions": questions(with_evidence)},
        {"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"},
    )
    return {
        "id": issue["identifier"],
        "title": issue["title"],
        "state": issue["state"]["name"],
        "priority": issue["priority"],
        "model": res["model"],
        "usage": res.get("usage"),
        "answers": res["answers"],
        "evidence": evidence,
    }


def write_report(results, out_dir, failures=()):
    order = ["pure_pr", "likely_pr_review", "pr_plus_ops", "needs_decision", "not_pr", "already_resolved"]
    results.sort(key=lambda r: (order.index(r["bucket"]), -r["answers"]["path"]["probabilities"]["pr_only"]))
    counts = {b: sum(r["bucket"] == b for r in results) for b in order}
    lines = [
        "# Jev triage: which issues can be done purely with a PR",
        "",
        f"Model: {results[0]['model'] if results else MODEL}. Issues: {len(results)}.",
        "",
        "| Bucket | Count |",
        "|---|---|",
        *[f"| {b} | {counts[b]} |" for b in order],
        "",
        "Flags: R = needs repo change, O = needs a step outside the repo, D = needs a decision, "
        "P = needs production investigation, X = already resolved, E = code evidence shows it delivered, S = the requested thing already seems to exist in the code. Shown when the probability is 0.5 or more.",
        "",
        *([f"**{len(failures)} issue(s) failed and are missing from this report:** " + "; ".join(failures), ""] if failures else []),
        "| Issue | State | Bucket | Path (p) | p(pr_only) | Flags | Size | Title |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        a = r["answers"]
        flags = "".join(
            k for k, q in (("R", "needs_repo_change"), ("O", "needs_outside_step"), ("D", "needs_decision"),
                           ("P", "needs_prod_investigation"), ("X", "already_resolved"))
            if q in a and a[q]["noul"] >= 0.5
        ) or "-"
        if "evidence_shows_done" in a and a["evidence_shows_done"]["noul"] >= 0.5:
            flags += "E"
        if "requested_thing_exists" in a and a["requested_thing_exists"]["noul"] >= 0.5:
            flags += "S"
        path = a["path"]
        title = r["title"].replace("|", "/")[:70]
        lines.append(
            f"| {r['id']} | {r['state']} | {r['bucket']} | {path['choice']} ({path['probabilities'][path['choice']]:.2f}) "
            f"| {path['probabilities']['pr_only']:.2f} | {flags} | {a['size']['score']:.1f} | {title} |"
        )
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return counts


def run_eval(labels_path, with_evidence, workers):
    """Score buckets against labelled outcomes from the pipeline's own history.

    positive: the pipeline shipped a PR for it. negative: closed with no code, or triaged NOT_CODE.
    Each issue is judged on the comments that existed before work began (Linear `startedAt`), with
    issue-id links to PRs and commits withheld, so the label cannot leak into the state.
    """
    labels = json.load(open(labels_path))
    truth = {**{i: True for i in labels["positive"]}, **{i: False for i in labels["negative"]}}
    issues = fetch_by_ids(sorted(truth))
    rows = []
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(lambda i: classify(i, with_evidence, as_of_pickup=True), issues):
            r["bucket"] = bucket(r["answers"], r["evidence"])
            r["label"] = truth[r["id"]]
            rows.append(r)
    def rate(pred):
        tp = sum(pred(r) and r["label"] for r in rows)
        fp = sum(pred(r) and not r["label"] for r in rows)
        pos = sum(r["label"] for r in rows)
        neg = len(rows) - pos
        recall = f"{tp/pos:.0%}" if pos else "n/a"
        fp_rate = f"{fp/neg:.0%}" if neg else "n/a"
        return f"recall {tp}/{pos} ({recall}), false positives {fp}/{neg} ({fp_rate}), precision {tp/max(tp+fp,1):.0%}"
    print("pure_pr:            " + rate(lambda r: r["bucket"] == "pure_pr"))
    print("pure_pr or likely:  " + rate(lambda r: r["bucket"] in ("pure_pr", "likely_pr_review")))
    print("misses (shipped a PR, not called PR): " + ", ".join(f"{r['id']}={r['bucket']}" for r in rows if r["label"] and r["bucket"] not in ("pure_pr", "likely_pr_review")))
    print("false alarms (no PR, called pure_pr): " + ", ".join(r["id"] for r in rows if not r["label"] and r["bucket"] == "pure_pr"))
    return rows


def load_pipeline_config():
    try:
        with open(os.path.join(".agent", "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_repository(path):
    try:
        with open(path, encoding="utf-8") as f:
            repo = json.load(f)
    except FileNotFoundError:
        sys.exit(f"jev_triage: --repository {path} not found (see repository.example.json)")
    for key in ("name", "contains", "does_not_contain"):
        if key not in repo:
            sys.exit(f"jev_triage: {path} has no {key!r}")
    return {k: repo[k] for k in ("name", "contains", "does_not_contain")}


TRIAGE_VERDICT = {
    "pure_pr": "CODE",
    "not_pr": "NOT_CODE",
    "already_resolved": "NOT_CODE",
}


def emit_triage(results, path=os.path.join(".agent", "triage.json")):
    """Merge buckets into the pipeline's triage cache without overwriting existing rows."""
    try:
        with open(path, encoding="utf-8") as f:
            triage = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        triage = {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    added = 0
    for r in results:
        if r["id"] in triage:
            continue
        triage[r["id"]] = {
            "verdict": TRIAGE_VERDICT.get(r["bucket"], "AMBIGUOUS"),
            "reason": f"jev bucket {r['bucket']}",
            "by": "jev-triage",
            "at": now,
        }
        added += 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(triage, f, indent=2)
    os.replace(tmp, path)
    print(f"TRIAGE {path}: {added} row(s) added, existing rows kept")


def main():
    global BASE, PATHSPEC, PR_LIMIT, IGNORE_COMMENTS, CUT_DESCRIPTION, REPOSITORY, INCLUDE_AUTHORS
    cfg = load_pipeline_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repository", help="JSON describing what a PR here can and cannot change (required unless --rebucket)")
    ap.add_argument("--assignee", default=(cfg.get("linear") or {}).get("user"),
                    help="Linear user name to pull issues for (default: linear.user from .agent/config.json)")
    ap.add_argument("--states", default="Todo,Backlog")
    ap.add_argument("--base", default=(cfg.get("git") or {}).get("baseBranch") or "main",
                    help="base branch for code evidence (default: git.baseBranch, else main)")
    ap.add_argument("--pathspec", action="append", default=[],
                    help="limit symbol search to these paths; repeatable (default: whole repository)")
    ap.add_argument("--pr-limit", type=int, default=1000, help="how many recent pull requests to index")
    ap.add_argument("--ignore-comment", action="append",
                    default=list((cfg.get("linear") or {}).get("unparkIgnorePatterns") or []),
                    help="regex; comments matching it are dropped; repeatable")
    ap.add_argument("--cut-description", action="append", default=[],
                    help="regex; the description is cut at its first match; repeatable")
    ap.add_argument("--include-comment-authors", action="store_true",
                    help="send comment authors' names to TypeSafe (default: pseudonyms)")
    ap.add_argument("--out", default=os.path.join(".agent", "jev-triage"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rebucket", action="store_true", help="re-apply bucket() to results.json without calling Jev")
    ap.add_argument("--emit-triage", action="store_true", help="merge buckets into .agent/triage.json")
    ap.add_argument("--ids", help="comma-separated issue ids to classify instead of an assignee query")
    ap.add_argument("--eval", help="labels.json with positive/negative id lists")
    ap.add_argument("--no-evidence", action="store_true", help="omit code_evidence and its questions (version 1 behaviour)")
    args = ap.parse_args()

    BASE = f"origin/{args.base}"
    PATHSPEC = args.pathspec
    PR_LIMIT = args.pr_limit
    IGNORE_COMMENTS = [re.compile(p, re.I) for p in args.ignore_comment]
    CUT_DESCRIPTION = [re.compile(p, re.I) for p in args.cut_description]
    INCLUDE_AUTHORS = args.include_comment_authors

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "results.json")
    with_evidence = not args.no_evidence
    failures = []

    if not args.rebucket:
        if not args.repository:
            sys.exit("jev_triage: --repository is required (see repository.example.json)")
        REPOSITORY = load_repository(args.repository)
        for key in ("LINEAR_API_KEY", "TYPESAFE_API_KEY"):
            if not os.environ.get(key):
                sys.exit(f"jev_triage: {key} is not set")

    if args.eval:
        rows = run_eval(args.eval, with_evidence, args.workers)
        tag = "v1" if args.no_evidence else "v2"
        json.dump(rows, open(os.path.join(args.out, f"eval-{tag}.json"), "w"), indent=1)
        return

    if args.rebucket:
        results = json.load(open(path))
    else:
        if args.ids:
            issues = fetch_by_ids([s.strip() for s in args.ids.split(",")])
        else:
            if not args.assignee:
                sys.exit("jev_triage: --assignee is required (no linear.user in .agent/config.json)")
            issues = fetch_issues(args.assignee, [s.strip() for s in args.states.split(",")])
        results = []
        with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(classify, i, with_evidence): i["identifier"] for i in issues}
            for fut in cf.as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:  # keep going; report failures at the end
                    failures.append(f"{futures[fut]}: {e}")
        if failures:
            print("FAILED " + "; ".join(failures), file=sys.stderr)
    for r in results:
        r["bucket"] = bucket(r["answers"], r.get("evidence"))
    with open(path, "w") as f:
        json.dump(results, f, indent=1)
    counts = write_report(results, args.out, failures)
    tokens = sum((r.get("usage") or {}).get("input_tokens", 0) for r in results)
    print(f"WROTE {args.out}/report.md and results.json: {len(results)} issues, {tokens} input tokens")
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    if args.emit_triage:
        emit_triage(results)


if __name__ == "__main__":
    main()
