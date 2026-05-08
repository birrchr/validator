"""
examples/housing_validation.py
-------------------------------
Full worked example demonstrating DataValidator with user-defined
cross-tabulations against a hypothetical housing survey dataset.

Run from the repo root:
    uv run python examples/housing_validation.py
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

from data_validator import DataValidator, TabulationSpec, StatSpec

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# 1. Generate a synthetic housing dataset for demonstration
# ---------------------------------------------------------------------------


def make_sample_data(path: Path, n: int = 50_000):
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT
                (ROW_NUMBER() OVER ())::INTEGER                     AS record_id,
                (2016 + (RANDOM() * 7)::INTEGER)::INTEGER           AS survey_year,
                CASE ((RANDOM()*12)::INTEGER % 13)
                    WHEN 0  THEN 'NL' WHEN 1  THEN 'PE' WHEN 2  THEN 'NS'
                    WHEN 3  THEN 'NB' WHEN 4  THEN 'QC' WHEN 5  THEN 'ON'
                    WHEN 6  THEN 'MB' WHEN 7  THEN 'SK' WHEN 8  THEN 'AB'
                    WHEN 9  THEN 'BC' WHEN 10 THEN 'YT' WHEN 11 THEN 'NT'
                    ELSE 'NU'
                END                                                  AS province,
                CASE ((RANDOM()*4)::INTEGER % 5)
                    WHEN 0 THEN 'CMA' WHEN 1 THEN 'CA'
                    WHEN 2 THEN 'MIZ' WHEN 3 THEN 'SZ'
                    ELSE 'RU'
                END                                                  AS cma_ca_type,
                CASE ((RANDOM()*5)::INTEGER % 6)
                    WHEN 0 THEN 'Single detached'
                    WHEN 1 THEN 'Semi-detached'
                    WHEN 2 THEN 'Row house'
                    WHEN 3 THEN 'Apartment <5'
                    WHEN 4 THEN 'Apartment 5+'
                    ELSE 'Other'
                END                                                  AS housing_type,
                CASE ((RANDOM()*3)::INTEGER % 4)
                    WHEN 0 THEN 'Owned'
                    WHEN 1 THEN 'Rented'
                    WHEN 2 THEN 'Band housing'
                    ELSE 'Unknown'
                END                                                  AS tenure,
                (100000 + (RANDOM() * 900000))::INTEGER              AS assessed_value,
                (1 + (RANDOM() * 8)::INTEGER)::INTEGER               AS n_rooms,
                (RANDOM() * 100)::DOUBLE                             AS lot_size_ha,
                CASE WHEN RANDOM() < 0.03 THEN NULL ELSE
                    'DWELLING ' || UPPER(MD5(RANDOM()::VARCHAR)[:6])
                END                                                  AS unit_identifier,
                CASE WHEN RANDOM() < 0.01 THEN 1 ELSE 0 END         AS is_vacant
            FROM range({n})
        ) TO '{path}' (FORMAT PARQUET)
    """)
    con.close()
    print(f"Sample data written: {path} ({n:,} rows)")


# ---------------------------------------------------------------------------
# 2. Run validation
# ---------------------------------------------------------------------------


def main():
    data_path = Path("examples/housing_survey.parquet")
    output_dir = Path("examples/output")

    make_sample_data(data_path)

    # -- User-defined tabulations -------------------------------------------
    tabulations = [
        # Classic year × province × housing type dwelling count
        TabulationSpec(
            dimensions=["survey_year", "province", "housing_type"],
            stats=[
                StatSpec("dwelling_count", "COUNT(*)"),
                StatSpec("avg_assessed_value", "AVG(assessed_value)"),
                StatSpec("median_assessed_value", "MEDIAN(assessed_value)"),
            ],
            label="year_prov_housing",
        ),
        # CMA/CA type breakdown with vacancy rate
        TabulationSpec(
            dimensions=["survey_year", "cma_ca_type", "tenure"],
            stats=[
                StatSpec("dwelling_count", "COUNT(*)"),
                StatSpec("vacancy_rate_pct", "100.0 * SUM(is_vacant) / COUNT(*)"),
                StatSpec("avg_rooms", "AVG(n_rooms)"),
            ],
            label="year_cmaca_tenure",
        ),
        # Province × tenure — filtered to owned dwellings only
        TabulationSpec(
            dimensions=["province", "housing_type"],
            stats=[
                StatSpec("total_assessed_value", "SUM(assessed_value)"),
                StatSpec(
                    "p90_assessed_value",
                    "PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY assessed_value)",
                ),
                StatSpec(
                    "p50_assessed_value",
                    "PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY assessed_value)",
                ),
            ],
            filters="tenure = 'Owned'",
            label="owned_prov_housing_value",
        ),
    ]

    with DataValidator(
        source_path=data_path,
        output_dir=output_dir,
        id_columns=["record_id"],
        memory_limit="2GB",
        string_delimiter=" ",
    ) as v:
        results = v.run_all(tabulation_specs=tabulations)
        outputs = v.list_outputs()

    print(f"\n{'=' * 60}")
    print(f"  {len(outputs)} report files written to: {output_dir}/validation/")
    print(f"{'=' * 60}")
    for p in outputs:
        rows = pd.read_parquet(p).shape[0]
        print(f"  {p.name:<60}  ({rows:>7,} rows)")

    # Preview one report
    print("\n--- Sample univariate output ---")
    uni = results["univariate"]
    print(uni[uni["dimension"] == "assessed_value"].to_string(index=False))

    print("\n--- Sample crosstab output (first 10 rows) ---")
    tabs = results["tabulations"]
    print(tabs.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
