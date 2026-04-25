"""
Basic test suite for data_validator.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data_validator import DataValidator, TabulationSpec, StatSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_parquet(path: Path, n: int = 1000):
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT
                i::INTEGER AS id,
                (i % 5)::INTEGER AS group_id,
                CASE (i % 3) WHEN 0 THEN 'alpha' WHEN 1 THEN 'beta' ELSE 'gamma' END AS category,
                (RANDOM() * 100)::DOUBLE AS score,
                CASE WHEN i % 50 = 0 THEN NULL ELSE
                    'token_' || (i % 10)::VARCHAR || ' extra'
                END AS label,
                (2020 + i % 4)::INTEGER AS year
            FROM range({n}) t(i)
        ) TO '{path}' (FORMAT PARQUET)
    """)
    con.close()


@pytest.fixture
def sample_parquet(tmp_path):
    p = tmp_path / "sample.parquet"
    _make_parquet(p)
    return p


@pytest.fixture
def validator(sample_parquet, tmp_path):
    v = DataValidator(
        source_path=sample_parquet,
        output_dir=tmp_path / "out",
        id_columns=["id"],
    )
    yield v
    v.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSchema:
    def test_returns_dataframe(self, validator):
        df = validator.run_schema()
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_contains_row_count(self, validator):
        df = validator.run_schema()
        row = df[df["metric"] == "row_count"]
        assert not row.empty
        assert row["value"].iloc[0] == 1000

    def test_output_file_exists(self, validator):
        validator.run_schema()
        outputs = validator.list_outputs()
        names = [p.name for p in outputs]
        assert any("schema" in n for n in names)


class TestDuplicates:
    def test_true_duplicates_columns(self, validator):
        df = validator.run_true_duplicates()
        assert set(df["metric"]).issuperset({"total_rows", "duplicate_rows", "unique_rows"})

    def test_id_duplicates_no_dupes(self, validator):
        df = validator.run_id_duplicates()
        dup_row = df[df["metric"] == "duplicate_rows"]
        assert dup_row["value"].iloc[0] == 0


class TestUnivariate:
    def test_has_expected_metrics(self, validator):
        df = validator.run_univariate()
        metrics = set(df["metric"].unique())
        assert {"mean", "median", "min", "max", "stddev"}.issubset(metrics)

    def test_score_column_present(self, validator):
        df = validator.run_univariate()
        assert "score" in df["dimension"].values


class TestFrequency:
    def test_category_present(self, validator):
        df = validator.run_frequency()
        assert "category" in df["dimension"].values

    def test_pct_and_count(self, validator):
        df = validator.run_frequency()
        metrics = set(df["metric"].unique())
        assert "count" in metrics and "pct" in metrics


class TestStringComponents:
    def test_tokens_extracted(self, validator):
        df = validator.run_string_components()
        assert not df.empty
        assert "label" in df["dimension"].values

    def test_known_token(self, validator):
        df = validator.run_string_components()
        label_df = df[df["dimension"] == "label"]
        vals = label_df["dimension_value"].str.lower().tolist()
        assert any("token_" in v for v in vals)
        assert any(v == "extra" for v in vals)


class TestTabulations:
    def test_basic_crosstab(self, validator):
        spec = TabulationSpec(
            dimensions=["year", "category"],
            stats=[
                StatSpec("row_count", "COUNT(*)"),
                StatSpec("avg_score", "AVG(score)"),
            ],
        )
        df = validator.run_tabulation(spec)
        assert not df.empty
        assert set(df["metric"].unique()) == {"row_count", "avg_score"}

    def test_output_files_named_correctly(self, validator):
        spec = TabulationSpec(
            dimensions=["year"],
            stats=[StatSpec("total", "COUNT(*)")],
            label="yearly_summary",
        )
        validator.run_tabulation(spec)
        outputs = [p.name for p in validator.list_outputs()]
        assert any("total__yearly_summary" in n for n in outputs)

    def test_filter_applied(self, validator):
        spec_all = TabulationSpec(
            dimensions=["year"],
            stats=[StatSpec("n", "COUNT(*)")],
            label="all_years",
        )
        spec_filtered = TabulationSpec(
            dimensions=["year"],
            stats=[StatSpec("n", "COUNT(*)")],
            filters="year = 2020",
            label="year_2020",
        )
        df_all = validator.run_tabulation(spec_all)
        df_filt = validator.run_tabulation(spec_filtered)
        assert df_all["value"].sum() > df_filt["value"].sum()

    def test_long_skinny_schema(self, validator):
        spec = TabulationSpec(
            dimensions=["category"],
            stats=[StatSpec("count", "COUNT(*)")],
        )
        df = validator.run_tabulation(spec)
        expected_cols = {"source_file", "report_type", "metric",
                         "dimension", "dimension_value", "value"}
        assert expected_cols.issubset(set(df.columns))


class TestRunAll:
    def test_run_all_returns_dict(self, validator):
        result = validator.run_all()
        assert isinstance(result, dict)
        assert "schema" in result
        assert "univariate" in result

    def test_run_all_with_tabulations(self, validator):
        specs = [
            TabulationSpec(
                dimensions=["year"],
                stats=[StatSpec("n", "COUNT(*)")],
            )
        ]
        result = validator.run_all(tabulation_specs=specs)
        assert "tabulations" in result

    def test_output_files_all_readable(self, validator):
        validator.run_all()
        for p in validator.list_outputs():
            df = pd.read_parquet(p)
            assert not df.empty


class TestSpecConstructors:
    """Tests for TabulationSpec.from_dict / from_yaml / from_json."""

    SPEC_DICT = {
        "label": "test_tab",
        "dimensions": ["year", "category"],
        "filters": "year >= 2020",
        "stats": [
            {"name": "count", "expression": "COUNT(*)"},
            {"name": "avg_score", "expression": "AVG(score)"},
        ],
    }

    def test_from_dict_basic(self):
        spec = TabulationSpec.from_dict(self.SPEC_DICT)
        assert spec.label == "test_tab"
        assert spec.dimensions == ["year", "category"]
        assert spec.filters == "year >= 2020"
        assert len(spec.stats) == 2
        assert spec.stats[0].name == "count"

    def test_from_dict_label_defaults(self):
        d = {k: v for k, v in self.SPEC_DICT.items() if k != "label"}
        spec = TabulationSpec.from_dict(d)
        assert spec.label == "year_category"

    def test_from_dict_missing_dimensions_raises(self):
        with pytest.raises(ValueError, match="dimensions"):
            TabulationSpec.from_dict({"stats": [{"name": "n", "expression": "COUNT(*)"}]})

    def test_from_dict_missing_stats_raises(self):
        with pytest.raises(ValueError, match="stats"):
            TabulationSpec.from_dict({"dimensions": ["year"]})

    def test_from_dict_list(self):
        specs = TabulationSpec.from_dict_list([self.SPEC_DICT, self.SPEC_DICT])
        assert len(specs) == 2

    def test_stat_spec_from_dict(self):
        s = StatSpec.from_dict({"name": "total", "expression": "SUM(score)"})
        assert s.name == "total"

    def test_stat_spec_missing_key_raises(self):
        with pytest.raises(ValueError, match="expression"):
            StatSpec.from_dict({"name": "total"})

    def test_from_json(self, tmp_path):
        import json
        data = {"tabulations": [{
            "label": "json_tab",
            "dimensions": ["year"],
            "stats": [{"name": "n", "expression": "COUNT(*)"}],
        }]}
        json_file = tmp_path / "tabs.json"
        json_file.write_text(json.dumps(data))
        specs = TabulationSpec.from_json(json_file)
        assert len(specs) == 1
        assert specs[0].label == "json_tab"

    def test_from_json_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            TabulationSpec.from_json(tmp_path / "nonexistent.json")

    def test_from_json_wrong_key_raises(self, tmp_path):
        import json
        json_file = tmp_path / "tabs.json"
        json_file.write_text(json.dumps({"other": []}))
        with pytest.raises(KeyError, match="tabulations"):
            TabulationSpec.from_json(json_file)

    def test_from_json_roundtrip_runs_tabulation(self, validator, tmp_path):
        import json
        data = {"tabulations": [{
            "label": "group_tab",
            "dimensions": ["year", "category"],
            "stats": [
                {"name": "n", "expression": "COUNT(*)"},
                {"name": "avg_score", "expression": "AVG(score)"},
            ],
        }]}
        json_file = tmp_path / "tabs.json"
        json_file.write_text(json.dumps(data))
        specs = TabulationSpec.from_json(json_file)
        df = validator.run_tabulations(specs)
        assert not df.empty
        assert set(df["metric"].unique()) == {"n", "avg_score"}


class TestContextManager:
    def test_context_manager(self, sample_parquet, tmp_path):
        with DataValidator(sample_parquet, tmp_path / "ctx_out") as v:
            df = v.run_schema()
        assert not df.empty


class TestOutputSchema:
    def test_all_outputs_have_canonical_columns(self, validator):
        validator.run_all()
        required = {"source_file", "report_type", "metric",
                    "dimension", "dimension_value", "value"}
        for p in validator.list_outputs():
            df = pd.read_parquet(p)
            assert required.issubset(set(df.columns)), f"Missing columns in {p.name}"

    def test_value_column_is_numeric(self, validator):
        validator.run_all()
        for p in validator.list_outputs():
            df = pd.read_parquet(p)
            numeric_vals = pd.to_numeric(df["value"], errors="coerce")
            # Non-null values should all be numeric
            non_null = df["value"].dropna()
            non_null_converted = numeric_vals.dropna()
            assert len(non_null) == len(non_null_converted), \
                f"Non-numeric values in 'value' column: {p.name}"
