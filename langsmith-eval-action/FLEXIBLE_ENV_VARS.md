# 🔧 Flexible Environment Variables - New Feature

Following the pattern from `langgraph-deploy-action`, the LangSmith Evaluation Action now supports flexible environment variables through the `environment-variables` input.

## ✨ What's New

### Before (Limited Individual Keys)
```yaml
- uses: langchain-ai/langsmith-eval-action@v1
  with:
    openai-api-key: ${{ secrets.OPENAI_API_KEY }}
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    # Only supported specific API keys
```

### After (Unlimited Flexibility)
```yaml
- uses: langchain-ai/langsmith-eval-action@v1
  with:
    environment-variables: |
      {
        "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
        "GOOGLE_API_KEY": "${{ secrets.GOOGLE_API_KEY }}",
        "COHERE_API_KEY": "${{ secrets.COHERE_API_KEY }}",
        "CUSTOM_MODEL_ENDPOINT": "${{ secrets.CUSTOM_MODEL_ENDPOINT }}",
        "AZURE_OPENAI_ENDPOINT": "${{ secrets.AZURE_OPENAI_ENDPOINT }}",
        "DATABASE_URL": "${{ secrets.DATABASE_URL }}",
        "EVALUATION_MODE": "comprehensive",
        "MAX_RETRIES": "5",
        "TIMEOUT_SECONDS": "600"
      }
```

## 🚀 Key Benefits

1. **Unlimited Environment Variables** - Set any number of environment variables
2. **Multiple LLM Providers** - Support for OpenAI, Anthropic, Google, Cohere, Azure, custom endpoints
3. **Custom Configuration** - Set evaluation modes, timeouts, database URLs, etc.
4. **Two Formats Supported** - JSON and YAML-style formats
5. **Backward Compatible** - Old individual API key inputs still work
6. **Priority System** - Environment variables input overrides individual inputs

## 📝 Format Examples

### JSON Format (Recommended)
```yaml
environment-variables: |
  {
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    "CUSTOM_VAR": "custom_value"
  }
```

### YAML-Style Format
```yaml
environment-variables: |
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  CUSTOM_VAR: custom_value
```

## 🔄 Migration Guide

### Your Current Setup
```yaml
# In .github/workflows/test-with-results.yml
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
  LANGSMITH_TRACING: ${{ secrets.LANGSMITH_TRACING }}
  LANGSMITH_ENDPOINT: ${{ secrets.LANGSMITH_ENDPOINT }}
```

### Migrated to New Action
```yaml
- uses: langchain-ai/langsmith-eval-action@v1
  with:
    langsmith-api-key: ${{ secrets.LANGSMITH_API_KEY }}
    environment-variables: |
      {
        "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
        "LANGSMITH_TRACING": "${{ secrets.LANGSMITH_TRACING }}",
        "LANGSMITH_ENDPOINT": "${{ secrets.LANGSMITH_ENDPOINT }}"
      }
```

## 🎯 Common Use Cases

### Multiple LLM Providers
```yaml
environment-variables: |
  {
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    "GOOGLE_API_KEY": "${{ secrets.GOOGLE_API_KEY }}",
    "COHERE_API_KEY": "${{ secrets.COHERE_API_KEY }}"
  }
```

### Azure OpenAI Configuration
```yaml
environment-variables: |
  {
    "AZURE_OPENAI_ENDPOINT": "${{ secrets.AZURE_OPENAI_ENDPOINT }}",
    "AZURE_OPENAI_API_KEY": "${{ secrets.AZURE_OPENAI_API_KEY }}",
    "AZURE_OPENAI_API_VERSION": "2024-02-15-preview",
    "OPENAI_API_TYPE": "azure"
  }
```

### Database and External Services
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

### Custom Evaluation Configuration
```yaml
environment-variables: |
  {
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "EVALUATION_MODE": "comprehensive",
    "MIN_SCORE_THRESHOLD": "0.85",
    "MAX_CONCURRENT_EVALUATIONS": "3",
    "ENABLE_DETAILED_LOGGING": "true",
    "CUSTOM_EVALUATOR_ENDPOINT": "${{ secrets.CUSTOM_EVALUATOR_ENDPOINT }}"
  }
```

## 🔒 Security Features

- **No Logging of Values** - Only environment variable keys are logged, never values
- **Secure Variable Handling** - All values are handled securely and not exposed in logs
- **GitHub Secrets Integration** - Seamless integration with GitHub Secrets
- **Backward Compatibility** - Existing individual API key inputs remain secure

## ⚙️ Implementation Details

### Priority Order (Highest to Lowest)
1. `environment-variables` input (JSON/YAML)
2. Individual API key inputs (`openai-api-key`, `anthropic-api-key`)
3. Existing environment variables

### Parsing Logic
- First attempts JSON parsing
- Falls back to YAML-style parsing if JSON fails
- Supports comments in YAML format (lines starting with `#`)
- Handles quoted and unquoted values
- Preserves colons in URLs and complex values

### Error Handling
- Graceful degradation if parsing fails
- Warning messages for invalid formats
- Continues with individual inputs if environment-variables fails
- No action failure due to parsing errors

## 🧪 Testing

The new functionality includes comprehensive tests:
- JSON format parsing
- YAML format parsing
- Backward compatibility
- Priority system
- Error handling
- Security (no value logging)

Run tests with:
```bash
node test.js
```

## 📚 Full Documentation

See [README.md](README.md#flexible-environment-variables) for complete documentation and examples.

---

This enhancement makes the LangSmith Evaluation Action significantly more flexible while maintaining full backward compatibility with your existing workflows! 🚀
