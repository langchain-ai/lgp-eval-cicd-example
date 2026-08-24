#!/usr/bin/env python3
"""Deploy this agent to LangSmith Deployment from CI.

Handles preview deployments, production deployments and preview cleanup against
either hosting model:

    # LangSmith Cloud (SaaS) -- builds from the GitHub repo, no Docker needed
    python .github/scripts/langgraph_api.py \
        --target saas --action deploy-preview --pr-number 42 \
        --repo-url https://github.com/org/repo --repo-ref my-branch

    # Self-hosted LangSmith -- deploys an image you already pushed
    CONTROL_PLANE_HOST=https://langsmith.internal/api-host \
    python .github/scripts/langgraph_api.py \
        --target self-hosted --action deploy-preview --pr-number 42 \
        --image-uri docker.io/org/agent:preview-42

Credentials are read from the environment, never from argv:

    LANGSMITH_API_KEY               required, authenticates to the control plane
    LANGSMITH_WORKSPACE_ID          required, the workspace to deploy into
    LANGSMITH_GITHUB_INTEGRATION_ID required for --target saas
    LANGSMITH_LISTENER_ID           optional, for --target self-hosted
    CONTROL_PLANE_HOST              required for --target self-hosted
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from control_plane import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    TARGET_SAAS,
    TARGETS,
    ControlPlaneClient,
    ControlPlaneError,
    build_saas_payload,
    build_self_hosted_payload,
    collect_secrets,
)
from control_plane import deployment_url as cp_deployment_url
from control_plane import (
    die,
    enable_line_buffering,
    print_deployment,
    resolve_host,
    source_for_target,
    validate_deployment_name,
    validate_new_deployment_name,
    write_github_output,
)

DEFAULT_SECRET_ENV_VARS = ["OPENAI_API_KEY"]


def parse_resource_overrides(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse the --resource-spec JSON blob."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ControlPlaneError(f"--resource-spec is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ControlPlaneError("--resource-spec must be a JSON object.")
    return parsed


def preview_name(prefix: str, pr_number: int, target: Optional[str] = None) -> str:
    """Build a preview deployment name.

    ``target`` applies the stricter self-hosted length rule, and is passed only
    when creating -- lookup, status and cleanup must still work for an existing
    deployment whose name predates the rule.
    """
    name = f"{prefix}-pr-{pr_number}"
    return (
        validate_new_deployment_name(name, target)
        if target
        else validate_deployment_name(name)
    )


def production_name(prefix: str, target: Optional[str] = None) -> str:
    name = f"{prefix}-prod"
    return (
        validate_new_deployment_name(name, target)
        if target
        else validate_deployment_name(name)
    )


def resolve_name(args, *, target: Optional[str] = None) -> str:
    """Work out which deployment this invocation refers to.

    An explicit --name wins; otherwise fall back to the pull-request convention.
    ``target`` is passed only when creating, so the stricter self-hosted length
    rule does not stop us finding or deleting an existing deployment.
    """
    if args.name:
        return (
            validate_new_deployment_name(args.name, target)
            if target
            else validate_deployment_name(args.name)
        )
    if args.pr_number:
        return preview_name(args.name_prefix, args.pr_number, target)
    return production_name(args.name_prefix, target)


def build_payload(args: argparse.Namespace, deployment_type: str) -> Dict[str, Any]:
    """Build the target-specific half of the create/patch request body."""
    if args.target == TARGET_SAAS:
        return build_saas_payload(
            integration_id=os.environ.get("LANGSMITH_GITHUB_INTEGRATION_ID", ""),
            repo_url=args.repo_url,
            repo_ref=args.repo_ref,
            langgraph_config_path=args.langgraph_config_path,
            deployment_type=deployment_type,
            build_on_push=args.build_on_push,
        )
    return build_self_hosted_payload(
        image_uri=args.image_uri,
        listener_id=os.environ.get("LANGSMITH_LISTENER_ID"),
        min_scale=args.min_scale,
        max_scale=args.max_scale,
        cpu=args.cpu,
        memory_mb=args.memory_mb,
        queue_cpu=args.queue_cpu,
        queue_memory_mb=args.queue_memory_mb,
        resource_overrides=parse_resource_overrides(args.resource_spec),
    )


def deploy(
    client: ControlPlaneClient,
    args: argparse.Namespace,
    name: str,
    deployment_type: str,
    secrets: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Create the deployment, or add a revision if it already exists."""
    payload = build_payload(args, deployment_type)
    existing = client.find_deployment(name)

    if existing:
        print(
            f"📝 Found existing deployment {name} ({existing['id']}); adding a revision."
        )
        # integration_id, repo_url, deployment_type and listener_id are all fixed
        # at creation, so only resend the part the API lets us change.
        source_config = payload.get("source_config") or {}
        mutable_config = (
            {"resource_spec": source_config["resource_spec"]}
            if "resource_spec" in source_config
            else None
        )
        deployment = client.patch_deployment(
            existing["id"],
            payload["source_revision_config"],
            secrets=secrets,
            source_config=mutable_config,
            route_through_gateway=args.route_through_gateway,
        )
    else:
        print(f"🆕 Creating deployment {name}.")
        deployment = client.create_deployment(
            name,
            source_for_target(args.target),
            payload["source_config"],
            payload["source_revision_config"],
            secrets,
            route_through_gateway=args.route_through_gateway,
        )

    print_deployment(deployment)

    revision_id = deployment.get("latest_revision_id")
    if args.wait and revision_id:
        print(f"⏳ Waiting for revision {revision_id} to deploy...")
        client.wait_for_revision(
            deployment["id"],
            revision_id,
            timeout=args.wait_timeout,
            interval=args.poll_interval,
        )
        # Re-read so the URL reflects the provisioned deployment.
        deployment = client.find_deployment(name) or deployment
        print("✅ Revision deployed.")
        print_deployment(deployment)

    write_github_output(
        deployment_id=str(deployment.get("id", "")),
        deployment_url=str(cp_deployment_url(deployment) or ""),
        deployment_name=name,
    )
    return deployment


def cleanup_preview(client: ControlPlaneClient, name: str) -> None:
    existing = client.find_deployment(name)
    if not existing:
        print(f"ℹ️  No deployment named {name}; nothing to clean up.")
        return
    print(f"🗑️  Deleting deployment {name} ({existing['id']}).")
    client.delete_deployment(existing["id"])
    print("✅ Deleted.")


def wait_for_latest(client: ControlPlaneClient, name: str, args) -> None:
    """Block until the deployment's newest revision settles.

    Useful when a revision already exists -- re-running a deploy just to watch
    it would create another revision.
    """
    deployment = client.find_deployment(name)
    if not deployment:
        die(f"No deployment named {name}.")
    revisions = client.list_revisions(deployment["id"])
    if not revisions:
        die(f"Deployment {name} has no revisions to wait on.")
    revision_id = revisions[0]["id"]
    print(f"⏳ Waiting for revision {revision_id}...")
    client.wait_for_revision(
        deployment["id"],
        revision_id,
        timeout=args.wait_timeout,
        interval=args.poll_interval,
    )
    print("✅ Revision deployed.")
    print_deployment(client.find_deployment(name) or deployment)


def interrupt_latest(client: ControlPlaneClient, name: str) -> None:
    """Cancel the newest revision if it is still in progress.

    Use this to unblock a deployment whose revision is stuck: later revisions
    queue behind it rather than superseding it.
    """
    deployment = client.find_deployment(name)
    if not deployment:
        die(f"No deployment named {name}.")
    revisions = client.list_revisions(deployment["id"])
    if not revisions:
        die(f"Deployment {name} has no revisions.")
    latest = revisions[0]
    status = latest.get("status", "UNKNOWN")
    if status in ("DEPLOYED", "INTERRUPTED") or "FAILED" in status:
        print(f"ℹ️  Revision {latest['id']} is already {status}; nothing to interrupt.")
        return
    print(f"🛑 Interrupting revision {latest['id']} ({status}).")
    client.interrupt_revision(deployment["id"], latest["id"])
    print("✅ Interrupted.")


def show_status(client: ControlPlaneClient, name: str) -> None:
    deployment = client.find_deployment(name)
    if not deployment:
        die(f"No deployment named {name}.")
    print_deployment(deployment)
    revisions = client.list_revisions(deployment["id"])
    if revisions:
        latest = revisions[0]
        print(f"🔁 Latest revision {latest.get('id')}: {latest.get('status')}")
        if latest.get("status_message"):
            print(f"   {latest['status_message']}")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default=os.environ.get("LANGSMITH_DEPLOYMENT_TARGET", TARGET_SAAS),
        help="Which hosting model to deploy to (default: %(default)s).",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=[
            "deploy-preview",
            "deploy-production",
            "cleanup-preview",
            "status",
            "wait",
            "interrupt",
        ],
    )
    parser.add_argument(
        "--name-prefix",
        default=os.environ.get("DEPLOYMENT_NAME_PREFIX", "text2sql"),
        help="Prefix for deployment names (default: %(default)s). Keep it short: "
        "self-hosted caps the whole name at 21 characters, see --help notes.",
    )
    parser.add_argument("--pr-number", type=int, help="PR number, for preview actions.")
    parser.add_argument(
        "--name",
        default=None,
        help="Exact deployment name, bypassing the <prefix>-pr-<n> convention. "
        "For long-lived deployments such as a demo that should not be named "
        "after a pull request.",
    )

    # Control plane location.
    parser.add_argument(
        "--control-plane-host",
        default=os.environ.get("CONTROL_PLANE_HOST"),
        help="Control plane base URL. Defaults to the SaaS host for --region; "
        "required for --target self-hosted (https://<host>/api-host).",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("LANGSMITH_REGION", "us"),
        help="LangSmith Cloud data region: us, eu, apac or aws-us (default: %(default)s).",
    )
    parser.add_argument(
        "--allow-insecure-host",
        action="store_true",
        help="Permit a plain http control plane host (internal instances only).",
    )

    # SaaS (github source).
    parser.add_argument(
        "--repo-url",
        default=os.environ.get("DEPLOYMENT_REPO_URL", ""),
        help="GitHub repository URL to deploy from (SaaS).",
    )
    parser.add_argument(
        "--repo-ref",
        default=os.environ.get("DEPLOYMENT_REPO_REF", "main"),
        help="Git branch or tag to deploy (SaaS, default: %(default)s).",
    )
    parser.add_argument(
        "--langgraph-config-path",
        default="langgraph.json",
        help="Path to langgraph.json in the repo (SaaS, default: %(default)s).",
    )
    parser.add_argument(
        "--build-on-push",
        action="store_true",
        help="Let the control plane rebuild on every push to the ref (SaaS).",
    )

    # Self-hosted (external_docker source).
    parser.add_argument(
        "--image-uri", default="", help="Docker image URI (self-hosted)."
    )
    parser.add_argument("--min-scale", type=int, default=1)
    parser.add_argument("--max-scale", type=int, default=1)
    parser.add_argument("--cpu", type=float, default=1)
    parser.add_argument("--memory-mb", type=int, default=1024)
    parser.add_argument(
        "--queue-cpu",
        type=float,
        default=None,
        help="CPU for the queue deployment (self-hosted). Defaults to --cpu, so "
        "leaving it unset reserves double the CPU you asked for.",
    )
    parser.add_argument(
        "--queue-memory-mb",
        type=int,
        default=None,
        help="Memory for the queue deployment (self-hosted). Defaults to --memory-mb.",
    )
    parser.add_argument(
        "--resource-spec",
        default=os.environ.get("DEPLOYMENT_RESOURCE_SPEC"),
        metavar="JSON",
        help="Extra resource_spec fields as JSON, merged over the flags above. "
        "A deployment provisions a Postgres and a Redis alongside the agent and "
        "queue, each with its own request, e.g. "
        '\'{"db_cpu": 0.25, "redis_cpu": 0.1, "db_storage_gi": 10}\'.',
    )

    # Secrets and polling.
    parser.add_argument(
        "--secret-env",
        action="append",
        metavar="NAME",
        help="Environment variable to forward as a deployment secret. Repeatable. "
        f"Default: {', '.join(DEFAULT_SECRET_ENV_VARS)}. Values are read from the "
        "environment and never logged.",
    )
    parser.add_argument(
        "--route-through-gateway",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Cloud only. Have the platform route OpenAI and Anthropic calls "
        "through the LangSmith LLM Gateway, so the deployment needs no provider "
        "key of its own. Self-hosted control planes do not implement this field "
        "and silently ignore it; forward a Cloud key as LLM_GATEWAY_API_KEY "
        "instead, or give the deployment a real provider key.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Block until the new revision reaches DEPLOYED.",
    )
    parser.add_argument("--wait-timeout", type=float, default=DEFAULT_WAIT_TIMEOUT)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)

    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    enable_line_buffering()

    # --name supplies the deployment directly, so a PR number is only required
    # when the name has to be derived from one.
    if (
        args.action in ("deploy-preview", "cleanup-preview")
        and not args.pr_number
        and not args.name
    ):
        die(f"--pr-number or --name is required for {args.action}.")
    if args.pr_number is not None and args.pr_number <= 0:
        die(f"--pr-number must be positive, got {args.pr_number}.")

    try:
        host = resolve_host(
            args.target, host=args.control_plane_host, region=args.region
        )
        client = ControlPlaneClient(
            host,
            os.environ.get("LANGSMITH_API_KEY", ""),
            os.environ.get("LANGSMITH_WORKSPACE_ID", ""),
            allow_insecure=args.allow_insecure_host,
        )
    except (ControlPlaneError, ValueError) as exc:
        die(str(exc))

    print(f"🎯 Target: {args.target}  •  control plane: {client.host}")

    if args.route_through_gateway and args.target != TARGET_SAAS:
        print(
            "⚠️  --route-through-gateway is a Cloud-only field. This self-hosted "
            "control plane does not implement it and will ignore it silently. "
            "Forward a Cloud key as LLM_GATEWAY_API_KEY, or set a provider key.",
            file=sys.stderr,
        )

    try:
        if args.action == "cleanup-preview":
            # No target: an existing deployment whose name predates the length
            # rule must still be deletable.
            cleanup_preview(client, resolve_name(args))
        elif args.action == "wait":
            name = resolve_name(args)
            wait_for_latest(client, name, args)
        elif args.action == "interrupt":
            name = resolve_name(args)
            interrupt_latest(client, name)
        elif args.action == "status":
            name = resolve_name(args)
            show_status(client, name)
        else:
            secrets = collect_secrets(args.secret_env or DEFAULT_SECRET_ENV_VARS)
            print(f"🔐 Forwarding secrets: {', '.join(s['name'] for s in secrets)}")
            if args.action == "deploy-preview":
                deploy(
                    client, args, resolve_name(args, target=args.target), "dev", secrets
                )
            else:
                deploy(
                    client,
                    args,
                    resolve_name(args, target=args.target),
                    "prod",
                    secrets,
                )
    except (ControlPlaneError, ValueError) as exc:
        die(str(exc))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
