# Precise retrieval at terabyte scale - what the research says, and where we are

Written 2026-08-06 against the question: the corpus is heading for terabytes, so
what actually keeps a numeric answer exact at that size?

## The finding that decides the architecture

**You do not embed the data. You embed the catalog.**

Every credible 2026 approach to precise numeric answers over large structured data
converges on the same split:

| layer | holds | size | how it is searched |
|---|---|---|---|
| catalog / schema | table + column names, types, descriptions, stats | megabytes | embeddings + lexical |
| data | the rows | terabytes | generated SQL, never embedded |

Embedding cells does not scale and does not get more accurate with more data - it
gets *less* accurate, because near-duplicate rows crowd the neighbourhood and the
model has to reconstruct an aggregate from a sample of chunks. Retrieval is used
to find *where to compute*, and the computation itself is a SELECT.

This is the same shape `rag/sheet_sql.py` already has: it matches the ask against
column names, then runs the aggregate over the real rows. The difference at TB
scale is that the catalog stops fitting in a prompt and the scan stops being free.

## The failure mode that dominates - and it is not arithmetic

Spider 2.0 is the enterprise text-to-SQL benchmark: real customer databases,
**1000+ columns**, ambiguous business questions, schema noise. When it launched,
frontier LLMs solved roughly **6-21%** of it. By 2026 purpose-built agentic,
schema-aware systems reach around **72% on Spider 2.0-Lite**.

The error breakdown is the useful part:

- **wrong schema linking: 27.6% of all SQL errors**
- of which **column linking errors: 16.6%**

The arithmetic is rarely wrong. *Binding the question to the right column* is what
fails, and it fails more as the schema grows. Schema Linking Recall - did we
retrieve every column the correct answer needs - is the metric that predicts
execution accuracy, because missing one column makes the SQL wrong no matter how
good the generator is.

**We measured this on ourselves and it was immediately true.** The first oracle
bench run scored 18/21 on values, and all three failures were schema-linking:
`OnTime` on a 200k-row sheet outscored `OnTimeSLA` on a 5k-row sheet purely on row
count, and `TotalShipments` was read as a mention of the `Shipments` sheet. Once
schema-link recall was measured separately it also caught two cases that had the
*right value with the wrong binding* - which a value-only benchmark scores as a
pass.

## Techniques worth adopting, in the order they pay off

1. **Schema-first retrieval.** Embed table/column metadata, retrieve
   coarse-to-fine (candidate tables, then columns within them). Reported recall
   80-95% on Spider/BIRD. Cheap, and it is the prerequisite for everything else.
2. **Bidirectional / context-aware schema linking.** Match question -> schema *and*
   schema -> question rather than one direction. Consistently higher recall and F1
   than one-way matching.
3. **Autonomous schema exploration (AutoLink-style).** Rather than stuffing the
   whole schema into context, explore and expand it agentically. Reported **+27.2%
   strict recall on Spider 2.0-Lite over the next best method, with 87.7% less
   peak token use.** This is the one that makes 1000+ column schemas tractable.
4. **Open table formats for the data layer.** Iceberg / Delta / Hudi track files
   and snapshots instead of directories, which buys ACID, time travel, and - the
   part that matters here - **partition pruning and column statistics for file
   skipping**. A well-partitioned TB table answers a filtered aggregate by reading
   a few files.
5. **Engine split by size.** DuckDB is the right in-process engine for
   small-to-medium, reads Parquet and Iceberg directly, and honours partition
   pruning. Genuine petabyte workloads want an MPP engine (Trino / Dremio / Spark).
   Do not plan to scale DuckDB into that range.
6. **Hybrid retrieval for the unstructured half.** Dense + lexical in parallel,
   merged with reciprocal rank fusion, then a reranker. This is for prose, not for
   numbers - it should never be in the path of an aggregate.

## Honest position: what our numbers do and do not show

Our oracle bench reports value accuracy and schema-link recall against ground truth
read straight from the workbook, on questions generated fresh per seed.

What that establishes: the row-range and filter-aggregate paths are arithmetically
sound and bind correctly **on a 5-sheet, ~15-column workbook**.

What it does **not** establish: anything about a 1000-column schema. Our whole
schema is smaller than the noise in a single Spider 2.0 database. The linking
failures we already found appeared at 15 columns - the research says that class of
failure grows with schema size, so the honest expectation is that recall drops
before it holds. Per R-0010, a clean run of n cases bounds the error rate at 3/n,
not at zero; the bench prints that bound rather than claiming perfection.

**The next honest measurement** is to run the oracle bench against a workbook with
hundreds of columns and overlapping names, because that is where the published
failure rate lives. Until that exists, "it works at terabyte scale" is a projection,
not a result.

## What to build next, concretely

1. **Persist a catalog** - sheet/column/type/stats per ingested workbook - instead
   of re-deriving the schema from the file on every ask. This is the prerequisite
   for schema-first retrieval and it removes the full-workbook load from the hot
   path.
2. **Make schema linking retrieval, not substring matching.** The current matcher
   is exact-normalised-substring with a longest-wins rule. That is fine at 15
   columns and will not survive 1000; it needs embeddings over column metadata
   with the lexical rule kept as a high-precision first pass.
3. **Report schema-link recall in every bench run** (done) and gate on it, not
   only on value accuracy.
4. **Push the data layer to Parquet + a table format** before the corpus outgrows
   openpyxl. Reading a 200k-row sheet already dominates our own bench runtime.

## Sources

- [Spider 2.0: Enterprise Text-to-SQL Benchmark](https://www.emergentmind.com/topics/spider-2-0-benchmark)
- [AutoLink: Autonomous Schema Exploration and Expansion for Scalable Schema Linking in Text-to-SQL at Scale](https://arxiv.org/pdf/2511.17190)
- [Rethinking Schema Linking: A Context-Aware Bidirectional Retrieval Approach for Text-to-SQL](https://arxiv.org/pdf/2510.14296)
- [Schema-First Retrieval: Embedding Catalogs for Natural Language Analytics](https://arxiv.org/pdf/2606.28387)
- [ReFoRCE: A Text-to-SQL Agent](https://arxiv.org/pdf/2502.00675)
- [LinkAlign: Scalable Schema Linking for Real-World Large-Scale Multi-Database Text-to-SQL](https://arxiv.org/pdf/2503.18596)
- [Using Apache Iceberg with Python and MPP Query Engines](https://amdatalakehouse.substack.com/p/using-apache-iceberg-with-python)
- [The 2025 & 2026 Ultimate Guide to the Data Lakehouse](https://datalakehousehub.com/blog/2025-09-2026-guide-to-data-lakehouses/)
- [A Survey of NL2SQL with Large Language Models](https://scispace.com/pdf/a-survey-of-nl2sql-with-large-language-models-where-are-we-5iuqr6htij4j.pdf)
