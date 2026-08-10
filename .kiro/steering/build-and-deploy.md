# Build and Deploy

## Local Development

```bash
# Install all dependencies (including dev)
make install

# Run linter
make lint

# Run tests
make test

# Run security checks
make security

# Clean up caches
make clean
```

## Makefile Targets

| Target | Purpose |
|--------|---------|
| `make install` | Install dependencies via `uv sync` |
| `make test` | Run all pytest tests |
| `make test-unit` | Run unit tests only |
| `make test-integ` | Run integration tests only |
| `make test-cov` | Tests with coverage report |
| `make test-cov-enforce` | Tests with 80% coverage gate |
| `make lint` | Ruff linting on `src/` |
| `make security` | Bandit + gitleaks scan |
| `make protoshield` | ProtoShield scan (needs AWS creds) |
| `make clean` | Remove __pycache__, .pytest_cache, *.pyc |

## Environment Variables

The operator requires these at runtime:

| Variable | Required | Description |
|----------|----------|-------------|
| `EKS_CLUSTER_NAME` | Yes | EKS cluster name |
| `ATHENA_DATABASE` | Yes | Athena database for CUR data |
| `ATHENA_TABLE` | Yes | Athena table name |
| `ATHENA_S3_OUTPUT` | Yes | S3 path for query results |
| `AWS_REGION` | No | Defaults to `us-east-1` |
| `COST_LOOKBACK_DAYS` | No | Days of cost data to query (default: 7) |
| `LOG_LEVEL` | No | DEBUG, INFO, WARNING, ERROR (default: INFO) |

## Package Management

This project uses **uv** as the package manager:
- `uv sync` — Install/update dependencies from lock file
- `uv add <package>` — Add a production dependency
- `uv add --group dev <package>` — Add a dev dependency
- `uv run <command>` — Run a command in the project's virtual environment
- `uv lock` — Regenerate the lock file

## Deployment

The operator deploys to Kubernetes in the `cost-governance-system` namespace. Key resources:
- CRDs: `CostGovernance`, `ViolationReport`
- IAM: `CostGovernanceOperatorRole` with Athena/S3/Glue permissions
- Pod Identity: EKS Pod Identity association for IAM auth
- ServiceMonitor: For Prometheus metric scraping

## Git Workflow

- Work on feature branches, never commit directly to main
- Run `make lint` and `make test` before pushing
- PRs should reference related issues
- Keep commits focused on a single change
