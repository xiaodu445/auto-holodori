# Game_agent development rules

Before changing game automation, read `docs/development-guardrails.md` and relevant entries in `docs/bug-ledger.md`.

For ALL game UI scenarios, also read `docs/interaction-contract.md`. New UI flows must register their semantic policy in domains/hololive_dreams/interaction.py and reuse its transition/RetryBudget (or document a reviewed specialized adapter). Do not implement click-once-and-wait-forever, blind repeats, or skip unexpected popup discovery. Every new flow needs dropped-input, delayed-popup, disabled-control and cancellation regression tests. Passive multiplayer waiting, realtime rhythm input, and non-idempotent spending must never inherit menu auto-repeat. Keep the contract's migration coverage table accurate; unmodified standalone EXEs are not automatically covered.

For every user-reported bug: add/update a ledger entry, separate proven root cause from hypothesis, add a targeted regression test where feasible, and document offline/live verification boundaries. Never report input delivery, missing matches, or bounded scanning as verified reward collection or global completion.

Preserve user configuration and unrelated changes. New daily modules must remain independently selectable, honor stop/focus checks, and use the existing journal/reward hooks. Claim-only changes must not buy, unlock paid passes, exchange currency, or follow unfinished-objective GO buttons.
