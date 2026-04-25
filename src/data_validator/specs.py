"""
User-defined specification objects for cross-tabulations and statistics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class StatSpec:
    """
    Defines a single statistic to compute in a tabulation.

    Parameters
    ----------
    name : str
        Label for this statistic in output (used in 'metric' column and file naming).
    expression : str
        DuckDB SQL aggregate expression evaluated in the context of the tabulation query.
        The expression can reference any column in the source table.

    Examples
    --------
    StatSpec("count", "COUNT(*)")
    StatSpec("total_value", "SUM(assessed_value)")
    StatSpec("avg_value", "AVG(assessed_value)")
    StatSpec("median_value", "MEDIAN(assessed_value)")
    StatSpec("pct_vacant", "100.0 * SUM(CASE WHEN status = 'vacant' THEN 1 ELSE 0 END) / COUNT(*)")
    """
    name: str
    expression: str

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> StatSpec:
        """
        Construct from a plain dict.

        Expected keys: ``name``, ``expression``.

        Parameters
        ----------
        d : dict
            e.g. ``{"name": "dwelling_count", "expression": "COUNT(*)"}``
        """
        missing = {"name", "expression"} - d.keys()
        if missing:
            raise ValueError(f"StatSpec dict missing required keys: {missing}")
        return cls(name=d["name"], expression=d["expression"])


@dataclass
class TabulationSpec:
    """
    Defines a full user-specified cross-tabulation.

    Parameters
    ----------
    dimensions : List[str]
        Ordered list of column names to group by (e.g. ["year", "province", "housing_type"]).
    stats : List[StatSpec]
        One or more statistics to compute within each group.
    filters : Optional[str]
        Optional SQL WHERE clause fragment applied before aggregation
        (e.g. "year >= 2018 AND province != 'XX'").
    label : Optional[str]
        Short label used in output file naming. Defaults to dimensions joined by '_'.

    Examples
    --------
    TabulationSpec(
        dimensions=["year", "province", "cma_ca", "housing_type"],
        stats=[
            StatSpec("dwelling_count", "SUM(dwelling_count)"),
            StatSpec("avg_value", "AVG(assessed_value)"),
        ],
        label="housing_summary"
    )
    """
    dimensions: List[str]
    stats: List[StatSpec]
    filters: Optional[str] = None
    label: Optional[str] = None

    def __post_init__(self):
        if not self.dimensions:
            raise ValueError("TabulationSpec must have at least one dimension.")
        if not self.stats:
            raise ValueError("TabulationSpec must have at least one StatSpec.")
        if self.label is None:
            self.label = "_".join(self.dimensions)

    # ------------------------------------------------------------------
    # from_dict
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TabulationSpec:
        """
        Construct a single TabulationSpec from a plain dict.

        Expected shape::

            {
                "label": "year_prov_housing",          # optional
                "dimensions": ["year", "province", "housing_type"],
                "filters": "year >= 2018",             # optional
                "stats": [
                    {"name": "dwelling_count", "expression": "COUNT(*)"},
                    {"name": "avg_value",      "expression": "AVG(assessed_value)"}
                ]
            }

        Parameters
        ----------
        d : dict
            Dictionary matching the shape above.
        """
        missing = {"dimensions", "stats"} - d.keys()
        if missing:
            raise ValueError(f"TabulationSpec dict missing required keys: {missing}")

        stats = [StatSpec.from_dict(s) for s in d["stats"]]
        return cls(
            dimensions=list(d["dimensions"]),
            stats=stats,
            filters=d.get("filters"),
            label=d.get("label"),
        )

    @classmethod
    def from_dict_list(cls, items: List[Dict[str, Any]]) -> List[TabulationSpec]:
        """
        Construct a list of TabulationSpecs from a list of dicts.

        Convenience wrapper around :meth:`from_dict` for bulk loading.

        Parameters
        ----------
        items : list of dict
            Each element is passed to :meth:`from_dict`.
        """
        return [cls.from_dict(item) for item in items]

    # ------------------------------------------------------------------
    # from_yaml
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(
        cls,
        source: Union[str, Path],
        key: str = "tabulations",
    ) -> List[TabulationSpec]:
        """
        Load a list of TabulationSpecs from a YAML file.

        The YAML file must contain a top-level key (default ``"tabulations"``)
        whose value is a list of tabulation dicts.

        Parameters
        ----------
        source : str or Path
            Path to the YAML file.
        key : str
            Top-level key that holds the list of tabulation dicts.
            Default: ``"tabulations"``.

        Returns
        -------
        list of TabulationSpec

        Example YAML
        ------------
        .. code-block:: yaml

            tabulations:
              - label: year_prov_housing
                dimensions: [year, province, housing_type]
                filters: "year >= 2018"
                stats:
                  - name: dwelling_count
                    expression: "COUNT(*)"
                  - name: avg_assessed_value
                    expression: "AVG(assessed_value)"

              - label: vacancy_by_tenure
                dimensions: [province, tenure]
                stats:
                  - name: vacancy_rate_pct
                    expression: "100.0 * SUM(is_vacant) / NULLIF(COUNT(*), 0)"
        """
        try:
            import yaml  # PyYAML — soft dependency
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required for from_yaml(). "
                "Install it with: pip install pyyaml"
            ) from exc

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"YAML file not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        if key not in data:
            available = list(data.keys())
            raise KeyError(
                f"Key '{key}' not found in {path.name}. "
                f"Available keys: {available}"
            )

        return cls.from_dict_list(data[key])

    # ------------------------------------------------------------------
    # from_json
    # ------------------------------------------------------------------

    @classmethod
    def from_json(
        cls,
        source: Union[str, Path],
        key: str = "tabulations",
    ) -> List[TabulationSpec]:
        """
        Load a list of TabulationSpecs from a JSON file.

        Parameters
        ----------
        source : str or Path
            Path to the JSON file.
        key : str
            Top-level key that holds the list of tabulation dicts.
            Default: ``"tabulations"``.

        Returns
        -------
        list of TabulationSpec

        Example JSON
        ------------
        .. code-block:: json

            {
              "tabulations": [
                {
                  "label": "year_prov_housing",
                  "dimensions": ["year", "province", "housing_type"],
                  "filters": "year >= 2018",
                  "stats": [
                    {"name": "dwelling_count", "expression": "COUNT(*)"},
                    {"name": "avg_value",      "expression": "AVG(assessed_value)"}
                  ]
                }
              ]
            }
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        if key not in data:
            available = list(data.keys())
            raise KeyError(
                f"Key '{key}' not found in {path.name}. "
                f"Available keys: {available}"
            )

        return cls.from_dict_list(data[key])
