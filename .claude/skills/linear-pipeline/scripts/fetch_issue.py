#!/usr/bin/env python3
"""fetch_issue.py <ISSUE-ID> <OUT-PATH>

Write a Linear issue's title and body to OUT-PATH. Print ONLY the path and byte
count -- the issue body never reaches stdout.

That is the entire reason this script exists. The supervisor must cache a ticket
without holding its prose in context, and an MCP tool result enters context while
a file written by a subprocess does not.

Requires LINEAR_API_KEY in the environment. Read scope is sufficient: this script
never writes to Linear. Keep the key out of .agent/config.json, which is committed.

Standard library only -- no jq, no curl, no requests.

Exit codes: 0 ok | 1 Linear error | 2 not found | 3 no key | 4 bad identifier | 5 transport
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.linear.app/graphql"

# Comments frequently carry the real acceptance criteria, so they are part of the
# cached ticket. If the comments selection ever fails against a schema change, the
# fallback query still returns the description -- a partial ticket beats none.
QUERY = """
query($team: String!, $num: Float!) {
  issues(filter: { team: { key: { eq: $team } }, number: { eq: $num } }, first: 1) {
    nodes {
      identifier title description url priority state { name }
      comments(first: 100) {
        nodes { body createdAt user { displayName name } }
      }
    }
  }
}
"""

QUERY_FALLBACK = """
query($team: String!, $num: Float!) {
  issues(filter: { team: { key: { eq: $team } }, number: { eq: $num } }, first: 1) {
    nodes { identifier title description url priority state { name } }
  }
}
"""


def die(code, *lines):
    for line in lines:
        print(line, file=sys.stderr)
    sys.exit(code)


def main():
    if len(sys.argv) != 3:
        die(4, "usage: fetch_issue.py <ISSUE-ID> <OUT-PATH>")
    issue_id, out_path = sys.argv[1], sys.argv[2]

    key = os.environ.get("LINEAR_API_KEY", "").strip()
    if not key:
        die(3,
            "FATAL: LINEAR_API_KEY is not set.",
            "       Export the Pipeline Bot's read-scoped Linear API key before",
            "       running the pipeline. Do not put it in .agent/config.json --",
            "       that file is committed.")

    m = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)-(\d+)", issue_id)
    if not m:
        die(4, f"FATAL: '{issue_id}' is not a TEAM-NUMBER issue identifier.")
    team, num = m.group(1).upper(), float(m.group(2))

    def post(query):
        payload = json.dumps({
            "query": query,
            "variables": {"team": team, "num": num},
        }).encode()
        req = urllib.request.Request(
            API, data=payload,
            headers={"Authorization": key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # Never echo the response body: an error page can carry request context.
            die(5, f"FATAL: Linear returned HTTP {e.code}. "
                   "Check that LINEAR_API_KEY is valid and has read scope.")
        except (urllib.error.URLError, TimeoutError) as e:
            die(5, f"FATAL: could not reach Linear ({e.__class__.__name__}).")
        except json.JSONDecodeError:
            die(5, "FATAL: Linear returned a response that was not JSON.")

    degraded = False
    body = post(QUERY)
    if body.get("errors"):
        # Retry without comments rather than lose the ticket entirely.
        body = post(QUERY_FALLBACK)
        degraded = True

    if body.get("errors"):
        msgs = "; ".join(e.get("message", "?") for e in body["errors"])
        die(1, f"LINEAR_ERROR: {msgs}")

    nodes = (body.get("data") or {}).get("issues", {}).get("nodes") or []
    if not nodes:
        die(2, f"NOT_FOUND: no issue {issue_id} visible to this key.")
    n = nodes[0]

    lines = [
        f"# {n['identifier']} — {n.get('title') or '(untitled)'}",
        "",
        f"- state: {(n.get('state') or {}).get('name', 'unknown')}",
        f"- priority: {n.get('priority') or 0}",
        f"- url: {n.get('url', '')}",
        "",
        "## Description",
        "",
        n.get("description") or "_No description on the ticket._",
        "",
    ]

    comments = ((n.get("comments") or {}).get("nodes")) or []
    lines += ["## Comments", ""]
    if degraded:
        lines += ["_Comments could not be fetched; the ticket may carry context not shown here._", ""]
    elif not comments:
        lines += ["_No comments on the ticket._", ""]
    else:
        for c in comments:
            who = (c.get("user") or {}).get("displayName") \
                  or (c.get("user") or {}).get("name") or "unknown"
            when = (c.get("createdAt") or "")[:19].replace("T", " ")
            lines += [f"### {who} — {when}", "", (c.get("body") or "").strip(), ""]

    doc = "\n".join(lines)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)

    print(f"WROTE {out_path} ({len(doc.encode())} bytes, {len(comments)} comment(s){' — DEGRADED: no comments' if degraded else ''})")


if __name__ == "__main__":
    main()
