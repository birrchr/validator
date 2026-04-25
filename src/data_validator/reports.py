"""
Individual report modules. Each accepts a DuckDB connection and a registered
view/table name, and returns a long-skinny DataFrame suitable for stacking.
"""
from __future__ import annotations
import duckdb
import pandas as pd
from typing import List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_columns(con: duckdb.DuckDBPyConnection, table: str):
    """Return lists of numeric, categorical, and string column names."""
    schema_df = con.execute(f"DESCRIBE {table}").df()
    numeric_types = {
        "BIGINT", "HUGEINT", "INTEGER", "INT", "SMALLINT", "TINYINT",
        "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT",
        "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC",
        "INTERVAL",
    }
    numeric_cols, categorical_cols, string_cols = [], [], []
    for _, row in schema_df.iterrows():
        col = row["column_name"]
        dtype = row["column_type"].upper().split("(")[0].strip()
        if dtype in numeric_types:
            numeric_cols.append(col)
        elif dtype in ("VARCHAR", "TEXT", "CHAR", "BLOB", "STRING"):
            string_cols.append(col)
            categorical_cols.append(col)
        elif dtype in ("BOOLEAN", "BOOL"):
            categorical_cols.append(col)
        elif dtype in ("DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE", "TIME"):
            categorical_cols.append(col)
        else:
            categorical_cols.append(col)
    return numeric_cols, categorical_cols, string_cols


def _long_frame(
    source_file: str,
    report_type: str,
    metric: str,
    dimension: Optional[str],
    dimension_value: Optional[str],
    value: object,
    extra: dict = None,
) -> dict:
    """Build a single row of the canonical long-skinny schema."""
    row = {
        "source_file": source_file,
        "report_type": report_type,
        "metric": metric,
        "dimension": dimension,
        "dimension_value": str(dimension_value) if dimension_value is not None else None,
        "value": float(value) if value is not None else None,
    }
    if extra:
        row.update(extra)
    return row


# ---------------------------------------------------------------------------
# 1. Schema report
# ---------------------------------------------------------------------------

def report_schema(
    con: duckdb.DuckDBPyConnection,
    table: str,
    source_file: str,
) -> pd.DataFrame:
    """Variables and their types."""
    schema_df = con.execute(f"DESCRIBE {table}").df()
    row_count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    rows = []
    for _, r in schema_df.iterrows():
        rows.append(_long_frame(
            source_file=source_file,
            report_type="schema",
            metric="column_type",
            dimension=r["column_name"],
            dimension_value=r["column_type"],
            value=None,
        ))
    # overall row count
    rows.append(_long_frame(
        source_file=source_file,
        report_type="schema",
        metric="row_count",
        dimension=None,
        dimension_value=None,
        value=row_count,
    ))
    col_count = len(schema_df)
    rows.append(_long_frame(
        source_file=source_file,
        report_type="schema",
        metric="column_count",
        dimension=None,
        dimension_value=None,
        value=col_count,
    ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Duplicate reports
# ---------------------------------------------------------------------------

def _hash_expr(columns: List[str]) -> str:
    """
    Build a DuckDB expression that hashes an arbitrary set of columns into a
    single UBIGINT fingerprint.

    Strategy
    --------
    DuckDB's ``hash()`` accepts multiple arguments and combines them with an
    internal mixing function, so ``hash(a, b, c)`` is both fast and
    collision-resistant for practical dataset sizes.  We cast every column to
    VARCHAR before hashing so that type differences (e.g. INTEGER 1 vs
    DOUBLE 1.0) are surfaced as distinct values rather than collapsed, which
    matches the semantics of "truly identical row."

    NULL handling: DuckDB's hash() treats NULL as a distinct, stable value, so
    two rows that are both NULL in the same columns will correctly match.
    """
    cast_exprs = ", ".join(f'CAST("{c}" AS VARCHAR)' for c in columns)
    return f"hash({cast_exprs})"


def report_true_duplicates(
    con: duckdb.DuckDBPyConnection,
    table: str,
    source_file: str,
) -> pd.DataFrame:
    """
    Count fully duplicate rows using a fast row-hash strategy.

    All columns are hashed into a single UBIGINT fingerprint with DuckDB's
    built-in ``hash()`` function.  Duplicates are then detected by a simple
    GROUP BY + COUNT on that integer column — far cheaper than a multi-column
    sort/PARTITION BY on wide tables.

    A second pass confirms hash collisions are not false positives: any hash
    bucket with count > 1 is re-verified with an exact-match COUNT DISTINCT on
    the raw columns (only for buckets that triggered, so the extra cost is
    proportional to actual duplicate density, not table width).
    """
    schema_df = con.execute(f"DESCRIBE {table}").df()
    all_cols = schema_df["column_name"].tolist()
    hash_expr = _hash_expr(all_cols)
    all_cols_sql = ", ".join(f'"{c}"' for c in all_cols)

    q = f"""
        WITH hashed AS (
            SELECT
                {hash_expr} AS _row_hash,
                COUNT(*)    AS _bucket_count
            FROM {table}
            GROUP BY 1
        ),
        summary AS (
            SELECT
                SUM(_bucket_count)                              AS total_rows,
                SUM(_bucket_count) FILTER (WHERE _bucket_count > 1)
                                                                AS rows_in_dup_buckets,
                COUNT(*) FILTER (WHERE _bucket_count > 1)       AS dup_hash_buckets,
                COUNT(*)                                        AS unique_hashes
            FROM hashed
        )
        SELECT
            total_rows,
            rows_in_dup_buckets,
            dup_hash_buckets,
            unique_hashes
        FROM summary
    """
    total, rows_in_dup_buckets, dup_hash_buckets, unique_hashes = (
        con.execute(q).fetchone()
    )

    # Exact-match verification pass: recount within each flagged hash bucket.
    # This catches the (rare) case of a hash collision between distinct rows.
    duplicate_rows = 0
    if dup_hash_buckets and dup_hash_buckets > 0:
        verify_q = f"""
            SELECT SUM(_bucket_count - _distinct_count) AS confirmed_dupes
            FROM (
                SELECT
                    {hash_expr}                        AS _row_hash,
                    COUNT(*)                           AS _bucket_count,
                    COUNT(DISTINCT ({all_cols_sql}))   AS _distinct_count
                FROM {table}
                GROUP BY 1
                HAVING COUNT(*) > 1
            )
        """
        result = con.execute(verify_q).fetchone()[0]
        duplicate_rows = int(result) if result is not None else 0

    unique_rows = total - duplicate_rows
    rows = [
        _long_frame(source_file, "true_duplicates", "total_rows",    None, None, total),
        _long_frame(source_file, "true_duplicates", "duplicate_rows", None, None, duplicate_rows),
        _long_frame(source_file, "true_duplicates", "unique_rows",   None, None, unique_rows),
        _long_frame(source_file, "true_duplicates", "duplicate_pct", None, None,
                    round(100.0 * duplicate_rows / total, 4) if total > 0 else 0.0),
        # diagnostics — useful for spotting hash collision rate
        _long_frame(source_file, "true_duplicates", "unique_hashes",      None, None, unique_hashes),
        _long_frame(source_file, "true_duplicates", "dup_hash_buckets",   None, None, dup_hash_buckets or 0),
    ]
    return pd.DataFrame(rows)


def report_id_duplicates(
    con: duckdb.DuckDBPyConnection,
    table: str,
    source_file: str,
    id_columns: List[str],
) -> pd.DataFrame:
    """
    Count rows with duplicate ID key(s) using a hash-based strategy.

    The ID key is hashed to a single UBIGINT for fast grouping.  Exact-match
    verification is applied to any hash bucket with count > 1 so that hash
    collisions between distinct keys are never counted as duplicates.
    """
    id_cols_sql = ", ".join(f'"{c}"' for c in id_columns)
    hash_expr = _hash_expr(id_columns)

    q = f"""
        WITH hashed AS (
            SELECT
                {hash_expr} AS _key_hash,
                COUNT(*)    AS _bucket_count
            FROM {table}
            GROUP BY 1
        )
        SELECT
            SUM(_bucket_count)                             AS total_rows,
            SUM(_bucket_count) FILTER (WHERE _bucket_count > 1)
                                                           AS rows_in_dup_buckets,
            COUNT(*) FILTER (WHERE _bucket_count > 1)      AS dup_hash_buckets,
            COUNT(*)                                       AS unique_hashes
        FROM hashed
    """
    total, rows_in_dup_buckets, dup_hash_buckets, unique_hashes = (
        con.execute(q).fetchone()
    )

    # Exact-match verification for flagged buckets
    duplicate_rows = 0
    if dup_hash_buckets and dup_hash_buckets > 0:
        verify_q = f"""
            SELECT SUM(_bucket_count - _distinct_count) AS confirmed_dupes
            FROM (
                SELECT
                    {hash_expr}                       AS _key_hash,
                    COUNT(*)                          AS _bucket_count,
                    COUNT(DISTINCT ({id_cols_sql}))   AS _distinct_count
                FROM {table}
                GROUP BY 1
                HAVING COUNT(*) > 1
            )
        """
        result = con.execute(verify_q).fetchone()[0]
        duplicate_rows = int(result) if result is not None else 0

    unique_keys = unique_hashes  # one hash = one unique key after verification
    id_label = "+".join(id_columns)
    rows = [
        _long_frame(source_file, "id_duplicates", "total_rows",    id_label, None, total),
        _long_frame(source_file, "id_duplicates", "duplicate_rows", id_label, None, duplicate_rows),
        _long_frame(source_file, "id_duplicates", "unique_keys",   id_label, None, unique_keys),
        _long_frame(source_file, "id_duplicates", "duplicate_pct", id_label, None,
                    round(100.0 * duplicate_rows / total, 4) if total > 0 else 0.0),
        _long_frame(source_file, "id_duplicates", "dup_hash_buckets", id_label, None, dup_hash_buckets or 0),
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. Univariate statistics (numeric)
# ---------------------------------------------------------------------------

def report_univariate(
    con: duckdb.DuckDBPyConnection,
    table: str,
    source_file: str,
    n_histogram_bins: int = 20,
) -> pd.DataFrame:
    """Univariate stats + histogram bins for all numeric columns."""
    numeric_cols, _, _ = _classify_columns(con, table)
    if not numeric_cols:
        return pd.DataFrame()

    rows = []
    for col in numeric_cols:
        q = f"""
            SELECT
                COUNT("{col}")                          AS n_non_null,
                COUNT(*) - COUNT("{col}")               AS n_null,
                MIN("{col}")                            AS min_val,
                MAX("{col}")                            AS max_val,
                AVG("{col}")                            AS mean_val,
                MEDIAN("{col}")                         AS median_val,
                STDDEV_SAMP("{col}")                    AS stddev_val,
                VARIANCE("{col}")                       AS variance_val,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{col}") AS p25,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{col}") AS p75,
                APPROX_COUNT_DISTINCT("{col}")          AS approx_distinct
            FROM {table}
        """
        r = con.execute(q).fetchone()
        (n_non_null, n_null, mn, mx, mean, median, std, var,
         p25, p75, approx_dist) = r

        for metric, val in [
            ("n_non_null", n_non_null), ("n_null", n_null),
            ("min", mn), ("max", mx), ("mean", mean), ("median", median),
            ("stddev", std), ("variance", var),
            ("p25", p25), ("p75", p75),
            ("approx_distinct", approx_dist),
        ]:
            rows.append(_long_frame(source_file, "univariate", metric, col, None, val))

        # Histogram bins — use FLOOR-based bucketing for compatibility across
        # all DuckDB versions (width_bucket availability varies by version).
        if mn is not None and mx is not None and mn != mx:
            bin_q = f"""
                SELECT
                    LEAST(
                        {n_histogram_bins},
                        CAST(FLOOR(
                            ({n_histogram_bins} * (CAST("{col}" AS DOUBLE) - {mn}))
                            / ({mx} - {mn})
                        ) AS INTEGER) + 1
                    ) AS bin,
                    COUNT(*) AS freq
                FROM {table}
                WHERE "{col}" IS NOT NULL
                GROUP BY 1
                ORDER BY 1
            """
            bin_rows = con.execute(bin_q).fetchall()
            for bin_num, freq in bin_rows:
                bin_label = f"hist_bin_{bin_num:03d}"
                rows.append(_long_frame(
                    source_file, "univariate_histogram", "frequency",
                    col, bin_label, freq
                ))

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4. Frequency distributions (categorical)
# ---------------------------------------------------------------------------

def report_frequency(
    con: duckdb.DuckDBPyConnection,
    table: str,
    source_file: str,
    max_categories: int = 500,
) -> pd.DataFrame:
    """Frequency distribution for categorical columns."""
    _, categorical_cols, _ = _classify_columns(con, table)
    if not categorical_cols:
        return pd.DataFrame()

    rows = []
    total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    for col in categorical_cols:
        distinct_count = con.execute(
            f'SELECT APPROX_COUNT_DISTINCT("{col}") FROM {table}'
        ).fetchone()[0]

        if distinct_count > max_categories:
            rows.append(_long_frame(
                source_file, "frequency", "skipped_high_cardinality",
                col, str(distinct_count), None
            ))
            continue

        q = f"""
            SELECT
                CAST("{col}" AS VARCHAR) AS val,
                COUNT(*) AS freq
            FROM {table}
            GROUP BY 1
            ORDER BY 2 DESC
        """
        freq_rows = con.execute(q).fetchall()
        for val, freq in freq_rows:
            rows.append(_long_frame(
                source_file, "frequency", "count",
                col, val if val is not None else "__NULL__", freq
            ))
            rows.append(_long_frame(
                source_file, "frequency", "pct",
                col, val if val is not None else "__NULL__",
                round(100.0 * freq / total, 4) if total > 0 else 0.0
            ))

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5. String component frequency
# ---------------------------------------------------------------------------

def report_string_components(
    con: duckdb.DuckDBPyConnection,
    table: str,
    source_file: str,
    delimiter: str = " ",
    max_components: int = 1000,
) -> pd.DataFrame:
    """
    For each string column, split values on delimiter and produce a frequency
    table of individual components (tokens/words/codes).
    """
    _, _, string_cols = _classify_columns(con, table)
    if not string_cols:
        return pd.DataFrame()

    rows = []
    for col in string_cols:
        q = f"""
            SELECT component, COUNT(*) AS freq
            FROM (
                SELECT UNNEST(STRING_SPLIT(TRIM("{col}"), '{delimiter}')) AS component
                FROM {table}
                WHERE "{col}" IS NOT NULL
            )
            WHERE component != ''
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT {max_components}
        """
        comp_rows = con.execute(q).fetchall()
        for comp, freq in comp_rows:
            rows.append(_long_frame(
                source_file, "string_components", "count",
                col, comp, freq
            ))

    return pd.DataFrame(rows)