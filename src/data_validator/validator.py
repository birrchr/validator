"""
DataValidator — DuckDB-powered data validation and profiling engine.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Union

import duckdb
import pandas as pd

from .reports import (
    report_schema,
    report_true_duplicates,
    report_id_duplicates,
    report_univariate,
    report_frequency,
    report_string_components,
)
from .specs import TabulationSpec

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Long/skinny output schema
# ---------------------------------------------------------------------------
OUTPUT_COLUMNS = [
    "source_file",      # basename of the input file
    "report_type",      # e.g. "schema", "univariate", "frequency", "crosstab"
    "metric",           # e.g. "mean", "count", "pct"
    "dimension",        # column name or grouping key label
    "dimension_value",  # value within that dimension
    "value",            # numeric result (all outputs normalised to float)
]


def _sanitize(name: str) -> str:
    """Make a string safe for use in file names."""
    return re.sub(r"[^\w]+", "_", name).strip("_").lower()


class DataValidator:
    """
    Generalised data profiling and validation tool.

    Parameters
    ----------
    source_path : str or Path
        Path to a Parquet file, Delta Lake directory, or CSV file.
    output_dir : str or Path
        Root directory for validation output. Reports land in
        ``{output_dir}/validation/``.
    id_columns : list of str, optional
        Column(s) that form the logical primary key for ID-duplicate checks.
    string_delimiter : str
        Token delimiter for string-component frequency analysis. Default ``" "``.
    max_categories : int
        Max distinct values before a categorical column is flagged as
        high-cardinality and skipped in frequency tables. Default 500.
    n_histogram_bins : int
        Number of histogram bins for numeric distributions. Default 20.
    memory_limit : str, optional
        DuckDB memory limit, e.g. ``"4GB"``. Defaults to DuckDB's own heuristic.
    threads : int, optional
        DuckDB thread count. Defaults to DuckDB's own heuristic.
    """

    def __init__(
        self,
        source_path: Union[str, Path],
        output_dir: Union[str, Path] = ".",
        id_columns: Optional[List[str]] = None,
        string_delimiter: str = " ",
        max_categories: int = 500,
        n_histogram_bins: int = 20,
        memory_limit: Optional[str] = None,
        threads: Optional[int] = None,
    ):
        self.source_path = Path(source_path)
        self.output_dir = Path(output_dir)
        self.id_columns = id_columns or []
        self.string_delimiter = string_delimiter
        self.max_categories = max_categories
        self.n_histogram_bins = n_histogram_bins

        self._validation_dir = self.output_dir / "validation"
        self._validation_dir.mkdir(parents=True, exist_ok=True)

        self._source_stem = _sanitize(self.source_path.stem)

        # DuckDB setup
        self._con = duckdb.connect()
        if memory_limit:
            self._con.execute(f"SET memory_limit='{memory_limit}'")
        if threads:
            self._con.execute(f"SET threads={threads}")

        self._register_source()

    # ------------------------------------------------------------------
    # Source registration
    # ------------------------------------------------------------------

    def _register_source(self):
        """Register the input file as a DuckDB view called 'src'."""
        p = self.source_path
        suffix = p.suffix.lower()

        if suffix == ".csv":
            self._con.execute(
                f"CREATE OR REPLACE VIEW src AS SELECT * FROM read_csv_auto('{p}')"
            )
        elif suffix == ".parquet":
            self._con.execute(
                f"CREATE OR REPLACE VIEW src AS SELECT * FROM read_parquet('{p}')"
            )
        elif suffix == "" or p.is_dir():
            # Delta Lake directory — requires delta extension
            try:
                self._con.execute("INSTALL delta; LOAD delta;")
                self._con.execute(
                    f"CREATE OR REPLACE VIEW src AS SELECT * FROM delta_scan('{p}')"
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Could not read Delta Lake at '{p}'. "
                    "Ensure the duckdb-delta extension is available."
                ) from exc
        else:
            raise ValueError(
                f"Unsupported file type: '{suffix}'. "
                "Supported: .parquet, .csv, or a Delta Lake directory."
            )
        log.info("Registered source: %s", p)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save(self, df: pd.DataFrame, report_name: str) -> Path:
        """Enforce the long/skinny schema and write to parquet."""
        # Ensure all canonical columns are present
        for col in OUTPUT_COLUMNS:
            if col not in df.columns:
                df[col] = None
        df = df[OUTPUT_COLUMNS].copy()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        fname = f"{report_name}__{self._source_stem}.parquet"
        out_path = self._validation_dir / fname
        df.to_parquet(out_path, index=False)
        log.info("Saved %s (%d rows) → %s", report_name, len(df), out_path)
        return out_path

    # ------------------------------------------------------------------
    # Public API — individual reports
    # ------------------------------------------------------------------

    def run_schema(self) -> pd.DataFrame:
        """Profile column names and types."""
        df = report_schema(self._con, "src", self.source_path.name)
        self._save(df, "schema")
        return df

    def run_true_duplicates(self) -> pd.DataFrame:
        """Detect fully duplicate rows."""
        df = report_true_duplicates(self._con, "src", self.source_path.name)
        self._save(df, "true_duplicates")
        return df

    def run_id_duplicates(self, id_columns: Optional[List[str]] = None) -> pd.DataFrame:
        """Detect rows with duplicate ID key(s)."""
        cols = id_columns or self.id_columns
        if not cols:
            log.warning("run_id_duplicates: no id_columns specified — skipping.")
            return pd.DataFrame(columns=OUTPUT_COLUMNS)
        df = report_id_duplicates(self._con, "src", self.source_path.name, cols)
        self._save(df, "id_duplicates")
        return df

    def run_univariate(self) -> pd.DataFrame:
        """Univariate statistics and histograms for numeric columns."""
        df = report_univariate(
            self._con, "src", self.source_path.name, self.n_histogram_bins
        )
        if not df.empty:
            self._save(df, "univariate")
        return df

    def run_frequency(self) -> pd.DataFrame:
        """Frequency distributions for categorical columns."""
        df = report_frequency(
            self._con, "src", self.source_path.name, self.max_categories
        )
        if not df.empty:
            self._save(df, "frequency")
        return df

    def run_string_components(self, delimiter: Optional[str] = None) -> pd.DataFrame:
        """Token-level frequency table for string columns."""
        delim = delimiter or self.string_delimiter
        df = report_string_components(
            self._con, "src", self.source_path.name, delim
        )
        if not df.empty:
            self._save(df, "string_components")
        return df

    # ------------------------------------------------------------------
    # User-defined tabulations
    # ------------------------------------------------------------------

    def run_tabulation(self, spec: TabulationSpec) -> pd.DataFrame:
        """
        Execute a user-defined cross-tabulation.

        The result is stored as:
            ``{stat_name}__{spec.label}__{source_stem}.parquet``

        One parquet file is written per StatSpec so files can be independently
        stacked in Power BI by metric name.

        Returns a combined DataFrame of all stats.
        """
        dims_sql = ", ".join(f'"{d}"' for d in spec.dimensions)
        where_clause = f"WHERE {spec.filters}" if spec.filters else ""

        all_rows = []

        for stat in spec.stats:
            q = f"""
                SELECT
                    {dims_sql},
                    {stat.expression} AS _stat_value
                FROM src
                {where_clause}
                GROUP BY {dims_sql}
                ORDER BY {dims_sql}
            """
            try:
                result = self._con.execute(q).df()
            except Exception as exc:
                log.error(
                    "Tabulation '%s' / stat '%s' failed: %s", spec.label, stat.name, exc
                )
                raise

            rows = []
            for _, row in result.iterrows():
                # Build the dimension_value as a composite key string
                dim_parts = [f"{d}={row[d]}" for d in spec.dimensions]
                dim_value = "|".join(str(p) for p in dim_parts)
                rows.append({
                    "source_file": self.source_path.name,
                    "report_type": "crosstab",
                    "metric": stat.name,
                    "dimension": spec.label,
                    "dimension_value": dim_value,
                    "value": row["_stat_value"],
                })

            df_stat = pd.DataFrame(rows)
            all_rows.append(df_stat)

            # One parquet per stat for independent Power BI stacking
            report_name = f"{_sanitize(stat.name)}__{_sanitize(spec.label)}"
            self._save(df_stat, report_name)

        return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()

    def run_tabulations(self, specs: List[TabulationSpec]) -> pd.DataFrame:
        """Run multiple TabulationSpecs and return combined results."""
        frames = [self.run_tabulation(s) for s in specs]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # ------------------------------------------------------------------
    # Full validation suite
    # ------------------------------------------------------------------

    def run_all(
        self,
        tabulation_specs: Optional[List[TabulationSpec]] = None,
        string_delimiter: Optional[str] = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Run the full validation suite and return a dict of report DataFrames.

        Parameters
        ----------
        tabulation_specs : list of TabulationSpec, optional
            User-defined cross-tabulations to include.
        string_delimiter : str, optional
            Override the instance-level string delimiter for this run.

        Returns
        -------
        dict mapping report name → DataFrame
        """
        results = {}

        log.info("=== Running schema report ===")
        results["schema"] = self.run_schema()

        log.info("=== Running true-duplicate report ===")
        results["true_duplicates"] = self.run_true_duplicates()

        if self.id_columns:
            log.info("=== Running ID-duplicate report ===")
            results["id_duplicates"] = self.run_id_duplicates()

        log.info("=== Running univariate report ===")
        results["univariate"] = self.run_univariate()

        log.info("=== Running frequency report ===")
        results["frequency"] = self.run_frequency()

        log.info("=== Running string-component report ===")
        results["string_components"] = self.run_string_components(string_delimiter)

        if tabulation_specs:
            log.info("=== Running %d user tabulation(s) ===", len(tabulation_specs))
            results["tabulations"] = self.run_tabulations(tabulation_specs)

        log.info("=== Validation complete. Output: %s ===", self._validation_dir)
        return results

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def list_outputs(self) -> List[Path]:
        """Return all parquet files written to the validation directory."""
        return sorted(self._validation_dir.glob("*.parquet"))

    def preview(self, n: int = 5) -> pd.DataFrame:
        """Quick look at the source data."""
        return self._con.execute(f"SELECT * FROM src LIMIT {n}").df()

    def sql(self, query: str) -> pd.DataFrame:
        """Run arbitrary SQL against the registered 'src' view."""
        return self._con.execute(query).df()

    def close(self):
        self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
