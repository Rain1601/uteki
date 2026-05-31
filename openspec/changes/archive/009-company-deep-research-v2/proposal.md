# 009 · Company deep research v2

## Why

The current company pipeline can produce a single-company 6-gate memo, but the next useful product goal is deeper investment research: compare the target company with up to three peers, rank candidates, recommend an action, and translate conviction into a bounded capital plan.

## What changes

- Parse a target US stock plus up to three user-supplied peers.
- Auto-fill up to three peers when the user does not supply them.
- Collect quote, financial, and news evidence for target and peers.
- Persist peer comparison, ranking, capital plan, and agent capability review artifacts.
- Add capital management recommendations without real order execution.
- Review autonomy, observability, traceability, and self-iteration after each major stage.

## Out of scope

- Real brokerage/trading integration.
- Portfolio-wide optimizer.
- Sector taxonomy service.
- Frontend redesign beyond consuming the new artifacts through the existing run artifact view.
