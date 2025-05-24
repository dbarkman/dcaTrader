# Testing Guide

## Setup

Make sure your virtual environment is properly activated:

```bash
source venv/bin/activate
# Verify python points to venv:
which python  # Should show: ~/dcaTrader/venv/bin/python
```

If needed, install test dependencies:
```bash
pip install -r requirements.txt
```

## Running Tests

### Using the test runner script (recommended):

```bash
python run_tests.py all          # Run all tests
python run_tests.py unit         # Run only unit tests  
python run_tests.py coverage     # Run with coverage report
python run_tests.py html         # Generate HTML coverage report
python run_tests.py integration  # Run integration tests
python run_tests.py fast         # Run tests without coverage
python run_tests.py verbose      # Run with verbose output
```

### Using pytest directly:

```bash
python -m pytest tests/ -v                    # Run all tests
python -m pytest tests/ -m unit              # Run only unit tests
python -m pytest tests/ --cov=src            # Run with coverage
python -m pytest tests/ --cov=src --cov-report=html  # HTML coverage report
```

## Test Organization

- **Unit tests**: Use `@pytest.mark.unit` - test individual functions with mocking
- **Integration tests**: Use `@pytest.mark.integration` - test end-to-end scenarios
- **Slow tests**: Use `@pytest.mark.slow` - tests that take longer to run
- **DB tests**: Use `@pytest.mark.db` - tests requiring database connection

## Coverage Reports

- Terminal coverage: Shows percentage and missing lines
- HTML coverage: Generated in `htmlcov/index.html` - open in browser for detailed view

## Current Status

- ✅ 34 tests passing
- ✅ 84% code coverage
- ✅ All Phase 1 functionality tested 