"""Command-line tooling for uteki operators.

Modules here are entrypoints invoked via ``uv run python -m
uteki_api.cli.<name>`` (typically wrapped by a shell script in
``scripts/``). They read the same on-disk state the API writes, so the
operator's CLI workflow doesn't depend on the API being running.
"""
