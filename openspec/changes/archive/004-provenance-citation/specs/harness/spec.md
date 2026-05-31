# Harness provenance delta — spec draft

## Source injection

Harness injects run-scoped source state into the skill before `skill.run()`:

```python
self.skill.sources = RunSources(...)
```

This mirrors `self.skill.artifacts`.

## Tool result registration

`ToolResult` may include:

```python
sources: list[dict] = []
```

Harness registers those source partials into the current run catalog after a tool finishes.

The emitted `tool_result` event includes registered ids in its data payload when available.

## Run finish

Before `done` or immediately before `run_store.finish`, harness ensures the source catalog is persisted as `source-catalog.json` if it has at least one item.

## Invariants

1. Skills and tools do not know filesystem paths for source catalog artifacts.
2. Missing or malformed source metadata does not fail a run; it becomes verifier input.
3. No source catalog is emitted for runs with zero registered sources.

