# Contributing

Open an issue with the version or commit, operating system, steps to reproduce and expected
and actual behavior. Remove private data and credentials. Discuss substantial changes before starting.

## Checks

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

## What to expect

This is a one-person project. I review reports as time permits; a response or fix may take time,
and I cannot promise a release date. Small, reproducible reports and focused pull requests help.
