const core = require('@actions/core');
const github = require('@actions/github');
const { execSync, spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const glob = require('glob');

// Operator map for threshold comparisons
const OP_MAP = {
  '>': (a, b) => a > b,
  '<': (a, b) => a < b,
  '>=': (a, b) => a >= b,
  '<=': (a, b) => a <= b,
  '==': (a, b) => a === b,
  '!=': (a, b) => a !== b,
};

function parseThreshold(thresholdStr) {
  const operators = Object.keys(OP_MAP).sort((a, b) => b.length - a.length);

  for (const symbol of operators) {
    if (thresholdStr.startsWith(symbol)) {
      const value = parseFloat(thresholdStr.slice(symbol.length));
      return { op: OP_MAP[symbol], value };
    }
  }

  throw new Error(`Invalid threshold format: ${thresholdStr}`);
}

function formatScore(value) {
  return value !== null && value !== undefined ? value.toFixed(2) : 'N/A';
}

function validateInputs() {
  const maxConcurrency = parseInt(core.getInput('max-concurrency') || '10');

  if (maxConcurrency < 1 || maxConcurrency > 50) {
    throw new Error(`max-concurrency must be between 1 and 50, got: ${maxConcurrency}`);
  }

  // Validate threshold expressions in config files if available
  const configPattern = core.getInput('config-pattern') || 'evaluation_config__*.json';
  try {
    const configFiles = glob.sync(configPattern);
    for (const configFile of configFiles) {
      if (fs.existsSync(configFile)) {
        const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
        if (config.criteria) {
          for (const [key, threshold] of Object.entries(config.criteria)) {
            try {
              parseThreshold(threshold);
            } catch (error) {
              core.warning(`Invalid threshold for ${key} in ${configFile}: ${threshold}`);
            }
          }
        }
      }
    }
  } catch (error) {
    core.debug(`Could not validate config files: ${error.message}`);
  }
}

function parseEnvironmentVariables(envVarsInput, openaiApiKey, anthropicApiKey) {
  const envVars = {};

  // Handle new environment-variables input format
  if (envVarsInput) {
    try {
      // Try to parse as JSON first
      const parsed = JSON.parse(envVarsInput);
      Object.assign(envVars, parsed);
    } catch (jsonError) {
      try {
        // Try to parse as YAML-style key: value
        const lines = envVarsInput.split('\n');
        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed && !trimmed.startsWith('#')) {
            const [key, ...valueParts] = trimmed.split(':');
            if (key && valueParts.length > 0) {
              const value = valueParts.join(':').trim().replace(/^["']|["']$/g, '');
              envVars[key.trim()] = value;
            }
          }
        }
      } catch (yamlError) {
        core.warning(`Failed to parse environment-variables input: ${jsonError.message}`);
        core.warning(`Also failed as YAML: ${yamlError.message}`);
      }
    }
  }

  // Backward compatibility: add individual API keys if provided
  if (openaiApiKey && !envVars.OPENAI_API_KEY) {
    envVars.OPENAI_API_KEY = openaiApiKey;
  }

  if (anthropicApiKey && !envVars.ANTHROPIC_API_KEY) {
    envVars.ANTHROPIC_API_KEY = anthropicApiKey;
  }

  // Environment fallbacks for common keys
  if (!envVars.OPENAI_API_KEY && process.env.OPENAI_API_KEY) {
    envVars.OPENAI_API_KEY = process.env.OPENAI_API_KEY;
  }

  if (!envVars.ANTHROPIC_API_KEY && process.env.ANTHROPIC_API_KEY) {
    envVars.ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
  }

  return envVars;
}

class LangSmithEvaluationRunner {
  constructor(options = {}) {
    this.apiKey = options.langsmithApiKey || core.getInput('langsmith-api-key', { required: true });
    this.workingDir = options.workingDirectory || core.getInput('working-directory') || '.';
    this.testCommand = options.testCommand || core.getInput('test-command') || 'pytest -m evaluator';
    this.pythonVersion = options.pythonVersion || core.getInput('python-version') || '3.11';
    this.installCommand = options.installCommand || core.getInput('install-command') || 'pip install langsmith';
    this.maxConcurrency = parseInt(options.maxConcurrency || core.getInput('max-concurrency') || '10');

    // Set LangSmith API key
    process.env.LANGSMITH_API_KEY = this.apiKey;

    // Parse and set environment variables
    const envVarsInput = options.environmentVariables || core.getInput('environment-variables');
    const openaiApiKey = options.openaiApiKey || core.getInput('openai-api-key');
    const anthropicApiKey = options.anthropicApiKey || core.getInput('anthropic-api-key');

    const envVars = parseEnvironmentVariables(envVarsInput, openaiApiKey, anthropicApiKey);

    if (Object.keys(envVars).length > 0) {
      core.info(`🔧 Setting ${Object.keys(envVars).length} environment variables`);
      // Don't log the actual values for security
      core.info(`🔐 Environment variables: ${Object.keys(envVars).join(', ')}`);

      // Set all environment variables
      for (const [key, value] of Object.entries(envVars)) {
        process.env[key] = value;
      }
    }

    // Set additional LangSmith-specific environment variables
    const datasetName = options.datasetName || core.getInput('dataset-name');
    if (datasetName) {
      process.env.LANGSMITH_DATASET_NAME = datasetName;
    }

    const experimentPrefix = options.experimentPrefix || core.getInput('experiment-prefix');
    if (experimentPrefix) {
      process.env.LANGSMITH_EXPERIMENT_PREFIX = experimentPrefix;
    }

    process.env.LANGSMITH_MAX_CONCURRENCY = this.maxConcurrency.toString();
  }

  async setupPython() {
    try {
      core.info('🐍 Setting up Python environment...');

      // Check if running in GitHub Actions (python should already be available)
      if (process.env.GITHUB_ACTIONS) {
        core.info('✅ Using pre-installed Python in GitHub Actions');
        return;
      }

      // For local development, try to use existing python
      try {
        const pythonVersion = execSync('python --version 2>&1', { encoding: 'utf-8' }).trim();
        core.info(`✅ Found Python: ${pythonVersion}`);
      } catch (error) {
        try {
          const python3Version = execSync('python3 --version 2>&1', { encoding: 'utf-8' }).trim();
          core.info(`✅ Found Python3: ${python3Version}`);
          // Use python3 if python is not available
          this.pythonCommand = 'python3';
        } catch (error) {
          throw new Error('Python not found. Please install Python 3.11 or higher.');
        }
      }
    } catch (error) {
      throw new Error(`Failed to setup Python: ${error.message}`);
    }
  }

  async installDependencies() {
    try {
      core.info('📦 Installing dependencies...');
      const command = this.installCommand;

      core.info(`Running: ${command}`);
      execSync(command, {
        cwd: this.workingDir,
        stdio: 'inherit',
        env: { ...process.env }
      });

      core.info('✅ Dependencies installed successfully');
    } catch (error) {
      throw new Error(`Failed to install dependencies: ${error.message}`);
    }
  }

  async runEvaluations() {
    try {
      core.info('🧪 Running evaluation tests...');
      core.info(`Working directory: ${this.workingDir}`);
      core.info(`Test command: ${this.testCommand}`);

      const startTime = Date.now();

      execSync(this.testCommand, {
        cwd: this.workingDir,
        stdio: 'inherit',
        env: { ...process.env }
      });

      const duration = ((Date.now() - startTime) / 1000).toFixed(1);
      core.info(`✅ Evaluations completed successfully in ${duration}s`);

      return true;
    } catch (error) {
      core.error(`❌ Evaluation tests failed: ${error.message}`);
      // Don't throw here - we want to continue to report generation
      return false;
    }
  }

  findConfigFiles() {
    const pattern = core.getInput('config-pattern') || 'evaluation_config__*.json';
    const configFiles = glob.sync(pattern, { cwd: this.workingDir });

    if (configFiles.length === 0) {
      core.warning(`No evaluation config files found matching pattern: ${pattern}`);
      return [];
    }

    core.info(`📋 Found ${configFiles.length} evaluation config files`);
    return configFiles.map(file => path.resolve(this.workingDir, file));
  }

  async processConfigFile(configPath, langsmithClient = null) {
    try {
      core.info(`🔍 Processing config: ${path.basename(configPath)}`);

      const configContent = fs.readFileSync(configPath, 'utf8');
      const config = JSON.parse(configContent);

      const experimentName = config.experiment_name;
      const criteria = config.criteria || {};

      if (!experimentName) {
        core.warning(`No experiment_name found in ${configPath}`);
        return null;
      }

      let evaluationResults = null;

      // If LangSmith client is available, fetch real results
      if (langsmithClient) {
        try {
          evaluationResults = await langsmithClient.processEvaluationResults(experimentName, criteria);
        } catch (error) {
          core.warning(`Failed to fetch LangSmith results for ${experimentName}: ${error.message}`);
        }
      }

      return {
        experiment_name: experimentName,
        criteria: criteria,
        config_file: configPath,
        evaluation_results: evaluationResults,
        status: evaluationResults ? 'completed' : 'processed'
      };

    } catch (error) {
      core.error(`Failed to process config ${configPath}: ${error.message}`);
      return {
        experiment_name: path.basename(configPath),
        error: error.message,
        config_file: configPath
      };
    }
  }

  async generateReport(results) {
    const reportFile = core.getInput('report-file') || 'eval_report.md';
    const reportPath = path.resolve(this.workingDir, reportFile);

    core.info(`📝 Generating evaluation report: ${reportPath}`);

    let content = '# 🧪 LangSmith Evaluation Results\n\n';
    content += `*Generated at ${new Date().toISOString().replace('T', ' ').replace(/\\.\\d{3}Z$/, ' UTC')}*\n\n`;

    let totalPassed = 0;
    let totalFailed = 0;
    let totalExperiments = 0;
    const experimentNames = [];

    if (results.length === 0) {
      content += '## ⚠️ No Results Found\n\n';
      content += 'No evaluation config files were found or processed successfully.\n\n';
    } else {
      content += `## 📊 Summary\n\n`;
      content += `- **Total Experiments**: ${results.length}\n`;

      for (const result of results) {
        totalExperiments++;
        const experimentName = result.experiment_name || 'Unknown';
        experimentNames.push(experimentName);

        if (result.error) {
          content += `### ❌ ${experimentName}\n\n`;
          content += `**Error**: ${result.error}\n\n`;
          totalFailed++;
          continue;
        }

        const evalResults = result.evaluation_results;

        if (!result.criteria || Object.keys(result.criteria).length === 0) {
          content += `### ℹ️ ${experimentName}\n\n`;
          content += 'No evaluation criteria defined for this experiment.\n\n';
          if (evalResults && evalResults.runs_count) {
            content += `**Runs Count**: ${evalResults.runs_count}\n\n`;
          }
          continue;
        }

        content += `### 📋 ${experimentName}\n\n`;

        // Add run count if available
        if (evalResults && evalResults.runs_count) {
          content += `**Runs**: ${evalResults.runs_count}\n\n`;
        }

        content += '| Feedback Key | Avg Score | Threshold | Pass? |\n';
        content += '|--------------|-----------|-----------|-------|\n';

        let experimentPassed = 0;
        let experimentFailed = 0;

        for (const [key, threshold] of Object.entries(result.criteria)) {
          let scoreDisplay = 'N/A';
          let statusDisplay = '⏳ Pending';

          // Check if we have real results
          if (evalResults && evalResults.criteria_results && evalResults.criteria_results[key]) {
            const criteriaResult = evalResults.criteria_results[key];
            scoreDisplay = formatScore(criteriaResult.score);
            statusDisplay = criteriaResult.passed ? '✅' : '❌';

            if (criteriaResult.passed) {
              experimentPassed++;
            } else {
              experimentFailed++;
            }
          } else if (evalResults && evalResults.feedback_summary && evalResults.feedback_summary[key]) {
            // We have feedback but no criteria check
            const summary = evalResults.feedback_summary[key];
            scoreDisplay = formatScore(summary.average);
            statusDisplay = '–';
          }

          content += `| ${key} | ${scoreDisplay} | ${threshold} | ${statusDisplay} |\n`;
        }

        content += '\n';

        // Add experiment summary
        if (experimentPassed > 0 || experimentFailed > 0) {
          content += `**✅ ${experimentPassed} Passed, ❌ ${experimentFailed} Failed**\n\n`;
          totalPassed += experimentPassed > 0 && experimentFailed === 0 ? 1 : 0;
          totalFailed += experimentFailed > 0 ? 1 : 0;
        } else {
          content += '*No evaluation results available yet.*\n\n';
        }
      }

      content += `\n---\n\n`;
      content += `**Overall**: ${totalPassed} experiments passed, ${totalFailed} experiments failed\n\n`;
    }

    content += '---\n';
    content += '*Generated by [LangSmith Evaluation Action](https://github.com/langchain-ai/langsmith-eval-action)*\n';

    fs.writeFileSync(reportPath, content, 'utf8');

    core.info(`✅ Report generated: ${reportPath}`);

    return {
      reportPath,
      totalExperiments,
      totalPassed,
      totalFailed,
      experimentNames
    };
  }

  async postPRComment(reportPath) {
    try {
      if (!github.context.payload.pull_request) {
        core.info('ℹ️ Not a pull request context, skipping PR comment');
        return;
      }

      const prComment = core.getInput('pr-comment');
      if (prComment !== 'true') {
        core.info('ℹ️ PR comments disabled, skipping');
        return;
      }

      const token = process.env.GITHUB_TOKEN;
      if (!token) {
        core.warning('GITHUB_TOKEN not available, cannot post PR comment');
        return;
      }

      const reportContent = fs.readFileSync(reportPath, 'utf8');

      const octokit = github.getOctokit(token);

      await octokit.rest.issues.createComment({
        ...github.context.repo,
        issue_number: github.context.payload.pull_request.number,
        body: reportContent
      });

      core.info('✅ Posted evaluation results as PR comment');
    } catch (error) {
      core.warning(`Failed to post PR comment: ${error.message}`);
    }
  }
}

// Import the enhanced LangSmith client
const { LangSmithAPIClient } = require('./langsmith-client');

async function main() {
  try {
    // Validate inputs first
    validateInputs();

    const action = core.getInput('action', { required: true });

    core.info(`🚀 Starting LangSmith Evaluation Action: ${action}`);

    const runner = new LangSmithEvaluationRunner();

    if (action === 'run-evaluations') {
      await handleRunEvaluations(runner);
    } else if (action === 'generate-report') {
      await handleGenerateReport(runner);
    } else {
      throw new Error(`Unknown action: ${action}`);
    }

    core.info(`🎉 Action completed successfully!`);

  } catch (error) {
    core.error(`❌ Action failed with error: ${error.message}`);

    // Provide helpful context based on error type
    if (error.message.includes('max-concurrency')) {
      core.error('💡 Check that max-concurrency is between 1 and 50');
    } else if (error.message.includes('threshold')) {
      core.error('💡 Check that threshold expressions use valid operators: >=, >, <=, <, ==, !=');
    } else if (error.message.includes('langsmith-api-key')) {
      core.error('💡 Verify LANGSMITH_API_KEY secret is set and has correct permissions');
    } else if (error.message.includes('pytest')) {
      core.error('💡 Check that evaluation tests are properly marked with @pytest.mark.evaluator');
    } else if (error.message.includes('config')) {
      core.error('💡 Verify evaluation config files are valid JSON with experiment_name and criteria');
    }

    core.setFailed(error.message);
  }
}

async function handleRunEvaluations(runner) {
  await runner.setupPython();
  await runner.installDependencies();
  const evalSuccess = await runner.runEvaluations();

  // Generate report after running evaluations
  const configFiles = runner.findConfigFiles();
  const langsmithClient = await createLangSmithClient(runner.apiKey);

  const results = await Promise.all(
    configFiles.map(file => runner.processConfigFile(file, langsmithClient))
  );
  const filteredResults = results.filter(r => r !== null);

  const reportResult = await runner.generateReport(filteredResults);
  await runner.postPRComment(reportResult.reportPath);

  // Set outputs
  setActionOutputs(reportResult);

  const overallStatus = evalSuccess ? 'success' : 'warning';
  core.setOutput('overall-status', overallStatus);

  if (!evalSuccess) {
    const failOnThreshold = core.getInput('fail-on-threshold') === 'true';
    if (failOnThreshold) {
      core.setFailed('Evaluations failed to meet threshold criteria');
    } else {
      core.warning('Some evaluations failed, but continuing (fail-on-threshold is false)');
    }
  }

  core.info(`📊 Processed ${reportResult.totalExperiments} experiments`);
}

async function handleGenerateReport(runner) {
  const configFiles = runner.findConfigFiles();
  const langsmithClient = await createLangSmithClient(runner.apiKey);

  const results = await Promise.all(
    configFiles.map(file => runner.processConfigFile(file, langsmithClient))
  );
  const filteredResults = results.filter(r => r !== null);

  const reportResult = await runner.generateReport(filteredResults);
  await runner.postPRComment(reportResult.reportPath);

  // Set outputs
  setActionOutputs(reportResult);
  core.setOutput('overall-status', 'success');

  core.info(`📊 Processed ${reportResult.totalExperiments} experiments`);
}

async function createLangSmithClient(apiKey) {
  try {
    const client = new LangSmithAPIClient(apiKey);
    const isHealthy = await client.healthCheck();
    if (!isHealthy) {
      core.warning('LangSmith API health check failed, proceeding without real-time results');
      return null;
    }
    return client;
  } catch (error) {
    core.warning(`Failed to initialize LangSmith client: ${error.message}`);
    return null;
  }
}

function setActionOutputs(reportResult) {
  core.setOutput('report-file', reportResult.reportPath);
  core.setOutput('experiment-names', JSON.stringify(reportResult.experimentNames));
  core.setOutput('total-experiments', reportResult.totalExperiments.toString());
  core.setOutput('passed-experiments', reportResult.totalPassed.toString());
  core.setOutput('failed-experiments', reportResult.totalFailed.toString());
}

// Export for testing
module.exports = {
  LangSmithEvaluationRunner,
  LangSmithAPIClient,
  parseThreshold,
  formatScore,
  parseEnvironmentVariables
};

// Run the action
if (require.main === module) {
  main();
}
