# Testing Guide

## Test Structure

```
tests/
  unit/          # Fast, isolated tests (no AWS/K8s calls)
  integ/         # Integration tests (may hit real services)
```

## Running Tests

- `make test` — Run all tests
- `make test-unit` — Unit tests only
- `make test-integ` — Integration tests only
- `make test-cov` — Tests with coverage report
- `make test-cov-enforce` — Tests with 80% minimum coverage enforcement

## Conventions

- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>` or `Test<Feature>`
- Test functions: `test_<behavior_being_tested>`
- Use pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.asyncio`

## Unit Tests

- Mock all external dependencies (AWS, Kubernetes API)
- Use `unittest.mock.patch` or `pytest-mock` for mocking
- Each test should validate one behavior
- Keep tests independent — no shared mutable state between tests
- Target: fast execution (< 1 second per test)

## Integration Tests

- Marked with `@pytest.mark.integration`
- May require AWS credentials and/or a running cluster
- Use real API calls but against test/dev resources
- Clean up any resources created during tests

## Async Tests

- Use `@pytest.mark.asyncio` for async test functions
- The fixture loop scope is set to `function` (each test gets its own event loop)
- Mock async functions with `AsyncMock`

## Fixtures

- Place shared fixtures in `conftest.py` at the appropriate level
- Use factory fixtures for creating test data with variations
- Common fixtures to create:
  - `mock_k8s_client` — Mocked Kubernetes API client
  - `mock_athena_client` — Mocked Athena/boto3 client
  - `sample_cost_governance_spec` — Example CRD spec dict
  - `sample_pod_list` — Example pod list with various label states

## Coverage

- Minimum threshold: 80%
- Coverage is measured against `src/` code
- Use `# pragma: no cover` sparingly and only for unreachable defensive code
