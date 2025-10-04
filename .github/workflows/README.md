# GitHub Actions Workflows

This directory contains the CI/CD workflows for the text2sql-agent project. The workflows provide comprehensive testing, quality assurance, and automated deployment using LangGraph (LangChain Hosted).

## Workflow Overview

### 1. Comprehensive Tests (`test-with-results.yml`)
**Triggers:** Push to main/develop, Pull Requests
**Purpose:** Complete testing pipeline with quality checks and evaluation

**Jobs:**
- **Setup:** Environment setup with Python 3.11 and UV dependency management
- **Quality Checks:** Linting, formatting, and pre-commit hooks
- **Test Coverage:** Test execution with coverage reporting
- **Unit Tests:** Individual component testing
- **Integration Tests:** Tests with external dependencies
- **E2E Tests:** End-to-end workflow testing
- **Evaluation Tests:** LLM-based evaluation (PR only)
- **Evaluation Report:** LangSmith integration with PR comments

### 2. Preview Deployment (`preview-deployment.yml`)
**Triggers:** PR opened, synchronized, or reopened to main
**Purpose:** Create preview deployments for PR testing

**Features:**
- **Docker Build:** Multi-platform Docker image with preview tag
- **LangGraph Deployment:** Deploy to preview environment
- **PR Comments:** Automatic status reporting
- **Preview URLs:** `https://text2sql-agent-pr-<pr-number>.langchain.dev`

### 3. Production Deployment (`new-lgp-revision.yml`)
**Triggers:** PR closed (merged or not)
**Purpose:** Cleanup previews and deploy to production

**Jobs:**
- **Cleanup Preview:** Remove preview deployment when PR closes
- **Build Production:** Build and push production Docker image (merged PRs only)
- **Deploy Production:** Deploy to production environment (merged PRs only)
- **Production URL:** `https://text2sql-agent-prod.langchain.dev`



## Deployment Pipeline

### Pipeline Flow

| Event | Action | Docker Tag | Deployment |
|-------|--------|------------|------------|
| Push to main/develop | Run comprehensive tests | - | - |
| PR open/sync | Build & deploy preview | `preview-<pr#>` | `text2sql-agent-pr-<pr#>` |
| PR close | Cleanup preview | - | Delete preview |
| PR merge | Deploy to production | `latest` | `text2sql-agent-prod` |

### Deployment Naming Convention

- **Preview Deployments:** `text2sql-agent-pr-<pr-number>`
- **Production Deployment:** `text2sql-agent-prod`
- **Docker Images:**
  - Preview: `perinim98/text2sql-agent:preview-<pr-number>`
  - Production: `perinim98/text2sql-agent:latest`

### URLs

- **Preview URLs:** `https://text2sql-agent-pr-<pr-number>.langchain.dev`
- **Production URL:** `https://text2sql-agent-prod.langchain.dev`

## Usage

### Local Development
Use the Makefile targets that correspond to the CI workflows:

```bash
# Quality checks (equivalent to test-with-results.yml quality-checks job)
make lint
make pre-commit

# Test execution (equivalent to test-with-results.yml test-coverage job)
make test

# Format code (auto-fix)
make format
```

### CI/CD Pipeline
The workflows run automatically on:
- **Every PR:** Comprehensive tests, preview deployment
- **Every push to main/develop:** Comprehensive tests
- **PR close:** Cleanup preview deployment
- **PR merge:** Production deployment

### Required Secrets
The following secrets must be configured in your GitHub repository:

- `OPENAI_API_KEY`: For OpenAI API access in tests and application
- `LANGSMITH_API_KEY`: For LangGraph API integration
- `LANGSMITH_TRACING`: For LangSmith tracing
- `LANGSMITH_ENDPOINT`: For LangSmith endpoint configuration
- `DOCKER_USERNAME`: Your Docker Hub username
- `DOCKER_PASSWORD`: Your Docker Hub access token

## API Integration

The pipeline uses a custom Python script (`.github/scripts/langgraph_api.py`) to interact with the LangGraph API:

- **List Deployments:** Find existing preview deployments
- **Create Deployment:** Create new preview/production deployments
- **Update Deployment:** Update existing deployments with new images
- **Delete Deployment:** Clean up preview deployments

## Workflow Benefits

1. **No wasteful deployments:** Only deploys on PR events, not every push
2. **Preview environments:** Each PR gets its own preview deployment
3. **Automatic cleanup:** Preview deployments are automatically removed when PRs are closed
4. **Production safety:** Production only deploys when PRs are merged
5. **Cost optimization:** Preview deployments use minimal resources (scale to 0 when not in use)
6. **Parallel Execution:** Different test types run in parallel for faster feedback
7. **Caching:** UV dependencies are cached to speed up builds
8. **Artifact Management:** Test results and reports are preserved as artifacts
9. **PR Integration:** Automatic commenting and status reporting
10. **Quality Gates:** Multiple layers of quality assurance

## Troubleshooting

### Common Issues

1. **Preview deployment not found:** Check if the PR number is correct and the deployment was created successfully
2. **API errors:** Verify the `LANGSMITH_API_KEY` secret is correct
3. **Docker build failures:** Check the Dockerfile path and build context
4. **Production deployment fails:** Ensure the PR was actually merged, not just closed
5. **Cache Misses:** If builds are slow, check that cache keys are consistent
6. **Secret Errors:** Ensure all required secrets are properly configured
7. **Test Failures:** Check the specific test job logs for detailed error information

### Debugging

- Check GitHub Actions logs for detailed error messages
- Verify secrets are properly configured
- Test API calls manually using the script: `python .github/scripts/langgraph_api.py --help`
- The script supports a `--base-url` parameter for different LangGraph environments

### Manual Workflow Execution
You can manually trigger workflows using the GitHub Actions UI or by dispatching workflow events via the GitHub API.

## Contributing

When adding new workflows or modifying existing ones:

1. Follow the established naming conventions
2. Use the Makefile targets when possible for consistency
3. Include appropriate error handling and reporting
4. Update this README with any changes
5. Test workflows locally using the Makefile targets
