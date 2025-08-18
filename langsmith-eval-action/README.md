# LangSmith Evaluation Action 🧪

A comprehensive GitHub Action for running LangSmith evaluations with automated reporting, threshold checking, and PR integration.

## Features

- 🧪 **Run LangSmith Evaluations** - Execute pytest-based evaluation tests with LangSmith integration
- 📊 **Automated Reporting** - Generate markdown reports with evaluation results and criteria
- 📝 **PR Comments** - Automatically post evaluation results as pull request comments
- ⚡ **Threshold Validation** - Define pass/fail criteria with flexible threshold expressions
- 🔄 **Multi-LLM Support** - Support for OpenAI, Anthropic, and other LLM providers
- 📈 **Configurable Concurrency** - Control evaluation concurrency for performance optimization
- 🛡️ **Production Ready** - Comprehensive error handling and logging

## Quick Start

### Basic Evaluation Workflow

```yaml
name: LangSmith Evaluations
on:
  pull_request:
    branches: [main]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install pytest langsmith openevals
          pip install -e .

      - name: Run LangSmith Evaluations
        uses: langchain-ai/langsmith-eval-action@v1
        with:
          action: 'run-evaluations'
          langsmith-api-key: ${{ secrets.LANGSMITH_API_KEY }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          test-command: 'pytest tests/offline_evals/ -m evaluator'
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Advanced Configuration

```yaml
name: Comprehensive LangSmith Evaluation Pipeline

on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install pytest langsmith openevals anthropic
          pip install -e .

      - name: Run LangSmith Evaluations
        uses: langchain-ai/langsmith-eval-action@v1
        with:
          action: 'run-evaluations'
          langsmith-api-key: ${{ secrets.LANGSMITH_API_KEY }}
          test-command: 'pytest tests/offline_evals/ -m evaluator --verbose'
          dataset-name: 'my-evaluation-dataset'
          experiment-prefix: 'ci-eval'
          max-concurrency: '5'
          fail-on-threshold: 'true'
          report-file: 'evaluation_results.md'
          environment-variables: |
            {
              "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
              "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
              "GOOGLE_API_KEY": "${{ secrets.GOOGLE_API_KEY }}",
              "CUSTOM_MODEL_ENDPOINT": "${{ secrets.CUSTOM_MODEL_ENDPOINT }}",
              "EVALUATION_MODE": "strict"
            }
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Upload evaluation artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: evaluation-results
          path: |
            evaluation_results.md
            evaluation_config__*.json
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `action` | Action to perform: `run-evaluations`, `generate-report` | ✅ | |
| `langsmith-api-key` | LangSmith API key for running evaluations | ✅ | |
| `openai-api-key` | OpenAI API key for LLM-as-judge evaluations (DEPRECATED: use `environment-variables`) | ❌ | |
| `anthropic-api-key` | Anthropic API key for Claude evaluations (DEPRECATED: use `environment-variables`) | ❌ | |
| `environment-variables` | JSON object or YAML string of environment variables to set | ❌ | `{}` |
| `test-command` | Command to run evaluation tests | ❌ | `pytest -m evaluator` |
| `dataset-name` | LangSmith dataset name to evaluate against | ❌ | |
| `experiment-prefix` | Prefix for LangSmith experiment names | ❌ | |
| `max-concurrency` | Maximum concurrency for evaluations (1-50) | ❌ | `10` |
| `config-pattern` | Pattern for evaluation config files | ❌ | `evaluation_config__*.json` |
| `report-file` | Output file for evaluation report | ❌ | `eval_report.md` |
| `pr-comment` | Whether to post results as PR comment | ❌ | `true` |
| `fail-on-threshold` | Whether to fail if criteria are not met | ❌ | `false` |
| `python-version` | Python version to use | ❌ | `3.11` |
| `install-command` | Command to install dependencies | ❌ | `pip install langsmith` |
| `working-directory` | Working directory for commands | ❌ | `.` |

## Outputs

| Output | Description |
|--------|-------------|
| `report-file` | Path to the generated evaluation report |
| `experiment-names` | JSON array of experiment names that were evaluated |
| `total-experiments` | Total number of experiments evaluated |
| `passed-experiments` | Number of experiments that passed all criteria |
| `failed-experiments` | Number of experiments that failed criteria |
| `overall-status` | Overall evaluation status: `success`, `warning`, or `failure` |

## Evaluation Test Structure

### 1. Create Evaluation Tests

Create pytest tests marked with `@pytest.mark.evaluator`:

```python
# tests/offline_evals/test_my_evaluation.py
import json
import pytest
from langsmith import Client
from openevals.llm import create_llm_as_judge
from my_agent import my_agent_function

client = Client()

# Define evaluators
correctness_evaluator = create_llm_as_judge(
    prompt="""
    You are grading this response for correctness:

    Question: {inputs}
    Expected: {reference_outputs}
    Actual: {outputs}

    Respond with CORRECT or INCORRECT.
    """,
    feedback_key="correctness",
    model="openai:gpt-4o-mini",
)

quality_evaluator = create_llm_as_judge(
    prompt="""
    Rate the quality of this response on a scale of 1-5:

    Question: {inputs}
    Response: {outputs}

    Rating (1-5):
    """,
    feedback_key="quality",
    model="openai:gpt-4o-mini",
)

def target_function(inputs: dict) -> dict:
    \"\"\"Target function that runs your AI system\"\"\"
    result = my_agent_function(inputs["question"])
    return {"response": result}

@pytest.mark.evaluator
def test_my_evaluation():
    \"\"\"Run evaluation using LangSmith\"\"\"

    experiment_results = client.evaluate(
        target_function,
        data="my-dataset-name",
        evaluators=[correctness_evaluator, quality_evaluator],
        max_concurrency=10,
        experiment_prefix="my-experiment",
    )

    # Define scoring criteria
    criteria = {
        "correctness": ">=0.8",  # 80% or higher
        "quality": ">=3.5"       # 3.5/5 or higher
    }

    # Save configuration for reporting
    config = {
        "experiment_name": experiment_results.experiment_name,
        "criteria": criteria
    }

    safe_name = experiment_results.experiment_name.replace(":", "-").replace("/", "-")
    config_filename = f"evaluation_config__{safe_name}.json"

    with open(config_filename, "w") as f:
        json.dump(config, f)

    assert experiment_results is not None
```

### 2. Threshold Expressions

Define evaluation criteria using flexible threshold expressions:

```python
criteria = {
    "correctness": ">=0.8",      # Greater than or equal to 0.8
    "accuracy": ">0.9",          # Greater than 0.9
    "latency": "<2.0",           # Less than 2.0 seconds
    "cost": "<=0.05",            # Less than or equal to $0.05
    "satisfaction": "==5.0",     # Exactly 5.0
    "errors": "!=0"              # Not equal to 0
}
```

### 3. Configuration Files

The action expects evaluation configuration files in JSON format:

```json
{
  "experiment_name": "my-experiment-2024-01-15-12-34-56",
  "criteria": {
    "correctness": ">=0.8",
    "response_quality": ">=3.5",
    "latency": "<5.0"
  }
}
```

## Actions

### `run-evaluations`

Runs evaluation tests and generates reports:

1. Sets up Python environment
2. Installs dependencies
3. Executes evaluation tests with pytest
4. Processes evaluation config files
5. Generates markdown report
6. Posts PR comment (if enabled)
7. Sets action outputs

### `generate-report`

Generates reports from existing evaluation config files without running tests:

1. Finds evaluation config files
2. Processes results from LangSmith
3. Generates markdown report
4. Posts PR comment (if enabled)
5. Sets action outputs

## Flexible Environment Variables

The action supports flexible environment variable configuration via the `environment-variables` input, similar to the LangGraph Deploy Action pattern.

### JSON Format

```yaml
- name: Run Evaluations with Multiple APIs
  uses: langchain-ai/langsmith-eval-action@v1
  with:
    action: 'run-evaluations'
    langsmith-api-key: ${{ secrets.LANGSMITH_API_KEY }}
    environment-variables: |
      {
        "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
        "GOOGLE_API_KEY": "${{ secrets.GOOGLE_API_KEY }}",
        "COHERE_API_KEY": "${{ secrets.COHERE_API_KEY }}",
        "CUSTOM_MODEL_ENDPOINT": "${{ secrets.CUSTOM_MODEL_ENDPOINT }}",
        "EVALUATION_MODE": "comprehensive",
        "MAX_RETRIES": "3",
        "TIMEOUT_SECONDS": "300"
      }
```

### YAML-Style Format

```yaml
- name: Run Evaluations with YAML-Style Variables
  uses: langchain-ai/langsmith-eval-action@v1
  with:
    action: 'run-evaluations'
    langsmith-api-key: ${{ secrets.LANGSMITH_API_KEY }}
    environment-variables: |
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
      CUSTOM_MODEL_ENDPOINT: ${{ secrets.CUSTOM_MODEL_ENDPOINT }}
      EVALUATION_MODE: comprehensive
      MAX_RETRIES: 3
      TIMEOUT_SECONDS: 300
```

### Common Use Cases

**Multiple LLM Providers:**
```yaml
environment-variables: |
  {
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    "GOOGLE_API_KEY": "${{ secrets.GOOGLE_API_KEY }}",
    "COHERE_API_KEY": "${{ secrets.COHERE_API_KEY }}"
  }
```

**Custom Model Endpoints:**
```yaml
environment-variables: |
  {
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "AZURE_OPENAI_ENDPOINT": "${{ secrets.AZURE_OPENAI_ENDPOINT }}",
    "AZURE_OPENAI_API_VERSION": "2024-02-15-preview",
    "CUSTOM_LLM_ENDPOINT": "${{ secrets.CUSTOM_LLM_ENDPOINT }}"
  }
```

**Evaluation Configuration:**
```yaml
environment-variables: |
  {
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "EVALUATION_MODE": "strict",
    "MIN_SCORE_THRESHOLD": "0.8",
    "ENABLE_DETAILED_LOGGING": "true",
    "PARALLEL_EVALUATIONS": "true"
  }
```

**Database and External Services:**
```yaml
environment-variables: |
  {
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "DATABASE_URL": "${{ secrets.DATABASE_URL }}",
    "REDIS_URL": "${{ secrets.REDIS_URL }}",
    "S3_BUCKET": "${{ secrets.S3_BUCKET }}",
    "AWS_ACCESS_KEY_ID": "${{ secrets.AWS_ACCESS_KEY_ID }}",
    "AWS_SECRET_ACCESS_KEY": "${{ secrets.AWS_SECRET_ACCESS_KEY }}"
  }
```

### Backward Compatibility

The individual API key inputs are still supported but deprecated:

```yaml
# Old format (still works)
- uses: langchain-ai/langsmith-eval-action@v1
  with:
    openai-api-key: ${{ secrets.OPENAI_API_KEY }}     # DEPRECATED
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }} # DEPRECATED

# New format (recommended)
- uses: langchain-ai/langsmith-eval-action@v1
  with:
    environment-variables: |
      {
        "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}"
      }
```

### Environment Variable Priority

1. **environment-variables input** (highest priority)
2. **Individual API key inputs** (openai-api-key, anthropic-api-key)
3. **Existing environment variables** (lowest priority)

This allows for flexible configuration while maintaining backward compatibility.

## Multi-Step Workflow Example

```yaml
name: Complete LangSmith Evaluation Pipeline

on:
  pull_request:
    branches: [main]

jobs:
  # First job: Run evaluations
  run-evaluations:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install pytest langsmith openevals
          pip install -e .

      - name: Run LangSmith Evaluations
        id: evaluations
        uses: langchain-ai/langsmith-eval-action@v1
        with:
          action: 'run-evaluations'
          langsmith-api-key: ${{ secrets.LANGSMITH_API_KEY }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          test-command: 'pytest tests/offline_evals/ -m evaluator'
          fail-on-threshold: 'false'  # Don't fail here, handle in next job
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Upload evaluation configs
        uses: actions/upload-artifact@v4
        with:
          name: evaluation-configs
          path: evaluation_config__*.json

  # Second job: Process results and make decisions
  process-results:
    needs: run-evaluations
    runs-on: ubuntu-latest
    if: always()
    steps:
      - uses: actions/checkout@v4

      - name: Download evaluation configs
        uses: actions/download-artifact@v4
        with:
          name: evaluation-configs

      - name: Generate detailed report
        uses: langchain-ai/langsmith-eval-action@v1
        with:
          action: 'generate-report'
          langsmith-api-key: ${{ secrets.LANGSMITH_API_KEY }}
          report-file: 'detailed_evaluation_report.md'
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Check if deployment should proceed
        run: |
          # Custom logic based on evaluation results
          if [ "${{ needs.run-evaluations.outputs.failed-experiments }}" -gt "0" ]; then
            echo "⚠️ Some evaluations failed, manual review required"
            echo "deployment_approved=false" >> $GITHUB_OUTPUT
          else
            echo "✅ All evaluations passed, deployment approved"
            echo "deployment_approved=true" >> $GITHUB_OUTPUT
          fi
```

## Environment Variables

The action supports these environment variables:

- `LANGSMITH_API_KEY` - LangSmith API key (required)
- `LANGSMITH_ENDPOINT` - Custom LangSmith endpoint (optional)
- `LANGSMITH_TRACING` - Enable LangSmith tracing (optional)
- `OPENAI_API_KEY` - OpenAI API key for evaluations (optional)
- `ANTHROPIC_API_KEY` - Anthropic API key for evaluations (optional)
- `GITHUB_TOKEN` - GitHub token for PR comments (auto-provided)

## Input Validation

The action validates all inputs to prevent common configuration errors:

- **max-concurrency**: Must be between 1 and 50
- **threshold expressions**: Must use valid operators (`>=`, `>`, `<=`, `<`, `==`, `!=`)
- **environment-variables**: Must be valid JSON or YAML format
- **config files**: Must contain valid JSON with `experiment_name` and `criteria`

Invalid inputs will cause the action to fail early with helpful error messages.

## Error Handling

The action provides comprehensive error handling:

- **Python Setup Failures** - Clear messages about missing Python installations
- **Dependency Install Failures** - Detailed pip install error messages
- **Test Execution Failures** - pytest output with specific test failures
- **Config File Errors** - JSON parsing and validation errors
- **LangSmith API Errors** - Network and authentication error handling
- **GitHub API Errors** - PR comment posting error handling

## Security Considerations

- API keys are handled securely through GitHub Secrets
- No sensitive information is logged or exposed in outputs
- Config files are validated before processing
- Network requests use proper authentication headers

## Performance Optimization

- Configurable concurrency limits for evaluations
- Efficient batch processing of multiple experiments
- Minimal network requests with proper caching
- Parallel processing of config files

## Troubleshooting

### Common Issues

**No evaluation config files found**
```
❌ No evaluation config files found matching pattern: evaluation_config__*.json
```
- Ensure your evaluation tests generate config files with the correct naming pattern
- Check the `config-pattern` input parameter

**Python/dependency errors**
```
❌ Failed to install dependencies: Command 'pip install langsmith' failed
```
- Verify Python is available in the environment
- Check the `install-command` input parameter
- Ensure all required dependencies are specified

**LangSmith API authentication**
```
❌ Failed to initialize LangSmith client
```
- Verify `LANGSMITH_API_KEY` secret is set correctly
- Check API key permissions in LangSmith dashboard

**Evaluation test failures**
```
❌ Evaluation tests failed: pytest command failed
```
- Check evaluation test implementation
- Verify dataset exists in LangSmith
- Check LLM API key configuration

### Debug Mode

Enable verbose logging:

```yaml
- name: Run LangSmith Evaluations
  uses: langchain-ai/langsmith-eval-action@v1
  with:
    action: 'run-evaluations'
    test-command: 'pytest tests/offline_evals/ -m evaluator --verbose -s'
  env:
    ACTIONS_STEP_DEBUG: true
```

## Contributing

1. Fork this repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues and questions:

1. Check the [troubleshooting guide](#troubleshooting)
2. Search existing [GitHub Issues](https://github.com/langchain-ai/langsmith-eval-action/issues)
3. Open a new issue with detailed information

## Changelog

### v1.0.0

- Initial release with core evaluation functionality
- Support for pytest-based evaluation tests
- Automated report generation and PR comments
- Configurable threshold validation
- Multi-LLM provider support
