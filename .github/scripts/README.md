# GitHub Actions Scripts

This directory contains Python scripts used by the GitHub Actions workflows for deployment management, status reporting, and evaluation processing.

## Scripts Overview

### 1. `langgraph_api.py`
**Purpose:** LangGraph API client for deployment management

**Features:**
- **List Deployments:** Find existing deployments by name pattern
- **Create Deployment:** Create new preview or production deployments
- **Update Deployment:** Update existing deployments with new Docker images
- **Delete Deployment:** Clean up preview deployments

**Usage:**
```bash
# Deploy preview for PR
python langgraph_api.py --action deploy-preview --pr-number 123 --image-uri docker.io/user/repo:preview-123 --api-key $LANGSMITH_API_KEY

# Deploy to production
python langgraph_api.py --action deploy-production --image-uri docker.io/user/repo:latest --api-key $LANGSMITH_API_KEY

# Cleanup preview deployment
python langgraph_api.py --action cleanup-preview --pr-number 123 --api-key $LANGSMITH_API_KEY

# Multiple secrets (direct values)
python langgraph_api.py --action deploy-preview --pr-number 123 --image-uri docker.io/user/repo:preview-123 --api-key $LANGSMITH_API_KEY --secrets OPENAI_API_KEY=sk-xxx ANTHROPIC_API_KEY=sk-xxx DATABASE_URL=postgres://...

# Multiple secrets (from environment)
python langgraph_api.py --action deploy-preview --pr-number 123 --image-uri docker.io/user/repo:preview-123 --api-key $LANGSMITH_API_KEY --secrets-from-env OPENAI_API_KEY ANTHROPIC_API_KEY DATABASE_URL REDIS_URL

# Custom deployment name
python langgraph_api.py --action deploy-preview --pr-number 123 --image-uri docker.io/user/repo:preview-123 --api-key $LANGSMITH_API_KEY --deployment-name my-custom-preview-123

# Custom resources
python langgraph_api.py --action deploy-production --image-uri docker.io/user/repo:latest --api-key $LANGSMITH_API_KEY --min-scale 1 --max-scale 3 --cpu 2 --memory-mb 2048
```

**Key Functions:**
- `deploy_preview()`: Creates or updates preview deployments for PRs
- `deploy_production()`: Creates or updates production deployment
- `cleanup_preview()`: Removes preview deployments when PRs are closed

### 2. `report_deployment.py`
**Purpose:** Generate deployment status reports for PR comments

**Features:**
- **Status Monitoring:** Check deployment and revision status
- **Markdown Reports:** Generate formatted status reports
- **PR Integration:** Create deployment status comments
- **Status Emojis:** Visual status indicators for different states

**Usage:**
```bash
# Generate preview deployment report
python report_deployment.py --deployment-name text2sql-agent-pr-123 --image-uri docker.io/user/repo:preview-123 --deployment-type preview

# Generate production deployment report
python report_deployment.py --deployment-name text2sql-agent-prod --image-uri docker.io/user/repo:latest --deployment-type production
```

**Status Indicators:**
- `⏳ AWAITING_DATABASE`: Deployment being set up
- `✅ READY`: Deployment is ready and accessible
- `🔨 BUILDING`: Docker image is being built
- `🚀 DEPLOYING`: Deployment in progress
- `❌ FAILED`: Deployment failed

### 3. `report_eval.py`
**Purpose:** Process LangSmith evaluation results and generate test reports

**Features:**
- **Evaluation Processing:** Parse LangSmith experiment results
- **Threshold Checking:** Validate scores against criteria
- **Markdown Reports:** Generate formatted evaluation reports
- **PR Integration:** Create evaluation result comments

**Usage:**
```bash
# Process all evaluation configs
python report_eval.py

# Process specific config files
python report_eval.py evaluation_config__*.json

# Process single config
python report_eval.py evaluation_config__my_experiment.json
```

**Configuration Format:**
```json
{
  "experiment_name": "my-experiment",
  "criteria": {
    "accuracy": ">=0.8",
    "response_time": "<2.0",
    "quality": ">=0.9"
  }
}
```

## Integration with Workflows

### Preview Deployment Flow
1. **`preview-deployment.yml`** calls `langgraph_api.py` to deploy preview
2. **`report_deployment.py`** generates status report
3. **GitHub Action** posts report as PR comment

### Production Deployment Flow
1. **`new-lgp-revision.yml`** calls `langgraph_api.py` to deploy production
2. **`report_deployment.py`** generates status report
3. **GitHub Action** posts report as PR comment

### Evaluation Flow
1. **`test-with-results.yml`** runs evaluation tests
2. **`report_eval.py`** processes results from LangSmith
3. **GitHub Action** posts evaluation report as PR comment

## Environment Variables

### GitHub Actions Context
In GitHub Actions, secrets are passed directly via command line arguments:
```bash
python langgraph_api.py \
  --secrets OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }} \
  --api-key ${{ secrets.LANGSMITH_API_KEY }}
```

### Local Development Context
For local development, you can use environment variables:
```bash
# Set environment variables
export LANGSMITH_API_KEY=your_key_here
export OPENAI_API_KEY=your_key_here

# Use with --secrets-from-env
python langgraph_api.py \
  --secrets-from-env OPENAI_API_KEY \
  --api-key $LANGSMITH_API_KEY
```

### Required Variables
- `LANGSMITH_API_KEY`: LangSmith API key for authentication
- `LANGSMITH_TRACING`: LangSmith tracing configuration (optional)
- `LANGSMITH_ENDPOINT`: LangSmith endpoint URL (optional)
- `OPENAI_API_KEY`: OpenAI API key (for deployment secrets)

## Error Handling

### Common Issues

1. **API Authentication Failures**
   - Verify `LANGSMITH_API_KEY` is correct
   - Check API endpoint URL configuration

2. **Deployment Not Found**
   - Ensure deployment name matches exactly
   - Check if deployment was created successfully

3. **Evaluation Config Errors**
   - Verify JSON format in config files
   - Check experiment names exist in LangSmith

4. **Docker Image Issues**
   - Verify image URI format
   - Check Docker registry permissions

## Development

### Adding New Scripts

When creating new scripts:

1. **Follow the established pattern:**
   - Use argparse for CLI interface
   - Include comprehensive error handling
   - Add verbose output options
   - Generate markdown reports for PR comments

2. **Environment Setup:**
   - Use environment variables for configuration
   - Include proper error messages for missing variables
   - Support both direct execution and GitHub Actions

3. **Documentation:**
   - Add docstrings for all functions
   - Include usage examples in help text
   - Update this README with new script information

### Testing Scripts

```bash
# Test API connectivity
python langgraph_api.py --action list-deployments --api-key $LANGSMITH_API_KEY

# Test deployment reporting
python report_deployment.py --deployment-name test-deployment --image-uri test:latest --deployment-type preview

# Test evaluation reporting
python report_eval.py --verbose
```

## File Dependencies

- **`langgraph_api.py`**: Standalone, requires `requests`
- **`report_deployment.py`**: Standalone, requires `requests`
- **`report_eval.py`**: Requires `langsmith` package

## Contributing

When modifying scripts:

1. **Maintain backward compatibility** for existing workflow usage
2. **Add comprehensive error handling** for edge cases
3. **Update documentation** to reflect changes
4. **Test with both local execution and GitHub Actions**
5. **Follow the established code style and patterns**
