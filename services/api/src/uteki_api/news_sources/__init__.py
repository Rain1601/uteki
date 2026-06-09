"""External news source connectors.

Each module here is a thin fetcher + parser that returns provider-neutral
``Filing``-like objects. Glue into the news_article DB lives in the
ingest scripts under ``services/api/scripts/`` and (eventually) under
the trigger scheduler.

Connectors so far:

- ``sec_edgar`` — SEC EDGAR per-CIK Atom feed for 8-K / 10-Q / 10-K.
"""
