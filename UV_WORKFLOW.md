# uv Workflow — data-validator

## Prerequisites

```bash
# Install uv (one-time, or managed by your platform image)
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: pip install uv
```

---

## First-time setup

```bash
git clone https://your-gitlab/data-validator.git
cd data-validator

# Create venv, install all deps including dev extras, generate uv.lock
uv sync --extra dev

# Activate (optional — uv run handles this automatically)
source .venv/bin/activate
```

`uv sync` reads `pyproject.toml`, resolves the full dependency graph, writes
`uv.lock`, and installs everything into `.venv`. Commit `uv.lock` so that all
environments (dev, CI, Fabric) get byte-for-byte identical installs.

---

## Day-to-day commands

| Task | Command |
|---|---|
| Install / sync deps | `uv sync --extra dev` |
| Add a runtime dep | `uv add duckdb` |
| Add a dev-only dep | `uv add --dev pytest-xdist` |
| Remove a dep | `uv remove some-package` |
| Run tests | `uv run pytest` |
| Run the CLI | `uv run data-validate data.parquet --output-dir ./reports` |
| Run a script | `uv run python examples/housing_validation.py` |
| Update all deps | `uv lock --upgrade` |
| Build wheel | `uv build` |
| Publish to Artifactory | `uv publish --index internal` |

---

## Installing extras

```bash
# Delta Lake support
uv sync --extra delta

# YAML config support
uv sync --extra yaml

# Everything
uv sync --extra all --extra dev
```

---

## Installing in JupyterHub / Fabric notebooks

```python
# In a notebook cell — uv is typically not available in notebook kernels,
# so use pip against the existing kernel. uv.lock still pins the exact versions.
import subprocess, sys
subprocess.run([
    sys.executable, "-m", "pip", "install",
    "data-validator",
    "--index-url", "https://your-artifactory/simple",
    "--extra-index-url", "https://pypi.org/simple",
], check=True)
```

Or, if uv IS available in your JupyterHub environment:
```bash
uv pip install data-validator --index internal
```

---

## Publishing to Artifactory

```bash
# Set credentials (or use keyring / UV_PUBLISH_TOKEN env var)
export UV_PUBLISH_TOKEN="your-artifactory-api-key"

# Build and publish
uv build
uv publish --index internal
```

The `[[tool.uv.index]]` block in `pyproject.toml` defines the `internal` index.
Update the `url` and `publish-url` fields to match your Artifactory instance.

---

## GitLab CI/CD snippet

```yaml
# .gitlab-ci.yml

variables:
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.uv-cache"
  UV_INDEX_URL: "https://your-artifactory/simple"
  UV_EXTRA_INDEX_URL: "https://pypi.org/simple"
  UV_PUBLISH_TOKEN: "$ARTIFACTORY_TOKEN"   # set in GitLab CI/CD variables

.uv-base:
  image: python:3.12-slim
  before_script:
    - pip install uv --quiet
    - uv sync --extra dev --frozen   # --frozen = use uv.lock exactly, no resolution
  cache:
    key: "uv-$CI_COMMIT_REF_SLUG"
    paths:
      - .uv-cache/
      - .venv/

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
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'   # tag-triggered, e.g. v0.2.0
```

---

## Lockfile notes

- **Always commit `uv.lock`** — it guarantees reproducible installs across dev,
  CI, and Fabric.
- **Never hand-edit `uv.lock`** — regenerate with `uv lock` or `uv sync`.
- On Fabric or other environments without uv, `pip install` against Artifactory
  will still honour the pinned versions because the wheel carries no lockfile
  dependency — just use `pip install data-validator==0.1.0`.
