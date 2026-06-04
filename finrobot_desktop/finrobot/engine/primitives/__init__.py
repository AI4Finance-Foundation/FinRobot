"""Pure, zero-I/O shared operators.

The lowest compute layer: depends only on stdlib / third-party math libs and
``models/``. Both ``data/`` and ``compute/operators/`` may import DOWN into here;
nothing here imports ``data/`` / ``compute/`` / ``pipelines/`` / ``agents/`` /
``routes/``. This is what lets a provider reuse a pure operator (EBITDA, headline
sentiment, BM25, historical bands) WITHOUT creating a data->compute cycle
(ADR-0005 §2.2).
"""
