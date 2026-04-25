"""
CLI entry point for data_validator.

Usage
-----
    python -m data_validator.cli path/to/file.parquet --output-dir ./reports --id-cols id

Or after installation:
    data-validate path/to/file.parquet --output-dir ./reports --id-cols record_id
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .validator import DataValidator


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="data-validate",
        description="DuckDB-powered data validation and profiling tool.",
    )
    p.add_argument("source", help="Path to a Parquet, CSV, or Delta Lake directory.")
    p.add_argument(
        "--output-dir", "-o", default=".",
        help="Root output directory. Reports land in {output_dir}/validation/. Default: '.'",
    )
    p.add_argument(
        "--id-cols", nargs="+", default=[],
        metavar="COL",
        help="Column(s) forming the logical primary key for ID-duplicate checks.",
    )
    p.add_argument(
        "--memory-limit", default=None,
        help="DuckDB memory limit e.g. '8GB'. Default: DuckDB heuristic.",
    )
    p.add_argument(
        "--threads", type=int, default=None,
        help="DuckDB thread count. Default: DuckDB heuristic.",
    )
    p.add_argument(
        "--string-delimiter", default=" ",
        help="Delimiter for string-component tokenisation. Default: space.",
    )
    p.add_argument(
        "--max-categories", type=int, default=500,
        help="Max distinct values before a categorical column is skipped. Default: 500.",
    )
    p.add_argument(
        "--histogram-bins", type=int, default=20,
        help="Number of histogram bins for numeric columns. Default: 20.",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity. Default: INFO.",
    )
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    source = Path(args.source)
    if not source.exists():
        print(f"ERROR: source path does not exist: {source}", file=sys.stderr)
        sys.exit(1)

    with DataValidator(
        source_path=source,
        output_dir=args.output_dir,
        id_columns=args.id_cols,
        string_delimiter=args.string_delimiter,
        max_categories=args.max_categories,
        n_histogram_bins=args.histogram_bins,
        memory_limit=args.memory_limit,
        threads=args.threads,
    ) as v:
        results = v.run_all()
        outputs = v.list_outputs()

    print(f"\n✓ Validation complete. {len(outputs)} report(s) written:")
    for p in outputs:
        print(f"  {p}")


if __name__ == "__main__":
    main()
