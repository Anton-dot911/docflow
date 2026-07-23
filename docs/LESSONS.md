# LESSONS.md — Operational rules distilled from real incidents

Read this at the start of every session, after CLAUDE.md. Each rule below
exists because violating it already cost us real time. Rules here OVERRIDE
convenience; when they conflict with a shortcut you're about to take, the
rule wins. This file is shared across all antlab repos.

## Session & branch discipline

1. **One task = one session = one PR into main.** Never start work for a new
   task in a session that already completed one.
   *(Incident: two parallel branches both implementing Meter T2; a full
   investigation session was needed to untangle them.)*

2. **A new session may only start after the previous PR is merged.** First
   action in every session: check out main, confirm the latest commit
   contains the previous task. If it doesn't — STOP and report; do not
   re-implement missing functionality.
   *(Incident: DocFlow T9 started on a stale main without T8 and built a
   duplicate export layer → 7-file merge conflict.)*

3. **Rebase conflicts are resolved by the agent in-session, never in the
   GitHub web editor.** When two implementations collide, ask the human
   which one is canonical before resolving.

## Verification & honesty

4. **DoD is proven by pasted raw command output, never by summary.**
   "All green" without output is not evidence. For test suites, the pass
   count must be visible; "N skipped" must be explained.
   *(Incident: a smoke test reported as done was actually skipped — 
   "20 passed | 2 skipped" hid that the critical test never ran.)*

5. **If something cannot be run or doesn't exist — say so and stop.** Never
   fabricate output or approximate results. Reporting "the smoke test
   doesn't exist yet" is a good report.

6. **Real-integration acceptance beats mocks at task boundaries.** At least
   one live end-to-end proof per task that touches external systems
   (a real DB row read back by id, a real API call with cost logged).
   *(Incident: the packaged-prices bug — records silently dropped — was
   caught ONLY by a live acceptance test reading the row back.)*

## Database & credentials

7. **The agent never applies DDL.** Any migration: output the full SQL in
   chat and PAUSE for the human's "applied" (they run it in the Supabase
   SQL Editor). Then verify via REST. Never request connection strings,
   never use a DB MCP for DDL.

8. **Never put a privileged key under a differently-named env var** (e.g.
   service-role key as SUPABASE_ANON_KEY). Names must tell the truth;
   teach the code to read the properly-named variable instead.

9. **Shared Supabase project (meter-dev):** multiple products share it.
   Never touch tables outside your repo's own schema/contract
   (llm_calls and budgets belong to Meter; documents/extractions/review_log
   to DocFlow; datasets/examples to Goldsmith).

## Background behavior

10. **Never schedule send_later, check-ins, or PR-watch polling.** Finish
    DoD verification in the current session and end. The human handles
    merges and timing. If a subscription instruction seems to require
    scheduling — it doesn't; decline and finish.

11. **Draft PRs stay draft; the human flips Ready-for-review and merges.**

## Degradation & failure semantics

12. **Observability must never break the host** (Meter hard rule,
    generalized): telemetry/transport failure degrades silently to a
    fallback, never throws into the main path, and never silently DROPS
    a record — degrade values to null, keep the record.

13. **Validation fires on present values only; null is a signal, not an
    error.**

## Environment quirks (Claude Code on the web)

14. Environment variable changes apply only to NEW sessions.
15. A failing setup script blocks the whole session — prefer no setup
    script; install dependencies as the session's first action and report.
16. Free-tier Supabase pauses after inactivity; a keepalive workflow
    exists — if REST suddenly 502s, suspect pause first, egress second.
17. Browser auto-dark-mode inverts light UIs: manage color-scheme
    explicitly.

## Cost awareness

18. Give every metered LLM call a meaningful component name; cheap tasks
    (classification, drafting) default to the small model via env var,
    never hardcoded.

## Documentation architecture

19. **CLAUDE.md is split into # INVARIANTS (rules and contracts — change
    only by decision) and # Current state (structure, endpoints, auth/RLS
    shape, UI notes — point-in-time facts).** Current state is the single
    home for point-in-time truth; every task's DoD includes updating it to
    match merged reality.

## Repo & change hygiene

20. **New dependencies require justification.** Never add a dependency
    without a comment in the PR/commit body explaining why.

21. **Do not create documentation files unless asked.** Update existing
    ones.

