"""
examples/unpack_crosstabs.py
----------------------------
Demonstrates how to unpack the encoded dimension_value column from
DataValidator crosstab outputs back into analysis-ready DataFrames.

Crosstab files are now written into labelled subfolders:
    validation/
        year_prov_housing/
            dwelling_count__housing_survey.parquet
            avg_assessed_value__housing_survey.parquet
        year_cmaca_tenure/
            dwelling_count__housing_survey.parquet
            ...

Run from the repo root (after running housing_validation.py first):
    uv run python examples/unpack_crosstabs.py
"""
from pathlib import Path
from data_validator import unpack_wide, unpack_long, unpack_folder, save_unpacked, save_dataframe

VALIDATION_DIR = Path("examples/output/validation")

# ---------------------------------------------------------------------------
# 1. Unpack a single file from a specific breakdown folder — WIDE format
# ---------------------------------------------------------------------------
print("\n=== WIDE: single file ===")
df = unpack_wide(
    VALIDATION_DIR / "year_prov_housing" / "dwelling_count__housing_survey.parquet"
)
print(df.head(10).to_string(index=False))
print(f"Shape: {df.shape}  Columns: {df.columns.tolist()}")

# ---------------------------------------------------------------------------
# 2. Unpack a single file — LONG format
# ---------------------------------------------------------------------------
print("\n=== LONG: single file ===")
df = unpack_long(
    VALIDATION_DIR / "year_prov_housing" / "dwelling_count__housing_survey.parquet"
)
print(df.head(10).to_string(index=False))
print(f"Shape: {df.shape}  Columns: {df.columns.tolist()}")

# ---------------------------------------------------------------------------
# 3. Unpack a specific breakdown folder — all stats, wide format
#    All files in the folder share the same dimensions so wide stacking works.
# ---------------------------------------------------------------------------
print("\n=== WIDE: all stats in year_prov_housing breakdown ===")
df = unpack_folder(VALIDATION_DIR, label="year_prov_housing", mode="wide")
print(df.head(10).to_string(index=False))
print(f"\nShape: {df.shape}")
print(f"Metrics: {sorted(df['metric'].unique().tolist())}")

# ---------------------------------------------------------------------------
# 4. Stack ALL breakdowns — LONG format
#    Different breakdowns have different dimensions, so long is the only
#    schema that is consistent across all of them.
# ---------------------------------------------------------------------------
print("\n=== LONG: all breakdowns stacked ===")
df = unpack_folder(VALIDATION_DIR, mode="long")
print(df.head(10).to_string(index=False))
print(f"\nTotal rows: {len(df):,}")
print(f"Labels:   {sorted(df['label'].unique().tolist())}")
print(f"Metrics:  {sorted(df['metric'].unique().tolist())}")
print(f"Dim keys: {sorted(df['dim_key'].unique().tolist())}")

# ---------------------------------------------------------------------------
# 5. Filter to a single metric across all breakdowns
# ---------------------------------------------------------------------------
print("\n=== LONG: dwelling_count only, all breakdowns ===")
df = unpack_folder(VALIDATION_DIR, mode="long", filter_metric="dwelling_count")
print(df.head(10).to_string(index=False))
print(f"Shape: {df.shape}")

# ---------------------------------------------------------------------------
# 6. Write combined unpacked table — all breakdowns — for Power BI
# ---------------------------------------------------------------------------
out = save_unpacked(
    VALIDATION_DIR,
    "examples/output/crosstabs_all_long.parquet",
    mode="long",
)
print(f"\n✓ All breakdowns (long): {out}")

# ---------------------------------------------------------------------------
# 7. Write one specific breakdown — wide — for direct analysis
# ---------------------------------------------------------------------------
out = save_unpacked(
    VALIDATION_DIR,
    "examples/output/year_prov_housing_wide.parquet",
    label="year_prov_housing",
    mode="wide",
)
print(f"✓ year_prov_housing (wide): {out}")

# ---------------------------------------------------------------------------
# 8. save_dataframe — write any in-memory DataFrame safely
# ---------------------------------------------------------------------------
df = unpack_wide(
    VALIDATION_DIR / "year_prov_housing" / "avg_assessed_value__housing_survey.parquet"
)
out = save_dataframe(df, "examples/output/avg_value_wide.parquet")
print(f"✓ avg_assessed_value (wide, single file): {out}")
