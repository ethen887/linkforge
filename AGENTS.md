# Repository Guidelines

## Project Structure & Module Organization

LinkForge is a Python 3.10+ package using the `src/` layout. Application code lives in `src/linkforge/`: `agent/` contains Browser Agent contracts and orchestration, `browser/` browser adapters, `observation/` page-state capture, `action/` structured browser actions, `llm/` provider implementations, and `config/` settings. Keep new functionality inside the most specific existing module; add a small, focused module rather than growing unrelated files.

Tests mirror product areas under `tests/unit/` and `tests/integration/`; browser integration coverage is in `tests/integration/browser/`. Put shared test doubles in `tests/fakes.py`. Repository and design notes are in `docu/`.

## Build, Test, and Development Commands

Use `uv` with the committed lockfile:

```powershell
uv sync --locked                 # create/update the local environment from uv.lock
uv run pytest                    # run the complete test suite
uv run ruff format --check .     # verify formatting
uv run ruff check .              # run lint checks
uv run mypy src                  # type-check package code
```

Run `uv run ruff format .` only when formatting intended changes. The CI workflow runs all four quality checks above on pushes and pull requests to `main`.

## Coding Style & Naming Conventions

Follow Ruff's 108-character line limit and Python 3.10-compatible syntax. Use four-space indentation, `snake_case` for modules/functions/variables, `PascalCase` for classes, and clear type annotations on public interfaces. Keep external services behind replaceable adapters (for example, browser and LLM implementations). Prefer deterministic rules over model decisions for predictable work. Do not commit API keys, cookies, tokens, passwords, or user data.

## Testing Guidelines

Use `pytest`; name files `test_<feature>.py`, classes `Test<Feature>`, and tests `test_<behavior>`. Add or update unit tests with behavior changes. Mark integration tests only when they need real external dependencies, and ensure tests remain safe to run without credentials. Run the full quality command set before opening a pull request.

## Commit & Pull Request Guidelines

History uses concise Conventional Commit-style prefixes, including `feat(browser): ...`, `fix: ...`, `refactor: ...`, and `chore: ...`; follow that pattern and keep each commit scoped. Work from an Issue on a feature branch, never directly on `main`. Use the pull-request template: link the Issue (`Closes #123`), explain purpose and major changes, describe meaningful design choices, and list exact verification commands. Include screenshots or terminal output when a UI/CLI-visible change benefits from evidence.
