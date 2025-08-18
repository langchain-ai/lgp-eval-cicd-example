# LangGraph Deploy Action 🚀

A GitHub Action for deploying and managing LangGraph applications with automated preview and production environments.

## Features

- 🚀 **Deploy to LangGraph** - Deploy Docker images to LangGraph Platform
- 🔄 **Preview Environments** - Automatic preview deployments for pull requests
- 🏭 **Production Deployments** - Managed production releases
- 🧹 **Automatic Cleanup** - Remove preview deployments when PRs are closed
- 📊 **Deployment Reports** - Generate markdown reports for PR comments
- ⚙️ **Configurable Resources** - Set CPU, memory, and scaling parameters

## Usage

### Deploy Preview Environment

```yaml
name: Preview Deployment
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  deploy-preview:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to LangGraph
        uses: langchain-ai/langgraph-deploy-action@v1
        with:
          action: 'deploy-preview'
          api-key: ${{ secrets.LANGSMITH_API_KEY }}
          image-uri: 'docker.io/your-org/your-app:preview-${{ github.event.pull_request.number }}'
          pr-number: ${{ github.event.pull_request.number }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

### Deploy to Production

```yaml
name: Production Deployment
on:
  push:
    branches: [main]

jobs:
  deploy-production:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Production
        uses: langchain-ai/langgraph-deploy-action@v1
        with:
          action: 'deploy-production'
          api-key: ${{ secrets.LANGSMITH_API_KEY }}
          image-uri: 'docker.io/your-org/your-app:latest'
          deployment-name: 'my-app-prod'  # Custom name
          app-name: 'my-app'              # Used for auto-generated names
          secrets: |
            {
              "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}"
            }
```

### Cleanup Preview Environment

```yaml
name: Cleanup Preview
on:
  pull_request:
    types: [closed]

jobs:
  cleanup-preview:
    runs-on: ubuntu-latest
    steps:
      - name: Cleanup Preview Deployment
        uses: langchain-ai/langgraph-deploy-action@v1
        with:
          action: 'cleanup-preview'
          api-key: ${{ secrets.LANGSMITH_API_KEY }}
          pr-number: ${{ github.event.pull_request.number }}
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `action` | Action to perform: `deploy-preview`, `deploy-production`, `cleanup-preview` | ✅ | |
| `api-key` | LangSmith API key for LangGraph deployments | ✅ | |
| `image-uri` | Docker image URI to deploy | ✅ | |
| `pr-number` | Pull request number (required for preview actions) | ⚠️ | |
| `deployment-name` | Name of the deployment (for production) | ❌ | Auto-generated |
| `app-name` | Application name for auto-generated deployment names | ❌ | `langgraph-app` |
| `openai-api-key` | OpenAI API key to inject as secret (DEPRECATED: use `secrets`) | ❌ | From environment |
| `secrets` | JSON object or YAML string of secrets to inject | ❌ | `{}` |
| `base-url` | LangGraph API base URL (supports multiple formats) | ❌ | `https://gtm.smith.langchain.dev/api-host/` |
| `resource-cpu` | CPU allocation for deployment (1-16) | ❌ | `1` |
| `resource-memory` | Memory allocation in MB (128-32768) | ❌ | `1024` |
| `min-scale` | Minimum scale instances (1-100) | ❌ | `1` |
| `max-scale` | Maximum scale instances (1-100) | ❌ | `1` |

## Outputs

| Output | Description |
|--------|-------------|
| `deployment-id` | ID of the created/updated deployment |
| `deployment-url` | URL of the deployment |
| `deployment-status` | Status of the deployment |
| `report-file` | Path to generated deployment report markdown file |

## Complete Workflow Example

```yaml
name: LangGraph CI/CD Pipeline

on:
  pull_request:
    types: [opened, synchronize, reopened, closed]
  push:
    branches: [main]

jobs:
  # Build Docker image
  build:
    runs-on: ubuntu-latest
    if: github.event.action != 'closed'
    outputs:
      image-uri: ${{ steps.build.outputs.image-uri }}
    steps:
      - uses: actions/checkout@v4

      - name: Build Docker image
        id: build
        run: |
          IMAGE_URI="docker.io/your-org/your-app:${{ github.sha }}"
          docker build -t $IMAGE_URI .
          docker push $IMAGE_URI
          echo "image-uri=$IMAGE_URI" >> $GITHUB_OUTPUT

  # Deploy preview environment
  deploy-preview:
    needs: build
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request' && github.event.action != 'closed'
    steps:
      - name: Deploy Preview
        id: deploy
        uses: langchain-ai/langgraph-deploy-action@v1
        with:
          action: 'deploy-preview'
          api-key: ${{ secrets.LANGSMITH_API_KEY }}
          image-uri: ${{ needs.build.outputs.image-uri }}
          pr-number: ${{ github.event.pull_request.number }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}

      - name: Comment PR with deployment status
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const comment = fs.readFileSync('${{ steps.deploy.outputs.report-file }}', 'utf8');

            await github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: comment
            });

  # Cleanup preview environment
  cleanup-preview:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request' && github.event.action == 'closed'
    steps:
      - name: Cleanup Preview
        uses: langchain-ai/langgraph-deploy-action@v1
        with:
          action: 'cleanup-preview'
          api-key: ${{ secrets.LANGSMITH_API_KEY }}
          pr-number: ${{ github.event.pull_request.number }}

  # Deploy to production
  deploy-production:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - name: Deploy to Production
        uses: langchain-ai/langgraph-deploy-action@v1
        with:
          action: 'deploy-production'
          api-key: ${{ secrets.LANGSMITH_API_KEY }}
          image-uri: ${{ needs.build.outputs.image-uri }}
          deployment-name: 'my-app-prod'
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

## Supported API Endpoints

The action supports different LangGraph API endpoints via the `base-url` input:

### LangGraph Host API Endpoints:
- **GTM Format**: `https://gtm.smith.langchain.dev/api-host/` (default)
- **Direct Format**: `https://api.host.langchain.com/`

### Usage with Custom Endpoints:

```yaml
- name: Deploy with Custom Endpoint
  uses: langchain-ai/langgraph-deploy-action@v1
  with:
    action: 'deploy-production'
    api-key: ${{ secrets.LANGSMITH_API_KEY }}
    image-uri: 'docker.io/your-org/your-app:latest'
    base-url: 'https://api.host.langchain.com/'  # Custom endpoint
    secrets: |
      {
        "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}"
      }
```

The action automatically normalizes URLs and appends `/v2` if needed.

## Multiple Secrets Support

The action supports injecting multiple API keys and secrets into your deployment via the `secrets` input.

### JSON Format:

```yaml
- name: Deploy with Multiple Secrets
  uses: langchain-ai/langgraph-deploy-action@v1
  with:
    action: 'deploy-production'
    api-key: ${{ secrets.LANGSMITH_API_KEY }}
    image-uri: 'docker.io/your-org/your-app:latest'
    secrets: |
      {
        "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
        "PINECONE_API_KEY": "${{ secrets.PINECONE_API_KEY }}",
        "DATABASE_URL": "${{ secrets.DATABASE_URL }}"
      }
```

### YAML-Style Format:

```yaml
- name: Deploy with YAML-Style Secrets
  uses: langchain-ai/langgraph-deploy-action@v1
  with:
    action: 'deploy-production'
    api-key: ${{ secrets.LANGSMITH_API_KEY }}
    image-uri: 'docker.io/your-org/your-app:latest'
    secrets: |
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

### Backward Compatibility:

The old `openai-api-key` input is still supported but deprecated:

```yaml
# Old format (still works)
- uses: langchain-ai/langgraph-deploy-action@v1
  with:
    openai-api-key: ${{ secrets.OPENAI_API_KEY }}  # DEPRECATED

# New format (recommended)
- uses: langchain-ai/langgraph-deploy-action@v1
  with:
    secrets: '{"OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}"}'
```

## Environment Variables

The action will automatically use these environment variables if the corresponding inputs are not provided:

- `OPENAI_API_KEY` - OpenAI API key for deployment secrets
- `LANGSMITH_API_KEY` - LangSmith API key (can be provided via input instead)

## Deployment Naming Convention

- **Preview deployments**: `{app-name}-pr-{number}` (e.g., `my-app-pr-123`)
- **Production deployments**: `{deployment-name}` or `{app-name}-prod`

### Customizing Deployment Names:

```yaml
# Custom app name affects auto-generated names
- uses: langchain-ai/langgraph-deploy-action@v1
  with:
    app-name: 'my-text2sql'  # Results in: my-text2sql-pr-123, my-text2sql-prod

# Or specify exact production deployment name
- uses: langchain-ai/langgraph-deploy-action@v1
  with:
    deployment-name: 'text2sql-production'  # Exact name for production
```

## Generated Reports

The action generates markdown deployment reports that include:

- 🚀 Deployment status with emoji indicators
- 🔗 Deployment URL
- 📦 Docker image information
- ⏰ Creation and update timestamps
- 📊 Resource allocation details

## Input Validation

The action validates all inputs to prevent deployment failures:

- **resource-cpu**: Must be between 1 and 16 (integer values)
- **resource-memory**: Must be between 128 and 32768 MB
- **min-scale/max-scale**: Must be between 1-100, with min-scale ≤ max-scale
- **secrets**: Must be valid JSON or YAML format
- **image-uri**: Required for deployment actions

Invalid inputs will cause the action to fail early with helpful error messages.

## Error Handling

The action includes comprehensive error handling for:

- ❌ Invalid API credentials
- ❌ Missing required parameters
- ❌ Deployment failures
- ❌ Network connectivity issues

All errors are reported with clear, actionable messages.

## Contributing

1. Fork this repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions:

1. Check the [troubleshooting guide](#troubleshooting)
2. Search existing [GitHub Issues](https://github.com/langchain-ai/langgraph-deploy-action/issues)
3. Open a new issue with detailed information

## Troubleshooting

### Common Issues

**Authentication Error**
```
❌ Action failed: Failed to list deployments: 401
```
- Verify your `LANGSMITH_API_KEY` is correct
- Check that the API key has deployment permissions

**Missing PR Number**
```
❌ Action failed: PR number is required for preview deployment
```
- Ensure you're passing `pr-number: ${{ github.event.pull_request.number }}`
- Verify the action is triggered on pull request events

**Image URI Invalid**
```
❌ Action failed: Failed to create deployment: 400
```
- Verify your Docker image URI is correct and accessible
- Ensure the image exists in the registry
- Check that authentication is configured for private registries
