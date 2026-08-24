# Makefile for Project Automation

.PHONY: install lint test test-deployment test-e2e test-evals build all clean security-scan format pre-commit

# Variables
PACKAGE_NAME = agents
TEST_DIR = tests
SCRIPTS_DIR = .github/scripts

# Default target
all: lint test

# Install project dependencies
install:
	uv sync

# Linting and Formatting Checks
lint:
	uv run ruff check $(PACKAGE_NAME) $(TEST_DIR) $(SCRIPTS_DIR)
	uv run black --check $(PACKAGE_NAME) $(TEST_DIR) $(SCRIPTS_DIR)
	uv run isort --check-only $(PACKAGE_NAME) $(TEST_DIR) $(SCRIPTS_DIR)

# Run Tests with Coverage
# Offline suites only: e2e and evaluations need live model and LangSmith access,
# so they get their own targets and their own CI jobs. Keeping them out of here
# means a missing credential cannot fail the coverage gate.
test:
	uv run pytest --cov=$(PACKAGE_NAME) --cov-report=xml \
		$(TEST_DIR)/unit $(TEST_DIR)/integrations $(TEST_DIR)/deployment

# Suites that call real services
test-e2e:
	uv run pytest $(TEST_DIR)/e2e/

test-evals:
	uv run pytest -m evaluator

# Test the deployment client for both hosting models (no credentials needed)
test-deployment:
	uv run pytest $(TEST_DIR)/deployment/ -v

# Run Pre-Commit Hooks
pre-commit:
	uv run pre-commit run --all-files

# Format Code (auto-fix)
format:
	uv run black $(PACKAGE_NAME) $(TEST_DIR) $(SCRIPTS_DIR)
	uv run isort $(PACKAGE_NAME) $(TEST_DIR) $(SCRIPTS_DIR)
	uv run ruff check --fix $(PACKAGE_NAME) $(TEST_DIR) $(SCRIPTS_DIR)

# Security Scanning
security-scan:
	uv run bandit -r $(PACKAGE_NAME)/ $(SCRIPTS_DIR)/

# Clean Up Generated Files
clean:
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info
	rm -rf htmlcov/
	rm -rf .mypy_cache/
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf .langgraph_api/
	rm -rf .coverage*
	rm -rf *.coverage.*
	rm -rf coverage.xml
	rm -rf evaluation_config__*.json

# Build the Package
build:
	uv run build
