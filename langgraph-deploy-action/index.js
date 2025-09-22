const core = require('@actions/core');
const github = require('@actions/github');
const axios = require('axios');
const fs = require('fs');

function validateInputs() {
  const resourceCpu = parseInt(core.getInput('resource-cpu') || '1');
  const resourceMemory = parseInt(core.getInput('resource-memory') || '1024');
  const minScale = parseInt(core.getInput('min-scale') || '1');
  const maxScale = parseInt(core.getInput('max-scale') || '1');

  if (resourceCpu < 1 || resourceCpu > 16) {
    throw new Error(`resource-cpu must be between 1 and 16, got: ${resourceCpu}`);
  }

  if (resourceMemory < 128 || resourceMemory > 32768) {
    throw new Error(`resource-memory must be between 128 and 32768 MB, got: ${resourceMemory}`);
  }

  if (minScale < 1 || minScale > 100) {
    throw new Error(`min-scale must be between 1 and 100, got: ${minScale}`);
  }

  if (maxScale < 1 || maxScale > 100) {
    throw new Error(`max-scale must be between 1 and 100, got: ${maxScale}`);
  }

  if (minScale > maxScale) {
    throw new Error(`min-scale (${minScale}) cannot be greater than max-scale (${maxScale})`);
  }
}

function parseSecrets(secretsInput, openaiApiKey) {
  const secrets = {};

  // Handle new secrets input format
  if (secretsInput) {
    try {
      // Try to parse as JSON first
      const parsed = JSON.parse(secretsInput);
      Object.assign(secrets, parsed);
    } catch (jsonError) {
      try {
        // Try to parse as YAML-style key: value
        const lines = secretsInput.split('\n');
        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed && !trimmed.startsWith('#')) {
            const [key, ...valueParts] = trimmed.split(':');
            if (key && valueParts.length > 0) {
              const value = valueParts.join(':').trim().replace(/^["']|["']$/g, '');
              secrets[key.trim()] = value;
            }
          }
        }
      } catch (yamlError) {
        core.warning(`Failed to parse secrets input: ${jsonError.message}`);
        core.warning(`Also failed as YAML: ${yamlError.message}`);
      }
    }
  }

  // Backward compatibility: add openai-api-key if provided
  if (openaiApiKey && !secrets.OPENAI_API_KEY) {
    secrets.OPENAI_API_KEY = openaiApiKey;
  }

  // Environment fallback for OPENAI_API_KEY
  if (!secrets.OPENAI_API_KEY && process.env.OPENAI_API_KEY) {
    secrets.OPENAI_API_KEY = process.env.OPENAI_API_KEY;
  }

  return secrets;
}

class LangGraphAPI {
  constructor(apiKey, baseUrl = 'https://gtm.smith.langchain.dev/api-host/v2') {
    this.apiKey = apiKey;
    // Ensure baseUrl doesn't have trailing slash and has correct path
    this.baseUrl = this.normalizeBaseUrl(baseUrl);
    this.headers = {
      'X-Api-Key': apiKey,
      'Content-Type': 'application/json'
    };
  }

  normalizeBaseUrl(baseUrl) {
    // Remove trailing slash
    let normalized = baseUrl.replace(/\/$/, '');

    // Handle different endpoint formats
    if (normalized.includes('api.host.langchain.com')) {
      // Direct format: https://api.host.langchain.com/v2
      if (!normalized.endsWith('/v2')) {
        normalized += '/v2';
      }
    } else if (normalized.includes('gtm.smith.langchain.dev/api-host')) {
      // GTM format: https://gtm.smith.langchain.dev/api-host/v2
      if (!normalized.endsWith('/v2')) {
        normalized += '/v2';
      }
    }

    return normalized;
  }

  async listDeployments(nameContains = null) {
    try {
      const params = nameContains ? { name_contains: nameContains } : {};
      const response = await axios.get(`${this.baseUrl}/deployments`, {
        headers: this.headers,
        params
      });
      return response.data;
    } catch (error) {
      throw new Error(`Failed to list deployments: ${error.response?.status} - ${error.response?.data}`);
    }
  }

  async createDeployment(name, imageUri, secretsObj = {}, resourceSpec = {}) {
    const defaultResourceSpec = {
      min_scale: parseInt(core.getInput('min-scale') || '1'),
      max_scale: parseInt(core.getInput('max-scale') || '1'),
      cpu: parseInt(core.getInput('resource-cpu') || '1'),
      memory_mb: parseInt(core.getInput('resource-memory') || '1024')
    };

    // Convert secrets object to LangGraph format
    const secrets = Object.entries(secretsObj).map(([name, value]) => ({
      name,
      value
    }));

    const requestBody = {
      name,
      source: 'external_docker',
      source_config: {
        integration_id: null,
        repo_url: null,
        deployment_type: null,
        build_on_push: null,
        custom_url: null,
        resource_spec: { ...defaultResourceSpec, ...resourceSpec }
      },
      source_revision_config: {
        repo_ref: null,
        langgraph_config_path: null,
        image_uri: imageUri
      },
      secrets
    };

    try {
      core.info(`📤 Creating deployment: ${name}`);
      core.info(`📦 Image: ${imageUri}`);

      const response = await axios.post(`${this.baseUrl}/deployments`, requestBody, {
        headers: this.headers
      });

      return response.data;
    } catch (error) {
      throw new Error(`Failed to create deployment: ${error.response?.status} - ${error.response?.data}`);
    }
  }

  async updateDeployment(deploymentId, imageUri) {
    const requestBody = {
      source_revision_config: {
        repo_ref: null,
        langgraph_config_path: null,
        image_uri: imageUri
      }
    };

    try {
      core.info(`🔄 Updating deployment: ${deploymentId}`);
      core.info(`📦 New image: ${imageUri}`);

      const response = await axios.patch(`${this.baseUrl}/deployments/${deploymentId}`, requestBody, {
        headers: this.headers
      });

      return response.data;
    } catch (error) {
      throw new Error(`Failed to update deployment: ${error.response?.status} - ${error.response?.data}`);
    }
  }

  async deleteDeployment(deploymentId) {
    try {
      await axios.delete(`${this.baseUrl}/deployments/${deploymentId}`, {
        headers: this.headers
      });
      return true;
    } catch (error) {
      throw new Error(`Failed to delete deployment: ${error.response?.status} - ${error.response?.data}`);
    }
  }

  async findDeploymentByName(nameContains) {
    const deployments = await this.listDeployments(nameContains);

    for (const deployment of deployments.resources || []) {
      if (deployment.name && deployment.name.includes(nameContains)) {
        return deployment;
      }
    }

    return null;
  }

  getDeploymentUrl(deploymentName) {
    return `https://${deploymentName}.langchain.dev`;
  }
}

class DeploymentReporter {
  constructor(api) {
    this.api = api;
  }

  formatStatusEmoji(status) {
    const statusMap = {
      'AWAITING_DATABASE': '⏳',
      'READY': '✅',
      'UNUSED': '⏸️',
      'AWAITING_DELETE': '🗑️',
      'UNKNOWN': '❓'
    };
    return statusMap[status] || '❓';
  }

  async generateDeploymentReport(deploymentName, imageUri, deploymentType = 'preview') {
    try {
      const deployment = await this.api.findDeploymentByName(deploymentName);

      if (!deployment) {
        return {
          deployment_name: deploymentName,
          status: 'NOT_FOUND',
          error: 'Deployment not found'
        };
      }

      const imageInfo = {
        uri: imageUri,
        tag: imageUri.includes(':') ? imageUri.split(':').pop() : 'latest',
        registry: imageUri.includes('/') ? imageUri.split('/')[0] : 'unknown'
      };

      return {
        deployment_name: deploymentName,
        deployment_id: deployment.id,
        status: deployment.status || 'UNKNOWN',
        status_emoji: this.formatStatusEmoji(deployment.status || 'UNKNOWN'),
        url: this.api.getDeploymentUrl(deploymentName),
        created_at: deployment.created_at,
        updated_at: deployment.updated_at,
        deployment_type: deploymentType,
        image_info: imageInfo
      };
    } catch (error) {
      return {
        deployment_name: deploymentName,
        error: error.message
      };
    }
  }

  writeMarkdownReport(report, outputFile = 'deployment_report.md') {
    let content = '# 🚀 LangGraph Deployment Status\n\n';

    if (report.error) {
      content += '### ❌ Deployment Failed\n\n';
      content += `**Error:** ${report.error}\n\n`;
    } else {
      const deploymentType = (report.deployment_type || 'unknown').charAt(0).toUpperCase() + (report.deployment_type || 'unknown').slice(1);
      const statusEmoji = report.status_emoji || '❓';
      const status = report.status || 'UNKNOWN';

      content += `### ${statusEmoji} ${deploymentType} Deployment: \`${report.deployment_name}\`\n\n`;
      content += '| Property | Value |\n';
      content += '|----------|-------|\n';
      content += `| **Status** | ${statusEmoji} ${status} |\n`;
      content += `| **URL** | [${report.url}](${report.url}) |\n`;
      content += `| **Deployment ID** | \`${report.deployment_id}\` |\n`;

      if (report.image_info) {
        content += `| **Image** | \`${report.image_info.uri}\` |\n`;
        content += `| **Tag** | \`${report.image_info.tag}\` |\n`;
      }

      if (report.created_at) {
        const createdDate = new Date(report.created_at).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
        content += `| **Created** | ${createdDate} |\n`;
      }

      content += '\n';

      if (status === 'READY') {
        content += '🎉 **Deployment is ready and accessible!**\n\n';
      } else if (status === 'AWAITING_DATABASE') {
        content += '⏳ **Deployment is being set up...**\n\n';
      }
    }

    content += '---\n';
    content += `*Report generated at ${new Date().toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC')}*\n`;

    fs.writeFileSync(outputFile, content);
    return outputFile;
  }
}

async function deployPreview(api, prNumber, imageUri, secrets, appName = 'langgraph-app') {
  const deploymentName = `${appName}-pr-${prNumber}`;

  core.info(`🔍 Looking for existing preview deployment: ${deploymentName}`);

  const existingDeployment = await api.findDeploymentByName(deploymentName);

  let result;
  if (existingDeployment) {
    core.info(`📝 Found existing preview deployment: ${existingDeployment.id}`);
    result = await api.updateDeployment(existingDeployment.id, imageUri);
    core.info('✅ Preview deployment updated successfully!');
  } else {
    core.info(`🆕 Creating new preview deployment: ${deploymentName}`);
    result = await api.createDeployment(deploymentName, imageUri, secrets);
    core.info('✅ Preview deployment created successfully!');
  }

  const deploymentUrl = api.getDeploymentUrl(deploymentName);
  core.info(`🔗 URL: ${deploymentUrl}`);

  return {
    deploymentId: result.id,
    deploymentUrl,
    deploymentName,
    status: result.status || 'UNKNOWN'
  };
}

async function deployProduction(api, deploymentName, imageUri, secrets, appName = 'langgraph-app') {
  const prodName = deploymentName || `${appName}-prod`;

  core.info(`🔍 Looking for production deployment: ${prodName}`);

  const existingDeployment = await api.findDeploymentByName(prodName);

  let result;
  if (existingDeployment) {
    core.info(`📝 Found existing production deployment: ${existingDeployment.id}`);
    result = await api.updateDeployment(existingDeployment.id, imageUri);
    core.info('✅ Production deployment updated successfully!');
  } else {
    core.info(`🆕 Creating new production deployment: ${prodName}`);
    result = await api.createDeployment(prodName, imageUri, secrets);
    core.info('✅ Production deployment created successfully!');
  }

  const deploymentUrl = api.getDeploymentUrl(prodName);
  core.info(`🔗 URL: ${deploymentUrl}`);

  return {
    deploymentId: result.id,
    deploymentUrl,
    deploymentName: prodName,
    status: result.status || 'UNKNOWN'
  };
}

async function cleanupPreview(api, prNumber, appName = 'langgraph-app') {
  const deploymentName = `${appName}-pr-${prNumber}`;

  core.info(`🔍 Looking for preview deployment to cleanup: ${deploymentName}`);

  const existingDeployment = await api.findDeploymentByName(deploymentName);

  if (existingDeployment) {
    core.info(`🗑️ Deleting preview deployment: ${existingDeployment.id}`);
    await api.deleteDeployment(existingDeployment.id);
    core.info('✅ Preview deployment deleted successfully!');
    return { deleted: true, deploymentName };
  } else {
    core.info(`ℹ️ No preview deployment found for PR #${prNumber}`);
    return { deleted: false, deploymentName };
  }
}

async function main() {
  try {
    // Validate inputs first
    validateInputs();

    // Get inputs
    const action = core.getInput('action', { required: true });
    const apiKey = core.getInput('api-key', { required: true });
    const imageUri = core.getInput('image-uri');
    const prNumber = core.getInput('pr-number');
    const deploymentName = core.getInput('deployment-name');
    const appName = core.getInput('app-name') || 'langgraph-app';
    const openaiApiKey = core.getInput('openai-api-key') || process.env.OPENAI_API_KEY;
    const secretsInput = core.getInput('secrets');
    const baseUrl = core.getInput('base-url') || 'https://gtm.smith.langchain.dev/api-host/v2';

    // Parse secrets with backward compatibility
    const secrets = parseSecrets(secretsInput, openaiApiKey);

    if (Object.keys(secrets).length > 0) {
      core.info(`📋 Found ${Object.keys(secrets).length} secrets to inject`);
      // Don't log the actual secrets for security
      core.info(`🔐 Secret keys: ${Object.keys(secrets).join(', ')}`);
    }

    core.info(`🚀 Starting LangGraph Deploy Action: ${action}`);

    // Initialize API client
    const api = new LangGraphAPI(apiKey, baseUrl);
    const reporter = new DeploymentReporter(api);

    let result;
    let reportFile;

    switch (action) {
      case 'deploy-preview':
        if (!prNumber || !imageUri) {
          throw new Error('PR number and image URI are required for preview deployment');
        }
        result = await deployPreview(api, prNumber, imageUri, secrets, appName);

        // Generate report
        const previewReport = await reporter.generateDeploymentReport(
          result.deploymentName,
          imageUri,
          'preview'
        );
        reportFile = reporter.writeMarkdownReport(previewReport, 'deployment_report.md');
        break;

      case 'deploy-production':
        if (!imageUri) {
          throw new Error('Image URI is required for production deployment');
        }
        result = await deployProduction(api, deploymentName, imageUri, secrets, appName);

        // Generate report
        const prodReport = await reporter.generateDeploymentReport(
          result.deploymentName,
          imageUri,
          'production'
        );
        reportFile = reporter.writeMarkdownReport(prodReport, 'deployment_report.md');
        break;

      case 'cleanup-preview':
        if (!prNumber) {
          throw new Error('PR number is required for preview cleanup');
        }
        result = await cleanupPreview(api, prNumber, appName);
        break;

      default:
        throw new Error(`Unknown action: ${action}`);
    }

    // Set outputs
    if (result.deploymentId) {
      core.setOutput('deployment-id', result.deploymentId);
    }
    if (result.deploymentUrl) {
      core.setOutput('deployment-url', result.deploymentUrl);
    }
    if (result.status) {
      core.setOutput('deployment-status', result.status);
    }
    if (reportFile) {
      core.setOutput('report-file', reportFile);
    }

    core.info('🎉 Action completed successfully!');

  } catch (error) {
    core.error(`❌ Action failed with error: ${error.message}`);

    // Provide helpful context based on error type
    if (error.message.includes('resource-')) {
      core.error('💡 Check resource allocation: CPU (1-16), Memory (128-32768 MB), Scale (1-100)');
    } else if (error.message.includes('scale')) {
      core.error('💡 Verify min-scale <= max-scale and both are within valid ranges (1-100)');
    } else if (error.message.includes('api-key') || error.message.includes('401')) {
      core.error('💡 Verify LANGSMITH_API_KEY secret is set and has deployment permissions');
    } else if (error.message.includes('image-uri') || error.message.includes('400')) {
      core.error('💡 Check that Docker image URI is correct and accessible');
    } else if (error.message.includes('pr-number')) {
      core.error('💡 Ensure PR number is provided for preview deployments');
    } else if (error.message.includes('deployment')) {
      core.error('💡 Check LangGraph API endpoint and deployment configuration');
    }

    core.setFailed(error.message);
  }
}

// Run the action
if (require.main === module) {
  main();
}

module.exports = {
  LangGraphAPI,
  DeploymentReporter,
  deployPreview,
  deployProduction,
  cleanupPreview
};
