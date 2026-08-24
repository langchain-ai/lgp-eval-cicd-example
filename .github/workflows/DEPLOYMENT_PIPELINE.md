# CI/CD pipeline

Automated testing, preview deployments and production deployments for the
text2sql agent, targeting [LangSmith Deployment](https://docs.langchain.com/langsmith/deployment).

## Hosting models

The control plane accepts a different deployment **source** per hosting model,
so this one setting determines the whole deployment path. Select it with the
`LANGSMITH_DEPLOYMENT_TARGET` repository variable.

| | `saas` | `self-hosted` |
|---|---|---|
| Control plane host | `https://api.host.langchain.com` (+ `eu.`/`apac.`/`aws.` regions) | `https://<your-langsmith-host>/api-host` |
| Source | `github` | `external_docker` |
| Docker build in CI | skipped | required |
| Extra config | `LANGSMITH_GITHUB_INTEGRATION_ID` | `CONTROL_PLANE_HOST`, optional `LANGSMITH_LISTENER_ID` |

## Workflows

### 1. `test-with-results.yml` — Comprehensive Tests

**Trigger:** pushes to `main`/`develop`, and every pull request.

| Job | What it does |
|---|---|
| `quality-checks` | ruff, black, isort, pre-commit |
| `test-coverage` | full suite with coverage |
| `deployment-tests` | control plane client for both hosting models (offline, no credentials) |
| `unit-tests` | individual nodes and utilities |
| `integration-tests` | full graph with mocked dependencies |
| `e2e-tests` | full graph against a real model |
| `evaluation-tests` | offline evaluations (pull requests only) |
| `evaluation-report` | posts the evaluation summary as a PR comment |
| `langgraph-dev-test` | boots a local Agent Server, checks `/ok` and that the graph is registered |
| `preview-deployment` | calls the preview workflow once everything above passes |

### 2. `preview-deployment.yml` — Preview Deployment

**Trigger:** `workflow_call` from the test workflow, or `workflow_dispatch`.

Builds and pushes a preview image (self-hosted only), then creates or updates
the preview deployment and comments the status on the pull request.

This is invoked as a reusable workflow rather than through `workflow_run`.
A `workflow_run` trigger executes in the base repository with access to every
secret, which would hand the deployment credentials to a fork's pull request.
Both jobs additionally skip pull requests raised from forks.

### 3. `new-lgp-revision.yml` — Production Deployment & Cleanup

**Trigger:** pull request closed against `main`.

| Job | Condition | What it does |
|---|---|---|
| `cleanup-preview` | always (non-fork) | deletes the pull request's preview deployment |
| `build-production-image` | merged **and** self-hosted | builds and pushes `:latest` and `main-<sha>` |
| `deploy-production` | merged | creates or revises the production deployment. Not gated on `cleanup-preview`: failing to delete a preview is housekeeping, not a reason to withhold a merged change |

## Using a different container registry

Only the self-hosted path builds images. It defaults to Docker Hub and is
registry-agnostic: set the `REGISTRY` and `IMAGE_NAME` repository variables and
the workflows follow.

| Registry | `REGISTRY` | Login |
|---|---|---|
| Docker Hub (default) | `docker.io` | `DOCKER_USERNAME` + a [Docker Hub access token](https://docs.docker.com/security/for-developers/access-tokens/) as `DOCKER_PASSWORD` |
| GitHub Container Registry | `ghcr.io` | `DOCKER_USERNAME` = `${{ github.actor }}`, `DOCKER_PASSWORD` = `${{ secrets.GITHUB_TOKEN }}` (add `packages: write`) |
| Amazon ECR | `<account>.dkr.ecr.<region>.amazonaws.com` | see below |
| Google Artifact Registry | `<region>-docker.pkg.dev` | `DOCKER_USERNAME` = `_json_key`, `DOCKER_PASSWORD` = the service account JSON |
| Azure ACR | `<name>.azurecr.io` | service principal ID and password |

ECR does not accept a static username and password, so replace the login step in
`preview-deployment.yml` and `new-lgp-revision.yml` with the official action:

```yaml
- name: Configure AWS credentials
  uses: aws-actions/configure-aws-credentials@v5
  with:
    role-to-assume: arn:aws:iam::<account>:role/<github-oidc-role>
    aws-region: <region>
- name: Log in to Amazon ECR
  uses: aws-actions/amazon-ecr-login@v2
```

Whichever you pick, the cluster running your Agent Servers must be able to pull
from it. For a private registry that usually means an `imagePullSecret` in the
deployment namespace, referenced via `LANGSMITH_LISTENER_ID` or the deployment's
`image_pull_secrets` resource spec.

## Sizing self-hosted previews

Every deployment provisions **four** workloads, each with its own CPU and memory
request: the agent, the queue, a Postgres StatefulSet and a Redis. Two defaults
catch people out:

* `queue_cpu` defaults to `cpu`, so `--cpu 1` reserves **two** cores, not one.
* `db_*` and `redis_*` are untouched by `--cpu`/`--memory-mb`. Lowering the agent
  and queue does nothing for the Postgres StatefulSet, which is often the pod
  that cannot be scheduled.

Size all four when a cluster is tight:

```bash
python .github/scripts/langgraph_api.py \
  --target self-hosted --action deploy-preview --pr-number 42 \
  --image-uri "$IMAGE" \
  --cpu 0.25 --memory-mb 768 --queue-cpu 0.2 --queue-memory-mb 512 \
  --resource-spec '{"db_cpu": 0.1, "db_memory_mb": 512, "redis_cpu": 0.1, "redis_memory_mb": 512}'
```

The control plane enforces minimums (for example `redis_memory_mb` must be at
least 512) and returns a `400` naming the offending field.

### A Postgres per pull request does not scale

The bigger problem is architectural: with a preview per pull request, every open
pull request costs its own Postgres **and** Redis. A handful of concurrent
previews will exhaust a small cluster, and the symptom is a revision that sits
in `DEPLOYING` until the platform's readiness timeout and then reports
`DEPLOY_FAILED` with no reason attached.

Point previews at shared datastores instead, by adding these as deployment
secrets or environment variables:

```bash
POSTGRES_URI_CUSTOM="postgresql://user:pass@shared-postgres:5432/preview_<pr>"
REDIS_URI_CUSTOM="redis://shared-redis:6379/<n>"
```

See the [self-hosted environment variables](https://docs.langchain.com/langsmith/env-var-self-hosted)
reference. If a *known-good* image also fails to deploy as a new deployment
while existing deployments stay healthy, the cluster is out of capacity rather
than anything being wrong with your image — that is the check to run first.

## Forwarding model credentials

Which secrets a deployment needs depends on how the agent reaches a model (see
[the README](../../README.md#-choosing-how-to-reach-a-model)):

```bash
# LLM Gateway -- no provider key. LANGSMITH_API_KEY is injected by Cloud and is
# a RESERVED name, so forwarding it is rejected with a 400.
--secret-env LLM_GATEWAY_BASE_URL --secret-env LLM_MODEL

# Anthropic directly
--secret-env ANTHROPIC_API_KEY

# OpenAI directly (the default)
--secret-env OPENAI_API_KEY
```

`--secret-env` names an environment variable to forward; the value is read from
the environment at deploy time and never appears in a log or on a command line.

## Deployment name length on self-hosted

**Self-hosted deployment names must be 21 characters or fewer.**

Self-hosted autoscaling uses KEDA, which derives an HPA named
`keda-hpa-<deployment-name>-<32-char-hash>`. Kubernetes caps object names at 63
characters, and `keda-hpa-` plus the separator plus the hash already consumes 42,
leaving 21.

Going over produces the worst failure mode in this whole pipeline. Every other
component reconciles — Postgres, Redis, the queue, the agent — the pods come up
healthy and **serve traffic normally**, but KEDA's admission webhook rejects the
autoscaler:

```
admission webhook "vscaledobject.kb.io" denied the request: HPA name
"keda-hpa-<name>-<hash>" is 64 characters long; must be no more than 63
```

The revision is then never marked ready and fails on the platform's timeout
after ten minutes with **no reason attached**. A deployment that works is
reported as failed.

The default prefix is `text2sql`, which leaves room for a six-digit pull request
number (`text2sql-pr-999999` derives a 60-character HPA). It was originally
`text2sql-agent`, which fits only up to PR #999:

| Prefix | PR #999 | PR #1000 | PR #999999 |
|---|---|---|---|
| `text2sql-agent` | 63 — works | **64 — breaks** | **66 — breaks** |
| `text2sql` (default) | 57 | 58 | 60 |

Override it with the `DEPLOYMENT_NAME_PREFIX` repository variable or
`--name-prefix`, keeping the full name at 21 characters or fewer.

`langgraph_api.py` validates this before deploying and fails immediately with an
explanation rather than letting it time out.

## Unblocking a stuck revision

A revision that is crash-looping or stuck building **holds the queue**: later
revisions sit in `QUEUED` behind it until it times out, so one bad deploy stalls
every push after it.

Cancel it and the queue drains immediately:

```bash
python .github/scripts/langgraph_api.py \
  --target saas --action interrupt --pr-number 42
```

The action no-ops when the newest revision has already settled, so it is safe to
run unconditionally before a deploy.

## Long-lived deployments

The pull-request convention (`<prefix>-pr-<n>`, `<prefix>-prod`) suits CI, but a
demo or a shared environment should not be named after a pull request. Pass
`--name` to set the name directly:

```bash
python .github/scripts/langgraph_api.py \
  --target self-hosted --action deploy-preview --name t2sql-demo \
  --image-uri "$IMAGE" --secret-env LLM_GATEWAY_API_KEY
```

`--name` works for every action, so the same deployment can be inspected with
`--action status --name t2sql-demo` and removed with `--action cleanup-preview
--name t2sql-demo`. The self-hosted length limit still applies when creating.

## Model credentials differ by hosting model

The LLM Gateway is a **Cloud** service (`gateway.smith.langchain.com`). That
matters more than it sounds:

| | Cloud (SaaS) | Self-Hosted |
|---|---|---|
| Platform-managed gateway routing (`route_through_gateway`) | supported | **not implemented — silently ignored** |
| Gateway with a forwarded key | `LLM_GATEWAY_API_KEY`, or the injected `LANGSMITH_API_KEY` | `LLM_GATEWAY_API_KEY` must be a **Cloud** key |
| Direct provider | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | same |

A self-hosted instance's own API key **cannot** call the gateway; it returns
`403`. The gateway only accepts Cloud keys, which is why `LLM_GATEWAY_API_KEY`
exists separately from `LANGSMITH_API_KEY`.

So a self-hosted deployment has two real options: forward a Cloud key, or give
it a provider key. There is no "the platform handles it" path — that is Cloud
only, and passing `--route-through-gateway` to a self-hosted control plane is
accepted by the CLI and then dropped on the floor by the API, so the CLI warns.

## Naming

- Preview deployments: `<prefix>-pr-<pr-number>` (deployment type `dev`), default `text2sql-pr-<n>`
- Production deployment: `<prefix>-prod` (deployment type `prod`), default `text2sql-prod`
- Preview images (self-hosted): `<registry>/<image>:preview-<pr-number>`
- Production images (self-hosted): `<registry>/<image>:latest`

Deployment URLs are read from the control plane's `url` field rather than being
constructed from the name — the serving hostname differs per hosting model.

## Scripts

Located in [`.github/scripts/`](.):

| Script | Purpose |
|---|---|
| `control_plane.py` | Control plane client: host resolution, auth, payload builders, revision polling |
| `langgraph_api.py` | CLI for `deploy-preview`, `deploy-production`, `cleanup-preview`, `status`, `wait`, `interrupt` |
| `report_deployment.py` | Renders the deployment status PR comment |
| `report_eval.py` | Renders the evaluation summary PR comment |
| `list_deployments.py` | Lists workspace deployments — useful for checking credentials |

All of them read credentials from the environment and print only secret *names*,
never values. Every request carries a timeout, and the control plane host is
validated as an absolute `https` URL before an API key is sent to it.

Test the client for both hosting models without any credentials:

```bash
make test-deployment
```

## Required configuration

See the [GitHub Actions setup section in the README](../../README.md#github-actions-setup)
for the full table of repository variables and secrets.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `401`/`403` from the control plane | `LANGSMITH_API_KEY` or `LANGSMITH_WORKSPACE_ID` wrong for this host |
| `external_docker` rejected | You are on SaaS; Cloud requires the `github` source |
| `github` source rejected | You are self-hosted; it requires `external_docker` |
| `Self-hosted deployments need an explicit control plane host` | Set `CONTROL_PLANE_HOST` to `https://<host>/api-host` |
| `Refusing to send an API key over plain http` | Use https, or pass `--allow-insecure-host` for an internal instance |
| `LANGSMITH_GITHUB_INTEGRATION_ID is required` | Fetch it from `GET /v1/integrations/github/install` |
| Preview never deploys | The pull request is from a fork — previews are skipped by design |
| Pods healthy and serving, but the revision reports `DEPLOY_FAILED` | The deployment name exceeds 21 characters, so KEDA's HPA name exceeds 63 and the autoscaler is rejected. See *Deployment name length on self-hosted* |
| `DEPLOY_FAILED` with no reason, after ~600s in `DEPLOYING` | The pods never became ready. Usually cluster capacity — see *Sizing self-hosted previews*. Confirm by deploying a known-good image as a new deployment: if that fails too, it is the cluster, not your image |
| `409 ... a project in LangSmith named X already exists` | See *Reopened pull requests* below |

### Reopened pull requests

Creating a deployment also creates a LangSmith tracing project with the same
name, but **deleting the deployment does not delete that project**. So after
`cleanup-preview` runs on PR close, the name stays claimed.

If the same pull request is later reopened, the preview deploy fails with:

```
409: There already exists a project in LangSmith named: text2sql-pr-<n>
```

The pipeline reports this as a `NameConflictError` explaining the fix rather
than a bare 409. To resolve it, delete the leftover tracing project of that name
in LangSmith (**Tracing Projects** → select → delete), then re-run the workflow.
Keep the project if you still want its traces, and deploy under a different name
instead.

Check credentials end to end with:

```bash
uv run python .github/scripts/list_deployments.py --target saas
```
