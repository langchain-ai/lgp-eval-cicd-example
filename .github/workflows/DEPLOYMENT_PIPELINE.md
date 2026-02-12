# CI/CD Pipeline Documentation

## Overview

This repository uses a modern CI/CD pipeline with GitHub Actions for automated testing, preview deployments, and production deployments using LangSmith Deployment.

## Pipeline Structure

### 1. Testing Pipeline (`test-with-results.yml`)
- **Trigger:** Every push to main/develop and every PR
- **Purpose:** Run comprehensive tests, linting, and quality checks
- **Jobs:**
  - Quality checks (linting, formatting)
  - Test coverage
  - Unit tests
  - Integration tests
  - E2E tests
  - Evaluation tests (PR only)

### 2. Preview Deployment (`preview-deployment.yml`)
- **Trigger:** PR opened, synchronized, or reopened
- **Purpose:** Create/update preview deployments for PR testing
- **Jobs:**
  - Build Docker image with tag `preview-<pr-number>`
  - Deploy to LangGraph as preview deployment
  - Update existing preview if it exists

### 3. Production Deployment (`new-deployment-revision.yml`)
- **Trigger:** PR closed (merged or not)
- **Purpose:** Cleanup previews and deploy to production
- **Jobs:**
  - Cleanup preview deployment
  - Build production Docker image (only if merged)
  - Deploy to production (only if merged)

## Deployment Naming Convention

- **Preview Deployments:** `text2sql-agent-pr-<pr-number>`
- **Production Deployment:** `text2sql-agent-prod`
- **Docker Images:**
  - Preview: `perinim98/text2sql-agent:preview-<pr-number>`
  - Production: `perinim98/text2sql-agent:latest`

## URLs

- **Preview URLs:** `https://text2sql-agent-pr-<pr-number>.langchain.dev`
- **Production URL:** `https://text2sql-agent-prod.langchain.dev`

## API Integration

The pipeline uses a custom Python script (`.github/scripts/langgraph_api.py`) to interact with the LangGraph API:

- **List Deployments:** Find existing preview deployments
- **Create Deployment:** Create new preview/production deployments
- **Update Deployment:** Update existing deployments with new images
- **Delete Deployment:** Clean up preview deployments

## Required Secrets

The following GitHub secrets are required:

- `LANGSMITH_API_KEY`: LangGraph API key
- `OPENAI_API_KEY`: OpenAI API key for the application
- `DOCKER_USERNAME`: Docker Hub username
- `DOCKER_PASSWORD`: Docker Hub password/token

## Workflow Summary

| Event | Action | Docker Tag | Deployment |
|-------|--------|------------|------------|
| Push to main | Run tests only | - | - |
| PR open/sync | Build & deploy preview | `preview-<pr#>` | `text2sql-agent-pr-<pr#>` |
| PR close | Cleanup preview | - | Delete preview |
| PR merge | Deploy to production | `latest` | `text2sql-agent-prod` |

## Benefits

1. **No wasteful deployments:** Only deploys on PR events, not every push
2. **Preview environments:** Each PR gets its own preview deployment
3. **Automatic cleanup:** Preview deployments are automatically removed when PRs are closed
4. **Production safety:** Production only deploys when PRs are merged
5. **Cost optimization:** Preview deployments use minimal resources (scale to 0 when not in use)

## Troubleshooting

### Common Issues

1. **Preview deployment not found:** Check if the PR number is correct and the deployment was created successfully
2. **API errors:** Verify the `LANGSMITH_API_KEY` secret is correct
3. **Docker build failures:** Check the Dockerfile path and build context
4. **Production deployment fails:** Ensure the PR was actually merged, not just closed

### Debugging

- Check GitHub Actions logs for detailed error messages
- Verify secrets are properly configured
- Test API calls manually using the script: `python .github/scripts/langgraph_api.py --help`
