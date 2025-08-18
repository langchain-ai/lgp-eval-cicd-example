// Enhanced LangSmith API client for production use
const core = require('@actions/core');

class LangSmithAPIClient {
  constructor(apiKey, options = {}) {
    this.apiKey = apiKey;
    this.baseUrl = options.baseUrl || process.env.LANGSMITH_ENDPOINT || 'https://api.smith.langchain.com';
    this.timeout = options.timeout || 30000; // 30 seconds
    this.retries = options.retries || 3;
    this.retryDelay = options.retryDelay || 1000; // 1 second

    if (!this.apiKey) {
      throw new Error('LangSmith API key is required');
    }
  }

  async makeRequest(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const config = {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
        'User-Agent': 'langsmith-eval-action/1.0.0',
        ...options.headers
      },
      signal: AbortSignal.timeout(this.timeout),
      ...options
    };

    let lastError;

    for (let attempt = 1; attempt <= this.retries; attempt++) {
      try {
        core.debug(`Making request to ${endpoint} (attempt ${attempt}/${this.retries})`);

        // Use node-fetch or built-in fetch if available
        const fetch = globalThis.fetch || require('node-fetch');
        const response = await fetch(url, config);

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        return data;

      } catch (error) {
        lastError = error;
        core.warning(`Request attempt ${attempt} failed: ${error.message}`);

        if (attempt < this.retries) {
          const delay = this.retryDelay * Math.pow(2, attempt - 1); // Exponential backoff
          core.debug(`Retrying in ${delay}ms...`);
          await new Promise(resolve => setTimeout(resolve, delay));
        }
      }
    }

    throw new Error(`Failed to make request after ${this.retries} attempts: ${lastError.message}`);
  }

  async getProject(projectName) {
    try {
      return await this.makeRequest(`/sessions?name=${encodeURIComponent(projectName)}&limit=1`);
    } catch (error) {
      throw new Error(`Failed to get project ${projectName}: ${error.message}`);
    }
  }

  async listRuns(projectName, options = {}) {
    try {
      const params = new URLSearchParams({
        session: projectName,
        limit: options.limit || 100,
        offset: options.offset || 0
      });

      if (options.runType) {
        params.append('run_type', options.runType);
      }

      if (options.startTime) {
        params.append('start_time', options.startTime.toISOString());
      }

      if (options.endTime) {
        params.append('end_time', options.endTime.toISOString());
      }

      const response = await this.makeRequest(`/runs?${params.toString()}`);
      return response.runs || [];
    } catch (error) {
      throw new Error(`Failed to list runs for project ${projectName}: ${error.message}`);
    }
  }

  async getFeedback(runIds, options = {}) {
    try {
      if (!Array.isArray(runIds) || runIds.length === 0) {
        return [];
      }

      // LangSmith API may have limits on batch size, so chunk if needed
      const chunkSize = options.chunkSize || 50;
      const allFeedback = [];

      for (let i = 0; i < runIds.length; i += chunkSize) {
        const chunk = runIds.slice(i, i + chunkSize);
        const params = new URLSearchParams();

        chunk.forEach(id => params.append('run', id));

        if (options.feedbackKey) {
          params.append('key', options.feedbackKey);
        }

        const response = await this.makeRequest(`/feedback?${params.toString()}`);
        allFeedback.push(...(response.feedback || []));
      }

      return allFeedback;
    } catch (error) {
      throw new Error(`Failed to get feedback: ${error.message}`);
    }
  }

  async getRunStats(projectName) {
    try {
      const params = new URLSearchParams({
        session: projectName
      });

      return await this.makeRequest(`/runs/stats?${params.toString()}`);
    } catch (error) {
      throw new Error(`Failed to get run stats for project ${projectName}: ${error.message}`);
    }
  }

  async searchProjects(nameContains) {
    try {
      const params = new URLSearchParams();
      if (nameContains) {
        params.append('name_contains', nameContains);
      }

      const response = await this.makeRequest(`/sessions?${params.toString()}`);
      return response.sessions || [];
    } catch (error) {
      throw new Error(`Failed to search projects: ${error.message}`);
    }
  }

  // Helper method to process evaluation results
  async processEvaluationResults(experimentName, criteria = {}) {
    try {
      core.info(`🔍 Processing results for experiment: ${experimentName}`);

      // Get runs for this experiment
      const runs = await this.listRuns(experimentName);

      if (runs.length === 0) {
        core.warning(`No runs found for experiment: ${experimentName}`);
        return {
          experiment_name: experimentName,
          runs_count: 0,
          feedback_summary: {},
          criteria_results: {}
        };
      }

      const runIds = runs.map(run => run.id);
      core.debug(`Found ${runIds.length} runs for experiment ${experimentName}`);

      // Get all feedback for these runs
      const feedback = await this.getFeedback(runIds);

      // Group feedback by key and calculate averages
      const feedbackByKey = {};
      for (const fb of feedback) {
        if (fb.score !== null && fb.score !== undefined) {
          if (!feedbackByKey[fb.key]) {
            feedbackByKey[fb.key] = [];
          }
          feedbackByKey[fb.key].push(fb.score);
        }
      }

      const feedbackSummary = {};
      const criteriaResults = {};

      for (const [key, scores] of Object.entries(feedbackByKey)) {
        const avgScore = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
        feedbackSummary[key] = {
          average: avgScore,
          count: scores.length,
          min: Math.min(...scores),
          max: Math.max(...scores)
        };

        // Check against criteria if defined
        if (criteria[key]) {
          try {
            const { parseThreshold } = require('./index');
            const { op, value } = parseThreshold(criteria[key]);
            const passed = avgScore !== null ? op(avgScore, value) : false;

            criteriaResults[key] = {
              threshold: criteria[key],
              score: avgScore,
              passed: passed,
              status: passed ? 'PASS' : 'FAIL'
            };
          } catch (error) {
            core.warning(`Invalid threshold for ${key}: ${criteria[key]}`);
            criteriaResults[key] = {
              threshold: criteria[key],
              score: avgScore,
              passed: false,
              status: 'ERROR',
              error: error.message
            };
          }
        }
      }

      return {
        experiment_name: experimentName,
        runs_count: runs.length,
        feedback_summary: feedbackSummary,
        criteria_results: criteriaResults,
        total_criteria: Object.keys(criteria).length,
        passed_criteria: Object.values(criteriaResults).filter(r => r.passed).length,
        failed_criteria: Object.values(criteriaResults).filter(r => !r.passed).length
      };

    } catch (error) {
      core.error(`Failed to process evaluation results: ${error.message}`);
      return {
        experiment_name: experimentName,
        error: error.message
      };
    }
  }

  // Health check method
  async healthCheck() {
    try {
      await this.makeRequest('/sessions?limit=1');
      return true;
    } catch (error) {
      core.error(`LangSmith API health check failed: ${error.message}`);
      return false;
    }
  }
}

module.exports = { LangSmithAPIClient };
