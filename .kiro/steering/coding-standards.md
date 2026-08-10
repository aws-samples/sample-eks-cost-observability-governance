# Coding Standards

## Python Style

- Python 3.14+ features are encouraged (type hints, match statements, etc.)
- Line length: 120 characters max
- Use Ruff for linting with rules: E (errors), F (pyflakes), I (isort), W (warnings)
- Run `make lint` to verify before committing

## Code Organization

- All source code lives under `src/`
- Each module should have a clear single responsibility
- Use `__init__.py` to define the public API of each package
- Keep imports organized: stdlib → third-party → local (enforced by Ruff isort)

## Naming Conventions

- Modules and packages: `snake_case`
- Classes: `PascalCase`
- Functions and variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private/internal: prefix with `_`

## Type Hints

- All public functions must have type annotations for parameters and return values
- Use `typing` module types where needed (e.g., `Optional`, `TypeAlias`)
- Prefer built-in generics (`list[str]`, `dict[str, Any]`) over `typing.List`, `typing.Dict`

## Error Handling

- Use specific exception types, never bare `except:`
- Define custom exceptions in a dedicated `exceptions.py` per package when needed
- Log errors with context before re-raising or wrapping
- Use structured logging (include relevant identifiers like namespace, pod name, governance name)

## Async Patterns

- The operator uses Kopf which is async-native — handlers should be `async def`
- Use `asyncio` for concurrent operations (e.g., parallel Athena queries)
- Avoid blocking calls in async handlers; use `asyncio.to_thread()` when calling sync APIs

## Documentation

- All public modules, classes, and functions need docstrings
- Use Google-style docstrings
- Include usage examples in docstrings for non-obvious APIs

## Dependencies

- Production dependencies go in `[project.dependencies]` in pyproject.toml
- Dev/test dependencies go in `[dependency-groups] dev`
- Pin to compatible ranges (e.g., `>=1.0,<2.0`) for stability
- Run `uv sync` after modifying dependencies

## Security

- Never hardcode credentials or secrets
- Use environment variables for configuration (see README for the expected set)
- Run `make security` (bandit + gitleaks) before committing
- Validate and sanitize all external input (Kubernetes API responses, Athena results)
