# The pipeline posts to Linear as its own identity

The pipeline writes to Linear through a dedicated **Pipeline Bot** user, reached via a second
project-scoped MCP server entry pointing at the same Linear endpoint, authenticated as that user.
The supervisor's tool allowlist permits only that entry's tools.

This exists because of a flaw found in the unpark mechanism. Linear's MCP connection is
authenticated as the operator, so the pipeline's decision brief and the operator's reply to it would
have the **same author** — making "the newest human comment unparks the issue" unimplementable by
author filtering. A marker embedded in the pipeline's own comments would have solved the detection
problem identity-agnostically and needed no Linear seat; we chose the identity fix instead because
it also answers a question the marker does not: teammates seeing a comment on a shared ticket can
tell whether a person or a machine wrote it.

## Consequences

Setup requires a Linear seat and a separate OAuth grant, so a target repo cannot be onboarded purely
from the terminal — ADR-0006's rule that every outward action belongs to the supervisor now has a
prerequisite the operator must satisfy by hand.

The operator's own Linear access is untouched, and the separation is structural: the supervisor
cannot post as the operator, because those tools are not in its allowlist.

`config.linear.mcpServer` is fatal-if-missing rather than defaulted. Defaulting it would silently
fall back to the operator's identity, reintroducing precisely the problem this decision removes.

**The identity can drift after the fact.** Re-authenticating the bot's MCP entry (for example through
`/mcp` after a token expires) attaches it to whoever completes the browser flow, and that is usually
the operator, signed in as themselves. Nothing fails: every write succeeds, under the wrong name, and
a brief posted as the operator then reads to the unpark check as the operator's own reply. The
supervisor therefore calls `get_user` for `me` at every cold start and holds all Linear writes when it
does not match `linear.user`.
