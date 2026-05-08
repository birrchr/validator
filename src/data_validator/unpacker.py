"""
unpacker.py
-----------
Utilities for unpacking the encoded dimension_value column produced by
DataValidator crosstab reports back into individual dimension columns.

The dimension_value format is:  key1=value1|key2=value2|key3=value3
For example:
    "year=2021|province=ON|housing_type=Single detached"

Output folder structure (as written by validator.py)
-----------------------------------------------------
    validation/
        schema__<file>.parquet
        univariate__<file>.parquet
        frequency__<file>.parquet
        ...
        year_prov_housing/              ← one folder per tabulation label
            dwelling_count__<file>.parquet
            avg_assessed_value__<file>.parquet
        year_cmaca_tenure/
            dwelling_count__<file>.parquet
            vacancy_rate_pct__<file>.parquet

Two output modes are supported:

WIDE (default)
    One column per dimension key, one row per metric value.
    Best for a single crosstab you want to analyse directly.

    year  | province | housing_type      | metric          | value
    2021  | ON       | Single detached   | dwelling_count  | 4521

LONG (stacked)
    Each dimension key-value pair becomes its own row alongside the metric.
    Schema is identical regardless of how many dimensions the crosstab has,
    so outputs from a*b and a*b*c*d can be stacked in Power BI without
    schema reconciliation.

    label             | dim_key       | dim_value         | metric          | value
    year_prov_housing | province      | ON                | dwelling_count  | 4521
    year_prov_housing | housing_type  | Single detached   | dwelling_count  | 4521
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

import duckdb
import pandas as pd


# ---------------------------------------------------------------------------
# Internal: Parquet writer
# ---------------------------------------------------------------------------

def _duckdb_write(df: pd.DataFrame, out_path: Path) -> None:
    """
    Write a DataFrame to Parquet using DuckDB's native COPY writer.

    Uses PARQUET_VERSION 'V1' which is readable by all PyArrow versions
    including older Anaconda installs. Never use df.to_parquet() or PyArrow
    directly — they produce format 2.6 by default which causes 'Repetition
    level histogram size mismatch' errors in Data Wrangler.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("_tmp", df)
    con.execute(f"""
        COPY (SELECT * FROM _tmp)
        TO '{out_path}'
        (FORMAT 'PARQUET', COMPRESSION 'snappy', PARQUET_VERSION 'V1')
    """)
    con.close()


# ---------------------------------------------------------------------------
# Internal: dimension key inference and SQL builder
# ---------------------------------------------------------------------------

def _get_dimension_keys(con: duckdb.DuckDBPyConnection, table: str) -> List[str]:
    """
    Infer dimension keys from the first non-null dimension_value in the table.
    Returns ordered list of keys, e.g. ['year', 'province', 'housing_type'].
    """
    sample = con.execute(f"""
        SELECT dimension_value
        FROM {table}
        WHERE dimension_value IS NOT NULL
          AND dimension_value != ''
          AND report_type = 'crosstab'
        LIMIT 1
    """).fetchone()

    if not sample:
        return []

    pairs = sample[0].split("|")
    return [pair.split("=", 1)[0] for pair in pairs if "=" in pair]


def _parse_sql(keys: List[str]) -> str:
    """
    Build DuckDB SQL expressions that parse dimension_value into one column
    per key using string_split and 1-based list indexing.
    """
    key_cols = []
    for i, key in enumerate(keys):
        expr = (
            f"string_split("
            f"string_split(dimension_value, '|')[{i + 1}], "
            f"'=')[2]"
        )
        key_cols.append(f"{expr} AS \"{key}\"")
    return ", ".join(key_cols)


# ---------------------------------------------------------------------------
# Public API — unpack functions
# ---------------------------------------------------------------------------

def unpack_wide(
    source: Union[str, Path, pd.DataFrame],
    con: Optional[duckdb.DuckDBPyConnection] = None,
    filter_metric: Optional[str] = None,
    filter_label: Optional[str] = None,
) -> pd.DataFrame:
    """
    Unpack a crosstab parquet file (or DataFrame) into wide format —
    one column per dimension key, one row per group × metric combination.

    Parameters
    ----------
    source : str, Path, or DataFrame
        Path to a validation parquet file, or a DataFrame already loaded.
        Can be a file inside a labelled subfolder (e.g.
        'validation/year_prov_housing/dwelling_count__survey.parquet').
    con : duckdb.DuckDBPyConnection, optional
        Existing DuckDB connection to reuse. A temporary one is created if omitted.
    filter_metric : str, optional
        Only return rows where metric == this value.
    filter_label : str, optional
        Only return rows where dimension == this value (the tabulation label).

    Returns
    -------
    pd.DataFrame with columns: source_file, metric, <dim1>, <dim2>, ..., value

    Example
    -------
    >>> df = unpack_wide(
    ...     "validation/year_prov_housing/dwelling_count__survey.parquet"
    ... )
    >>> df.columns
    ['source_file', 'metric', 'year', 'province', 'housing_type', 'value']
    """
    _con = con or duckdb.connect()

    if isinstance(source, pd.DataFrame):
        _con.register("_src", source)
        table = "_src"
    else:
        path = str(Path(source))
        _con.execute(
            f"CREATE OR REPLACE TEMP VIEW _src AS SELECT * FROM read_parquet('{path}')"
        )
        table = "_src"

    where_parts = ["report_type = 'crosstab'"]
    if filter_metric:
        where_parts.append(f"metric = '{filter_metric}'")
    if filter_label:
        where_parts.append(f"dimension = '{filter_label}'")
    where = " AND ".join(where_parts)

    _con.execute(
        f"CREATE OR REPLACE TEMP VIEW _filtered AS SELECT * FROM {table} WHERE {where}"
    )

    keys = _get_dimension_keys(_con, "_filtered")
    if not keys:
        return pd.DataFrame()

    key_sql = _parse_sql(keys)
    key_col_names = ", ".join(f'"{k}"' for k in keys)

    q = f"""
        SELECT
            source_file,
            metric,
            {key_sql},
            value
        FROM _filtered
        ORDER BY {key_col_names}, metric
    """
    result = _con.execute(q).df()

    if con is None:
        _con.close()

    return result


def unpack_long(
    source: Union[str, Path, pd.DataFrame],
    con: Optional[duckdb.DuckDBPyConnection] = None,
    filter_metric: Optional[str] = None,
    filter_label: Optional[str] = None,
) -> pd.DataFrame:
    """
    Unpack a crosstab parquet file (or DataFrame) into long format —
    each dimension key-value pair becomes its own row alongside the metric.

    The output schema is always 6 columns regardless of how many dimensions
    the crosstab has, making it ideal for stacking in Power BI.

    Parameters
    ----------
    source : str, Path, or DataFrame
        Path to a parquet file or DataFrame.
    con : duckdb.DuckDBPyConnection, optional
        Existing connection to reuse.
    filter_metric : str, optional
        Only return rows where metric == this value.
    filter_label : str, optional
        Only return rows where dimension == this value.

    Returns
    -------
    pd.DataFrame with columns:
        source_file, label, metric, value, dim_key, dim_value

    Example
    -------
    >>> df = unpack_long(
    ...     "validation/year_prov_housing/dwelling_count__survey.parquet"
    ... )
    """
    _con = con or duckdb.connect()

    if isinstance(source, pd.DataFrame):
        _con.register("_src", source)
        table = "_src"
    else:
        path = str(Path(source))
        _con.execute(
            f"CREATE OR REPLACE TEMP VIEW _src AS SELECT * FROM read_parquet('{path}')"
        )
        table = "_src"

    where_parts = ["report_type = 'crosstab'"]
    if filter_metric:
        where_parts.append(f"metric = '{filter_metric}'")
    if filter_label:
        where_parts.append(f"dimension = '{filter_label}'")
    where = " AND ".join(where_parts)

    q = f"""
        SELECT
            source_file,
            dimension        AS label,
            metric,
            value,
            string_split(pair, '=')[1] AS dim_key,
            string_split(pair, '=')[2] AS dim_value
        FROM (
            SELECT
                source_file,
                dimension,
                metric,
                value,
                UNNEST(string_split(dimension_value, '|')) AS pair
            FROM {table}
            WHERE {where}
        )
        WHERE pair != ''
        ORDER BY source_file, label, metric, dim_key
    """
    result = _con.execute(q).df()

    if con is None:
        _con.close()

    return result


# ---------------------------------------------------------------------------
# Public API — folder-level operations
# ---------------------------------------------------------------------------

# Standard report prefixes that live in validation/ root — not crosstabs.
_STANDARD_PREFIXES = (
    "schema__",
    "true_duplicates__",
    "id_duplicates__",
    "univariate__",
    "univariate_histogram__",
    "frequency__",
    "string_components__",
)


def unpack_folder(
    validation_dir: Union[str, Path],
    label: Optional[str] = None,
    mode: str = "long",
    filter_metric: Optional[str] = None,
    filter_label: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load and unpack crosstab parquet files from the validation folder structure,
    then stack them into a single DataFrame.

    Folder targeting
    ----------------
    Crosstab files live in labelled subfolders:
        validation/year_prov_housing/dwelling_count__survey.parquet
        validation/year_cmaca_tenure/dwelling_count__survey.parquet

    - ``label=None`` (default): loads all subfolders (all breakdowns)
    - ``label="year_prov_housing"``: loads only that breakdown's folder

    Parameters
    ----------
    validation_dir : str or Path
        Path to the validation/ folder.
    label : str, optional
        Subfolder name (tabulation label) to target. None = all subfolders.
    mode : str
        "wide" or "long". Use "long" for stacking across different breakdowns.
    filter_metric : str, optional
        Only include rows where metric == this value.
    filter_label : str, optional
        Only include rows where dimension == this value.

    Returns
    -------
    pd.DataFrame

    Notes
    -----
    Wide mode stacks are only meaningful when all loaded files share the same
    dimensions. If loading across multiple subfolders (different breakdowns),
    use mode="long".

    Example
    -------
    >>> # All breakdowns, long format
    >>> df = unpack_folder("examples/output/validation", mode="long")

    >>> # One specific breakdown only
    >>> df = unpack_folder(
    ...     "examples/output/validation",
    ...     label="year_prov_housing",
    ...     mode="wide",
    ... )
    """
    folder = Path(validation_dir)

    if label is not None:
        # Target a specific subfolder
        target_dirs = [folder / label]
    else:
        # All immediate subdirectories (each is a tabulation label)
        target_dirs = [d for d in sorted(folder.iterdir()) if d.is_dir()]

    parquet_files = []
    for d in target_dirs:
        parquet_files.extend(sorted(d.glob("*.parquet")))

    if not parquet_files:
        return pd.DataFrame()

    fn = unpack_wide if mode == "wide" else unpack_long
    frames = []
    con = duckdb.connect()

    for p in parquet_files:
        try:
            df = fn(p, con=con, filter_metric=filter_metric, filter_label=filter_label)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            import warnings
            warnings.warn(f"Could not unpack {p}: {e}")

    con.close()

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def save_unpacked(
    validation_dir: Union[str, Path],
    output_path: Union[str, Path],
    label: Optional[str] = None,
    mode: str = "long",
    filter_metric: Optional[str] = None,
    filter_label: Optional[str] = None,
) -> Path:
    """
    Unpack crosstab files and write the result to a single parquet file.

    Uses DuckDB native COPY writer (PARQUET_VERSION V1) for compatibility
    with all PyArrow versions including older Anaconda installs.

    Parameters
    ----------
    validation_dir : str or Path
        Path to the validation/ folder.
    output_path : str or Path
        Destination parquet file.
    label : str, optional
        Target a specific breakdown subfolder. None = all subfolders.
    mode : str
        "wide" or "long".
    filter_metric, filter_label : str, optional
        Optional filters.

    Returns
    -------
    Path to the written file.

    Example
    -------
    >>> save_unpacked(
    ...     "examples/output/validation",
    ...     "examples/output/crosstabs_unpacked.parquet",
    ...     mode="long",
    ... )

    >>> # One breakdown only
    >>> save_unpacked(
    ...     "examples/output/validation",
    ...     "examples/output/year_prov_housing.parquet",
    ...     label="year_prov_housing",
    ...     mode="wide",
    ... )
    """
    df = unpack_folder(
        validation_dir,
        label=label,
        mode=mode,
        filter_metric=filter_metric,
        filter_label=filter_label,
    )

    if df.empty:
        raise ValueError(
            f"No crosstab files found in '{validation_dir}'"
            + (f" / '{label}'" if label else "")
        )

    out = Path(output_path)
    _duckdb_write(df, out)
    print(f"Saved {len(df):,} rows → {out}")
    return out


def save_dataframe(df: pd.DataFrame, output_path: Union[str, Path]) -> Path:
    """
    Write any DataFrame to parquet using DuckDB native writer (PARQUET_VERSION V1).

    Use this instead of df.to_parquet() to avoid 'Repetition level histogram
    size mismatch' errors when opening files in Data Wrangler or with older
    PyArrow versions.

    Parameters
    ----------
    df : pd.DataFrame
        Any DataFrame to save.
    output_path : str or Path
        Destination parquet file.

    Returns
    -------
    Path to the written file.

    Example
    -------
    >>> df = unpack_wide("validation/year_prov_housing/dwelling_count__survey.parquet")
    >>> save_dataframe(df, "output/dwelling_wide.parquet")
    """
    out = Path(output_path)
    _duckdb_write(df, out)
    print(f"Saved {len(df):,} rows → {out}")
    return out
