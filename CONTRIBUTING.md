# Contributing

## Setup

Follow the steps in [CLAUDE.md](CLAUDE.md) to get the project running locally. Copy `.env.example` to `.env` and fill in your values before starting the backend.

## Branching

Branch off `main`. Use these prefixes:

| Prefix | Use for |
|--------|---------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code changes with no behavior change |
| `docs/` | Documentation only |
| `chore/` | Dependency bumps, CI, tooling |

Example: `feat/export-geojson`, `fix/tracker-id-swap`

## Pull Requests

- Open PRs against `main`
- Keep PRs focused — one feature or fix per PR
- Squash-merge when merging (keeps `main` history linear)
- CI must pass (Ruff lint + frontend build) before merging

## Code Style

- Python: formatted and linted with [Ruff](https://docs.astral.sh/ruff/) — run both before committing:
  - `ruff format .` — formats code
  - `ruff check . --fix` — lints and applies auto-fixes
- JavaScript/Vue: no enforced formatter yet — match the style of surrounding code
- No comments unless the *why* is non-obvious

## No Automated Tests

This project has no test suite. Before opening a PR, manually verify the affected flow end-to-end (see testing notes in CLAUDE.md).
