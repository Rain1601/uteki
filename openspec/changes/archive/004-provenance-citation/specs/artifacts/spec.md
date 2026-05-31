# Artifacts provenance delta — spec draft

## New standard artifact

```text
source-catalog.json
```

Purpose:

- Durable source state for a run.
- Input to evaluator citation checks.
- Future UI source drawer / citation chip backing data.

## Naming

`source-catalog.json` is reserved. Skills should not use the name for unrelated content.

## Event

When written, emit existing event type:

```python
artifact_written
```

with:

```json
{
  "name": "source-catalog.json",
  "kind": "json",
  "written_by": "<skill-name-or-harness>",
  "description": "Run source catalog"
}
```

