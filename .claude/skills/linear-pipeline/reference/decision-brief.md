# The decision brief

Written to `.issues/<ISSUE_ID>/decision.md` when you hit a fork you cannot resolve. The supervisor
relays it to Linear verbatim as one comment; a human — or a fresh agent months later — acts on it
without opening this repository.

Write exactly these five parts, in this order:

```markdown
**Situation** — 2-3 sentences on the state of play. What the issue asks, and where it stalled.
**Options** — A / B (/ C). One line each, naming the concrete tradeoff, not the mechanism.
**Recommendation** — which one, and the reason in one sentence.
**Need from you** — the question, phrased so one reply answers it.
**State** — <ISSUE_ID> @ <STAGE>, attempt <n>
            artifacts: <paths that exist>
```

## What each part is for

**Situation** orients someone who has forgotten this issue exists. Present tense, no history of what
you tried — that lives in the artifacts.

**Options** are the real alternatives. Two is normal; three is the ceiling. Each carries the cost of
choosing it, so the reader can decide without deriving the tradeoffs themselves.

**Recommendation** commits. You have read the code and they have not, so an unranked list of options
pushes your work back onto them.

**Need from you** is answerable in one reply. "Should this use the existing queue or a new one?" is
answerable. "How should we approach this?" is not.

**State** is what makes the brief resumable rather than merely readable. A reader who wants the full
story follows those paths; a reader who just wants to decide never has to.

Two things this field gets wrong unless you are deliberate:

- **`<STAGE>` is the literal stage name**, spelled as it appears in `.agent/state.json`:
  `DISCOVERY_STARTED`, `PLANNING_STARTED`, `IMPLEMENTATION_STARTED`. Not a description of what you
  were doing, and not the word your own instructions use for your role. A human matching this brief
  against the state file needs the two to be the same string.
- **List only artifacts that exist.** You are blocking, which usually means the document you would
  normally have produced was never written. Name what is on disk — often just `issue.md` and this
  brief. A path to a file nobody wrote sends the reader looking for context that was never captured.

## The bar

The brief is the only artifact a human reads directly. It clears the bar when someone who has never
seen the issue can answer the question in one reply, from the brief alone.

## Posting

You have no Linear tools, by design: an agent with network side effects cannot be safely re-run after
being killed, and re-running killed stages is how this pipeline survives its usage limit. Write the
file and return `STATUS=BLOCKED`. The supervisor posts it.
