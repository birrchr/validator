# data-validator

A data profiling and validation tool built on [DuckDB](https://duckdb.org/). Point it at a Parquet, Delta Lake, or CSV file and it produces a set of standardised reports — schema summaries, duplicate checks, statistical distributions, frequency tables, and your own custom cross-tabulations — all written as Parquet files in a consistent format ready to load into a Power BI dashboard.

---

## Table of Contents

1. [What this tool does](#1-what-this-tool-does)
2. [Before you start](#2-before-you-start)
3. [Getting the code](#3-getting-the-code)
4. [Setting up your environment](#4-setting-up-your-environment)
5. [Running the tool — command line](#5-running-the-tool--command-line)
6. [Running the tool — Python script or notebook](#6-running-the-tool--python-script-or-notebook)
7. [Understanding the output](#7-understanding-the-output)
8. [Reports explained](#8-reports-explained)
9. [Custom cross-tabulations](#9-custom-cross-tabulations)
10. [Loading results into Power BI](#10-loading-results-into-power-bi)
11. [Using in JupyterHub or Microsoft Fabric](#11-using-in-jupyterhub-or-microsoft-fabric)
12. [All options reference](#12-all-options-reference)
13. [For developers](#13-for-developers)
14. [Project structure](#14-project-structure)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. What this tool does

When you receive a new data file, a good first step is to profile it — understand what columns it has, whether there are duplicates, what the value distributions look like, and whether key fields contain the values you expect. Doing this manually with Excel or ad-hoc scripts is slow and inconsistent between analysts.

`data-validator` automates that profiling step. You point it at a file and it produces a standard set of reports, every time, in a format that can be directly loaded into Power BI for visualisation. Reports can also be stacked across multiple files or multiple runs so you can track data quality over time.

---

## 2. Before you start

You need two things installed on your computer.

### Python

Check whether you already have it by opening a terminal (on Windows: search for "Command Prompt" or "PowerShell"; on Mac: open "Terminal") and typing:

```
python --version
```

You should see something like `Python 3.12.3`. Any version 3.9 or higher is fine. If you get an error or a version below 3.9, download and install Python from [python.org/downloads](https://www.python.org/downloads/) — choose the latest stable release and use the default installer options.

### uv

`uv` is the package manager this project uses. A package manager is a tool that downloads and installs the libraries your code depends on, and makes sure everyone working on the project has exactly the same versions. Think of it like an app store for Python code.

Install uv by running one of the following in your terminal:

```bash
# Mac or Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (run in PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installing, **close and reopen your terminal**, then verify it worked:

```bash
uv --version
```

You should see a version number like `uv 0.5.x`.

---

## 3. Getting the code

Clone the repository from GitLab. This downloads a copy of the project to your computer:

```bash
git clone https://your-gitlab/data-validator.git
cd data-validator
```

If you don't have Git, you can instead download a ZIP from the GitLab web interface (look for a **Code** or **Download** button), unzip it, and open your terminal inside that folder.

> **What does `cd data-validator` do?** It changes your terminal's working directory into the project folder. All commands from here on assume you are inside that folder.

---

## 4. Setting up your environment

A **virtual environment** is an isolated copy of Python just for this project. It keeps the packages installed here completely separate from anything else on your machine, so there are no version conflicts. `uv` creates and manages this for you.

Run this once from inside the `data-validator` folder:

```bash
uv sync --extra dev
```

This will:
- Read `pyproject.toml` to find out what packages are needed
- Read `uv.lock` to get the exact pinned versions
- Create a `.venv` folder containing the isolated environment
- Install everything

You'll see output like:

```
Resolved 12 packages in 0.4s
Installed 12 packages in 1.2s
 + data-validator 0.1.0 (editable)
 + duckdb 1.x.x
 + pandas 2.x.x
 ...
```

**You only need to do this once.** If you later pull updated code from GitLab that changes `uv.lock`, run `uv sync --extra dev` again to pick up any new packages.

### Optional extras

The base install supports Parquet and CSV files. For additional support:

```bash
# To read Delta Lake files
uv sync --extra delta

# To define tabulations in YAML config files
uv sync --extra yaml

# Install everything
uv sync --extra all --extra dev
```

---

## 5. Running the tool — command line

The simplest way to use the tool is from the command line. This runs all the standard reports automatically without writing any Python code.

```bash
uv run data-validate path/to/your/file.parquet --output-dir ./reports
```

A fuller example:

```bash
uv run data-validate housing_survey.parquet \
    --output-dir   ./reports   \
    --id-cols      record_id   \
    --memory-limit 8GB         \
    --threads      8
```

> **What is `uv run`?** It runs the command inside the virtual environment you set up in step 4. You don't need to "activate" anything — `uv run` handles that automatically.

When it finishes you'll see:

```
✓ Validation complete. 6 report files written:
  reports/validation/schema__housing_survey.parquet
  reports/validation/true_duplicates__housing_survey.parquet
  reports/validation/id_duplicates__housing_survey.parquet
  reports/validation/univariate__housing_survey.parquet
  reports/validation/frequency__housing_survey.parquet
  reports/validation/string_components__housing_survey.parquet
```

### Command line options

| Option | Default | What it does |
|---|---|---|
| `--output-dir` / `-o` | `.` (current folder) | Where to write reports. A `validation/` subfolder is created inside it. |
| `--id-cols` | _(none)_ | Column name(s) that form the unique identifier for each row. Enables the ID-duplicate report. You can specify multiple: `--id-cols year province id` |
| `--memory-limit` | DuckDB default | Cap on RAM usage, e.g. `4GB`, `16GB`. Important on shared servers. |
| `--threads` | DuckDB default | How many CPU cores to use for processing. |
| `--max-categories` | `500` | Columns with more distinct values than this are skipped in frequency tables. |
| `--histogram-bins` | `20` | Number of bins in the numeric distribution histograms. |
| `--string-delimiter` | `" "` (space) | Character used to split text columns into tokens. Use `_` for underscore-coded fields. |
| `--log-level` | `INFO` | How much to print. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

> **Note:** The command line does not support custom cross-tabulations. For those, use the Python API described in the next section.

---

## 6. Running the tool — Python script or notebook

For custom cross-tabulations, or to run validation as part of a larger pipeline, use the Python API.

Create a file — call it something like `run_validation.py` — with the following content, adapted to your file and column names:

```python
from data_validator import DataValidator, TabulationSpec, StatSpec

# Define custom cross-tabulations (optional — see section 9 for details)
tabulations = [
    TabulationSpec(
        dimensions=["survey_year", "province", "housing_type"],
        stats=[
            StatSpec("dwelling_count",        "COUNT(*)"),
            StatSpec("avg_assessed_value",    "AVG(assessed_value)"),
            StatSpec("median_assessed_value", "MEDIAN(assessed_value)"),
        ],
        label="year_prov_housing",
    ),
]

# Run everything
with DataValidator(
    source_path  = "housing_survey.parquet",
    output_dir   = "./reports",
    id_columns   = ["record_id"],
    memory_limit = "8GB",
) as v:
    results = v.run_all(tabulation_specs=tabulations)
```

Then run it from your terminal:

```bash
uv run python run_validation.py
```

> **What is `with DataValidator(...) as v:`?**
> This is called a context manager. It guarantees that the database connection is properly closed when the block finishes — even if something goes wrong midway through. Always use this `with` pattern when writing scripts.

You can also run reports individually if you only need specific ones:

```python
with DataValidator("data.parquet", output_dir="./reports") as v:
    v.run_schema()
    v.run_univariate()
    v.run_frequency()
```

And you can run arbitrary SQL directly against your file, which is handy for exploration:

```python
with DataValidator("data.parquet") as v:
    df = v.sql("SELECT province, COUNT(*) AS n FROM src GROUP BY 1 ORDER BY 2 DESC")
    print(df)
```

---

## 7. Understanding the output

### Where files are written

All output goes into a `validation/` subfolder inside your `--output-dir`. The naming convention is:

```
{report_name}__{source_filename}.parquet
```

For the built-in reports on a file called `housing_survey.parquet`:

```
reports/
└── validation/
    ├── schema__housing_survey.parquet
    ├── true_duplicates__housing_survey.parquet
    ├── id_duplicates__housing_survey.parquet
    ├── univariate__housing_survey.parquet
    ├── frequency__housing_survey.parquet
    └── string_components__housing_survey.parquet
```

For custom cross-tabulations, **one file is written per statistic**:

```
    ├── dwelling_count__year_prov_housing__housing_survey.parquet
    ├── avg_assessed_value__year_prov_housing__housing_survey.parquet
    └── median_assessed_value__year_prov_housing__housing_survey.parquet
```

### The output table format

Every single output file — regardless of which report it came from — has exactly the same six columns. This is intentional: it means all files can be stacked on top of each other in Power BI without any reshaping or transformation.

| Column | Type | What it contains |
|---|---|---|
| `source_file` | text | Name of the input file (e.g. `housing_survey.parquet`) |
| `report_type` | text | Which report this row belongs to (e.g. `schema`, `univariate`, `frequency`, `crosstab`) |
| `metric` | text | The name of the measurement (e.g. `mean`, `count`, `duplicate_pct`) |
| `dimension` | text | The column name or tabulation label this measurement relates to |
| `dimension_value` | text | The specific value or category (e.g. `Ontario`, `Single detached`) |
| `value` | number | The numeric result |

Here is what a few rows from a univariate report look like:

| source_file | report_type | metric | dimension | dimension_value | value |
|---|---|---|---|---|---|
| housing_survey.parquet | univariate | mean | assessed_value | _(null)_ | 487234.5 |
| housing_survey.parquet | univariate | median | assessed_value | _(null)_ | 412000.0 |
| housing_survey.parquet | univariate | min | assessed_value | _(null)_ | 85000.0 |
| housing_survey.parquet | frequency | count | province | Ontario | 14823 |
| housing_survey.parquet | frequency | pct | province | Ontario | 29.65 |

And from a cross-tabulation:

| source_file | report_type | metric | dimension | dimension_value | value |
|---|---|---|---|---|---|
| housing_survey.parquet | crosstab | dwelling_count | year_prov_housing | year=2021\|province=ON\|housing_type=Single detached | 4521 |
| housing_survey.parquet | crosstab | avg_assessed_value | year_prov_housing | year=2021\|province=ON\|housing_type=Single detached | 612480.3 |

---

## 8. Reports explained

**Schema** checks that the file loaded correctly and lists every column along with its data type. It also records the total row and column count of the dataset — a quick sanity check before going further.

**True duplicates** detects rows where every single column is identical to another row. The detection uses a fast hashing strategy: each row is fingerprinted into a single number, then groups with more than one row are flagged and verified with an exact match. This is much faster than a full multi-column sort on wide tables. The report tells you how many duplicate rows exist and what percentage of the dataset they represent.

**ID duplicates** detects rows that share the same value in your ID column(s) but may differ in other columns — a common and more subtle data quality problem. For example, if `record_id = 1001` appears twice with different values in `assessed_value`, true-duplicate detection would miss it but ID-duplicate detection catches it. Requires `--id-cols` to be set.

**Univariate statistics** computes the following for every numeric column: minimum, maximum, mean, median, standard deviation, variance, 25th percentile, 75th percentile, approximate distinct count, and a histogram showing how values are distributed across bins. Null counts are included.

**Frequency distribution** produces a count and percentage for each distinct value in every categorical column (text, boolean, date). Columns with more than `--max-categories` distinct values are flagged but skipped to avoid enormous output — this guard exists for fields like postal codes or free-text descriptions.

**String components** splits the text in each string column on a delimiter (default: space) and produces a frequency table of the resulting tokens. For a column containing values like `"Single detached house"` and `"Semi-detached house"`, this would produce a table showing how often `Single`, `detached`, `Semi`, `house`, etc. appear. Useful for coded or composite string fields where the parts carry meaning independently.

---

## 9. Custom cross-tabulations

Cross-tabulations let you define exactly what groupings and statistics you want — equivalent to a pivot table or a `GROUP BY` query. You specify which columns to group by (`dimensions`) and what to calculate within each group (`stats`).

### Defining tabulations in Python

```python
from data_validator import TabulationSpec, StatSpec

specs = [
    TabulationSpec(
        # Columns to group by, in order
        dimensions=["survey_year", "province", "cma_ca_type", "housing_type"],

        # Statistics to compute within each group
        stats=[
            StatSpec("dwelling_count",       "COUNT(*)"),
            StatSpec("avg_assessed_value",   "AVG(assessed_value)"),
            StatSpec("total_assessed_value", "SUM(assessed_value)"),
            StatSpec("p90_assessed_value",
                     "PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY assessed_value)"),
        ],

        # Optional: filter rows before grouping (standard SQL WHERE clause)
        filters="survey_year >= 2018",

        # Short name used in output file names
        label="year_prov_cmaca_housing",
    ),

    TabulationSpec(
        dimensions=["province", "tenure"],
        stats=[
            StatSpec("vacancy_rate_pct",
                     "100.0 * SUM(is_vacant) / NULLIF(COUNT(*), 0)"),
        ],
        filters="tenure != 'Unknown'",
        label="vacancy_by_tenure",
    ),
]
```

Pass them to `run_all()`:

```python
with DataValidator("housing_survey.parquet", output_dir="./reports") as v:
    v.run_all(tabulation_specs=specs)
```

### Defining tabulations in a YAML file

If you'd rather keep tabulation definitions in a config file that analysts can edit without touching Python, save a `.yaml` file like this:

```yaml
# tabulations.yaml

tabulations:

  - label: year_prov_housing
    dimensions: [survey_year, province, housing_type]
    filters: "survey_year >= 2018"
    stats:
      - name: dwelling_count
        expression: "COUNT(*)"
      - name: avg_assessed_value
        expression: "AVG(assessed_value)"
      - name: vacancy_rate_pct
        expression: "100.0 * SUM(is_vacant) / NULLIF(COUNT(*), 0)"

  - label: tenure_breakdown
    dimensions: [province, tenure]
    stats:
      - name: count
        expression: "COUNT(*)"
```

Load it in your script:

```python
from data_validator import DataValidator, TabulationSpec

specs = TabulationSpec.from_yaml("tabulations.yaml")

with DataValidator("housing_survey.parquet", output_dir="./reports") as v:
    v.run_all(tabulation_specs=specs)
```

> YAML support requires the `yaml` extra: `uv sync --extra yaml`

### Defining tabulations in a JSON file

JSON works identically — useful when your tabulation config is generated by another system or tool:

```json
{
  "tabulations": [
    {
      "label": "year_prov_housing",
      "dimensions": ["survey_year", "province", "housing_type"],
      "filters": "survey_year >= 2018",
      "stats": [
        {"name": "dwelling_count",     "expression": "COUNT(*)"},
        {"name": "avg_assessed_value", "expression": "AVG(assessed_value)"}
      ]
    }
  ]
}
```

```python
specs = TabulationSpec.from_json("tabulations.json")
```

JSON support uses Python's built-in library — no extra install needed.

### StatSpec expression reference

The `expression` field accepts any standard SQL aggregate expression that DuckDB supports.

| What you want to calculate | Expression |
|---|---|
| Row count | `COUNT(*)` |
| Sum | `SUM(column_name)` |
| Average (mean) | `AVG(column_name)` |
| Median | `MEDIAN(column_name)` |
| Minimum / Maximum | `MIN(column_name)` / `MAX(column_name)` |
| 90th percentile | `PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY column_name)` |
| Standard deviation | `STDDEV_SAMP(column_name)` |
| Percentage meeting a condition | `100.0 * SUM(CASE WHEN status = 'vacant' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)` |
| Approximate distinct count | `APPROX_COUNT_DISTINCT(column_name)` |

> **Tip:** When dividing to compute a percentage, always wrap the denominator in `NULLIF(expr, 0)`. This returns `NULL` instead of crashing when a group has zero rows. For example: `SUM(x) / NULLIF(COUNT(*), 0)`.

---

## 10. Loading results into Power BI

All output files share the same six-column structure, so Power BI can load and stack them automatically.

1. Open Power BI Desktop.
2. **Home → Get Data → Folder**. Navigate to your `validation/` folder and click **Connect**.
3. In the preview window, click **Combine & Transform Data**. Power BI stacks all Parquet files into one table.
4. In the Power Query editor, verify the `value` column is typed as **Decimal Number**. If not, click the column header icon and change it.
5. Click **Close & Apply**.

You can now filter and slice by any of the six columns to build report pages:

- Filter `report_type = 'univariate'` and `metric = 'mean'` to compare means across all numeric columns.
- Filter `report_type = 'frequency'` and `dimension = 'province'` to see value distributions for a specific column.
- Filter `report_type = 'true_duplicates'` and `metric = 'duplicate_pct'` to monitor data quality across files.
- Filter `report_type = 'crosstab'` and `metric = 'dwelling_count'` to see your custom tabulation results.
- Slice by `source_file` to compare validation runs across different input files or time periods.

**Suggested DAX measures:**

```dax
Total Value = SUM('validation'[value])
Row Count = COUNTROWS('validation')
```

---

## 11. Using in JupyterHub or Microsoft Fabric

In notebook environments (JupyterHub, Fabric), `uv` is not available inside the running kernel. Install the package using `pip` directly in a notebook cell:

```python
import subprocess, sys

subprocess.run([
    sys.executable, "-m", "pip", "install",
    "data-validator==0.1.0",
    "--index-url",       "https://your-artifactory/simple",
    "--extra-index-url", "https://pypi.org/simple",
    "--quiet",
], check=True)
```

Then use it as normal:

```python
from data_validator import DataValidator, TabulationSpec, StatSpec

with DataValidator(
    source_path  = "/lakehouse/default/Files/housing_survey.parquet",
    output_dir   = "/lakehouse/default/Files/validation_output",
    id_columns   = ["record_id"],
    memory_limit = "8GB",
) as v:
    v.run_all()
```

### Memory management on Kubernetes / Fabric

DuckDB reads the total RAM of the node by default, which can exceed the actual memory limit of your pod or notebook container. Use the following snippet to stay safely within your container's real limit:

```python
import pathlib

def get_pod_memory_limit_gb(headroom_gb: int = 1) -> str | None:
    """Read the pod cgroup memory limit and return a DuckDB-safe limit string."""
    cgroup_file = pathlib.Path("/sys/fs/cgroup/memory.max")
    if cgroup_file.exists():
        raw = cgroup_file.read_text().strip()
        if raw != "max":                          # "max" means no limit set
            limit_gb = int(raw) // (1024 ** 3)
            return f"{max(1, limit_gb - headroom_gb)}GB"
    return None   # let DuckDB use its own default

with DataValidator(
    source_path  = "data.parquet",
    output_dir   = "./reports",
    memory_limit = get_pod_memory_limit_gb(),
) as v:
    v.run_all()
```

---

## 12. All options reference

```python
DataValidator(
    source_path      = "data.parquet",  # Path to input file or Delta Lake folder
    output_dir       = "./reports",     # Where to write output (validation/ created inside)
    id_columns       = ["record_id"],   # Column(s) forming the logical primary key
    string_delimiter = " ",            # Delimiter for splitting string columns into tokens
    max_categories   = 500,             # Skip frequency tables above this many distinct values
    n_histogram_bins = 20,              # Number of bins in numeric histograms
    memory_limit     = "8GB",          # DuckDB memory cap
    threads          = 8,               # CPU threads for DuckDB
)
```

Individual report methods (all return a DataFrame and write a Parquet file):

```python
v.run_schema()
v.run_true_duplicates()
v.run_id_duplicates(id_columns=["record_id"])   # can override instance setting
v.run_univariate()
v.run_frequency()
v.run_string_components(delimiter="_")          # can override instance setting
v.run_tabulation(spec)                          # single TabulationSpec
v.run_tabulations(specs)                        # list of TabulationSpec
v.run_all(tabulation_specs=specs)               # everything at once
```

Utility methods:

```python
v.preview(n=10)          # return the first n rows of the source file as a DataFrame
v.sql("SELECT ...")      # run arbitrary SQL against the registered 'src' view
v.list_outputs()         # return list of all Parquet files written so far
```

---

## 13. For developers

### Running the tests

```bash
uv run pytest
```

With a coverage report:

```bash
uv run pytest --cov=data_validator --cov-report=term-missing
```

### Adding or removing packages

```bash
# Add a runtime dependency (goes into [project] dependencies in pyproject.toml)
uv add some-package

# Add a dev-only dependency (not included in the distributed package)
uv add --dev some-dev-tool

# Remove a package
uv remove some-package
```

After any of these commands, `uv.lock` is updated automatically. **Always commit `uv.lock`** alongside your code changes. It is what guarantees every developer, CI run, and Fabric deployment gets bit-for-bit identical packages.

### Releasing a new version

1. Update `version = "..."` in `pyproject.toml`.
2. Commit the change: `git commit -am "bump version to 0.2.0"`
3. Push and create a Git tag: `git tag v0.2.0 && git push origin v0.2.0`
4. The GitLab CI pipeline picks up the tag, runs the tests, builds the wheel, and publishes to Artifactory automatically.

To publish manually if needed:

```bash
export UV_PUBLISH_TOKEN="your-artifactory-api-key"
uv build                       # creates dist/data_validator-0.x.x-py3-none-any.whl
uv publish --index internal    # uploads to Artifactory
```

### GitLab CI/CD

The pipeline defined in `.gitlab-ci.yml` has two stages:

**test** — runs on every push to every branch. Installs dependencies with `uv sync --frozen` (uses `uv.lock` exactly, no re-resolution) then runs pytest.

**publish** — runs only when a version tag like `v0.2.0` is pushed. Builds the wheel and publishes to Artifactory.

```yaml
# .gitlab-ci.yml

variables:
  UV_CACHE_DIR:        "$CI_PROJECT_DIR/.uv-cache"
  UV_INDEX_URL:        "https://your-artifactory/simple"
  UV_EXTRA_INDEX_URL:  "https://pypi.org/simple"
  UV_PUBLISH_TOKEN:    "$ARTIFACTORY_TOKEN"   # set in GitLab CI/CD → Variables

.uv-base:
  image: python:3.12-slim
  before_script:
    - pip install uv --quiet
    - uv sync --extra dev --frozen
  cache:
    key: "uv-$CI_COMMIT_REF_SLUG"
    paths: [.uv-cache/, .venv/]

test:
  extends: .uv-base
  stage: test
  script:
    - uv run pytest --cov=data_validator --cov-report=xml
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

publish:
  extends: .uv-base
  stage: deploy
  script:
    - uv build
    - uv publish --index internal
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
```

---

## 14. Project structure

```
data-validator/
│
├── src/
│   └── data_validator/
│       ├── __init__.py       # Public API — what gets imported
│       ├── validator.py      # DataValidator class — the main entry point
│       ├── reports.py        # Individual report functions
│       ├── specs.py          # TabulationSpec and StatSpec
│       └── cli.py            # The data-validate command line tool
│
├── tests/
│   └── test_validator.py     # Automated test suite
│
├── examples/
│   ├── housing_validation.py # Full worked example with synthetic data
│   ├── tabulations.yaml      # Example YAML tabulation config
│   └── tabulations.json      # Example JSON tabulation config
│
├── pyproject.toml            # Project metadata, dependencies, tool config
├── uv.lock                   # Pinned package versions — always commit this
├── .python-version           # Python version pin (3.12)
└── README.md                 # This file
```

---

## 15. Troubleshooting

**`uv: command not found`**
uv is not installed or not on your PATH. Re-run the install command from section 2 and restart your terminal before trying again.

**`ModuleNotFoundError: No module named 'data_validator'`**
You are running Python outside the virtual environment. Use `uv run python your_script.py` instead of `python your_script.py`. Alternatively, activate the environment first: `source .venv/bin/activate` on Mac/Linux, or `.venv\Scripts\activate` on Windows.

**`FileNotFoundError` when reading a Delta Lake directory**
Make sure you have installed the delta extra (`uv sync --extra delta`). On first use, DuckDB downloads the extension from the internet — this will fail in air-gapped environments. In that case, the extension needs to be pre-installed into your Docker image or JupyterHub base environment.

**The tool is using too much memory or crashing on large files**
Set `--memory-limit` on the CLI or `memory_limit=` in the Python constructor (e.g. `"4GB"`). In Kubernetes or Fabric, use the cgroup detection snippet in section 11 to automatically stay within your pod's real memory limit.

**The frequency report skips a column I care about (`skipped_high_cardinality`)**
Raise the threshold with `--max-categories 2000` (or whatever is appropriate). Be aware this produces larger output files. If you only need the distinct count rather than the full table, use a cross-tabulation: `StatSpec("distinct_count", "APPROX_COUNT_DISTINCT(column_name)")`.

**`KeyError: 'tabulations'` when loading a YAML or JSON config file**
Your file uses a different top-level key name. Pass the correct key: `TabulationSpec.from_yaml("config.yaml", key="your_key")`.

**Tests fail after pulling new code from GitLab**
Run `uv sync --extra dev` to bring your environment in line with the updated `uv.lock`.

**On Windows, the `\` line continuation in CLI examples doesn't work**
Replace `\` with `` ` `` (backtick) in PowerShell, or write the whole command on one line.
