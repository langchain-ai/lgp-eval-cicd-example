#!/usr/bin/env python3
"""
Generic LangGraph API helper script for deployment management.
Handles preview deployments, production deployments, and cleanup with configurable parameters.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import requests


class LangGraphAPI:
    """LangGraph API client for deployment management."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        # Default to the standard LangChain hosted API, but allow override
        self.base_url = base_url or "https://api.host.langchain.com/v2"
        # Fix header name to match working script
        self.headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    def list_deployments(self, name_contains: Optional[str] = None) -> Dict[str, Any]:
        """List deployments with optional name filter."""
        params = {}
        if name_contains:
            params["name_contains"] = name_contains

        response = requests.get(
            f"{self.base_url}/deployments", headers=self.headers, params=params
        )

        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Failed to list deployments: {response.status_code}")
            print(f"Response: {response.text}")
            sys.exit(1)

    def create_deployment(
        self,
        name: str,
        image_uri: str,
        secrets: List[Dict[str, str]] = None,
        resource_spec: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new deployment."""
        if secrets is None:
            secrets = []

        if resource_spec is None:
            resource_spec = {
                "min_scale": 1,
                "max_scale": 1,
                "cpu": 1,
                "memory_mb": 1024,
            }

        # Match the working script structure exactly, but for external_docker
        request_body = {
            "name": name,
            "source": "external_docker",
            "source_config": {
                "integration_id": None,
                "repo_url": None,
                "deployment_type": None,
                "build_on_push": None,
                "custom_url": None,
                "resource_spec": resource_spec,
            },
            "source_revision_config": {
                "repo_ref": None,
                "langgraph_config_path": None,
                "image_uri": image_uri,
            },
            "secrets": secrets,
        }

        print(f"📤 Sending deployment request to: {self.base_url}/deployments")
        print(f"📦 Payload: {request_body}")

        response = requests.post(
            f"{self.base_url}/deployments", headers=self.headers, json=request_body
        )

        print(f"📥 Response status: {response.status_code}")
        print(f"📥 Response headers: {dict(response.headers)}")

        if response.status_code in [200, 201]:
            return response.json()
        else:
            print(f"❌ Failed to create deployment: {response.status_code}")
            print(f"Response: {response.text}")
            print(f"Request URL: {response.url}")
            print(f"Request headers: {dict(response.request.headers)}")
            sys.exit(1)

    def update_deployment(self, deployment_id: str, image_uri: str) -> Dict[str, Any]:
        """Update deployment with new image (creates new revision)."""
        request_body = {
            "source_revision_config": {
                "repo_ref": None,
                "langgraph_config_path": None,
                "image_uri": image_uri,
            }
        }

        print(
            f"📤 Sending update request to: {self.base_url}/deployments/{deployment_id}"
        )
        print(f"📦 Payload: {request_body}")

        response = requests.patch(
            f"{self.base_url}/deployments/{deployment_id}",
            headers=self.headers,
            json=request_body,
        )

        print(f"📥 Response status: {response.status_code}")
        print(f"📥 Response headers: {dict(response.headers)}")

        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Failed to update deployment: {response.status_code}")
            print(f"Response: {response.text}")
            print(f"Request URL: {response.url}")
            print(f"Request headers: {dict(response.request.headers)}")
            sys.exit(1)

    def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a deployment."""
        response = requests.delete(
            f"{self.base_url}/deployments/{deployment_id}", headers=self.headers
        )

        if response.status_code == 204:
            return True
        else:
            print(f"❌ Failed to delete deployment: {response.status_code}")
            print(f"Response: {response.text}")
            return False

    def find_deployment_by_name(self, name_contains: str) -> Optional[Dict[str, Any]]:
        """Find a deployment by name pattern."""
        deployments = self.list_deployments(name_contains=name_contains)

        for deployment in deployments.get("resources", []):
            if name_contains in deployment.get("name", ""):
                return deployment

        return None


def parse_secrets(
    secrets_args: List[str], secrets_from_env: List[str]
) -> List[Dict[str, str]]:
    """Parse secrets from command line arguments and environment variables."""
    secrets = []

    # Parse secrets from command line (format: KEY=VALUE)
    for secret in secrets_args:
        if "=" in secret:
            key, value = secret.split("=", 1)
            secrets.append({"name": key, "value": value})
        else:
            print(f"⚠️  Warning: Secret '{secret}' should be in format KEY=VALUE")

    # Parse secrets from environment variables
    for env_var in secrets_from_env:
        value = os.environ.get(env_var)
        if value:
            secrets.append({"name": env_var, "value": value})
        else:
            print(f"⚠️  Warning: Environment variable '{env_var}' not found")

    return secrets


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from JSON file."""
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        return config
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Failed to load config file {config_path}: {e}")
        sys.exit(1)


def deploy_preview(
    api: LangGraphAPI,
    pr_number: int,
    image_uri: str,
    app_name: str,
    secrets: List[Dict[str, str]],
    resource_spec: Dict[str, Any],
    domain: str,
    protocol: str,
    deployment_name: str = None,
):
    """Deploy or update a preview deployment."""
    if deployment_name is None:
        deployment_name = f"{app_name}-pr-{pr_number}"

    print(f"🔍 Looking for existing preview deployment: {deployment_name}")

    # Check if preview deployment already exists
    existing_deployment = api.find_deployment_by_name(deployment_name)

    if existing_deployment:
        print(f"📝 Found existing preview deployment: {existing_deployment['id']}")
        print(f"🔄 Updating with new image: {image_uri}")

        result = api.update_deployment(existing_deployment["id"], image_uri)
        print("✅ Preview deployment updated successfully!")
        print(f"📦 Deployment ID: {result['id']}")
        print(f"🔗 URL: {protocol}://{deployment_name}.{domain}")

    else:
        print(f"🆕 Creating new preview deployment: {deployment_name}")
        print(f"📦 Image: {image_uri}")

        result = api.create_deployment(
            deployment_name, image_uri, secrets, resource_spec
        )
        print("✅ Preview deployment created successfully!")
        print(f"📦 Deployment ID: {result['id']}")
        print(f"🔗 URL: {protocol}://{deployment_name}.{domain}")


def cleanup_preview(
    api: LangGraphAPI, pr_number: int, app_name: str, deployment_name: str = None
):
    """Clean up a preview deployment."""
    if deployment_name is None:
        deployment_name = f"{app_name}-pr-{pr_number}"

    print(f"🔍 Looking for preview deployment to cleanup: {deployment_name}")

    existing_deployment = api.find_deployment_by_name(deployment_name)

    if existing_deployment:
        print(f"🗑️  Deleting preview deployment: {existing_deployment['id']}")

        if api.delete_deployment(existing_deployment["id"]):
            print("✅ Preview deployment deleted successfully!")
        else:
            print("❌ Failed to delete preview deployment")
            sys.exit(1)
    else:
        print(f"ℹ️  No preview deployment found for PR #{pr_number}")


def deploy_production(
    api: LangGraphAPI,
    image_uri: str,
    app_name: str,
    secrets: List[Dict[str, str]],
    resource_spec: Dict[str, Any],
    domain: str,
    protocol: str,
    production_suffix: str,
    deployment_name: str = None,
):
    """Deploy or update production deployment."""
    if deployment_name is None:
        deployment_name = f"{app_name}-{production_suffix}"

    print(f"🔍 Looking for production deployment: {deployment_name}")

    existing_deployment = api.find_deployment_by_name(deployment_name)

    if existing_deployment:
        print(f"📝 Found existing production deployment: {existing_deployment['id']}")
        print(f"🔄 Updating with new image: {image_uri}")

        result = api.update_deployment(existing_deployment["id"], image_uri)
        print("✅ Production deployment updated successfully!")
        print(f"📦 Deployment ID: {result['id']}")
        print(f"🔗 URL: {protocol}://{deployment_name}.{domain}")

    else:
        print(f"🆕 Creating new production deployment: {deployment_name}")
        print(f"📦 Image: {image_uri}")

        result = api.create_deployment(
            deployment_name, image_uri, secrets, resource_spec
        )
        print("✅ Production deployment created successfully!")
        print(f"📦 Deployment ID: {result['id']}")
        print(f"🔗 URL: {protocol}://{deployment_name}.{domain}")


def main():
    parser = argparse.ArgumentParser(
        description="Generic LangGraph API deployment helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deploy preview with custom app name
  python langgraph_api.py --action deploy-preview --app-name my-llm-app --pr-number 123 --image-uri docker.io/user/my-llm-app:preview-123 --api-key $LANGSMITH_API_KEY

  # Deploy with custom secrets and resources
  python langgraph_api.py --action deploy-production --app-name my-llm-app --image-uri docker.io/user/my-llm-app:latest --secrets OPENAI_API_KEY=sk-xxx --secrets-from-env DATABASE_URL --min-scale 0 --max-scale 3 --cpu 2.0 --memory-mb 2048 --api-key $LANGSMITH_API_KEY

  # Use configuration file
  python langgraph_api.py --config deployment-config.json --action deploy-preview --pr-number 123 --api-key $LANGSMITH_API_KEY
        """,
    )

    # Core arguments
    parser.add_argument(
        "--action",
        required=True,
        choices=["deploy-preview", "deploy-production", "cleanup-preview"],
        help="Action to perform",
    )
    parser.add_argument("--api-key", required=True, help="LangGraph API key")
    parser.add_argument(
        "--base-url",
        help="LangGraph API base URL (default: https://api.host.langchain.com/v2)",
    )

    # Configuration file
    parser.add_argument("--config", help="Configuration file path (JSON format)")

    # Deployment naming
    parser.add_argument(
        "--app-name",
        default="text2sql-agent",
        help="Application name (default: text2sql-agent)",
    )
    parser.add_argument(
        "--production-suffix",
        default="prod",
        help="Production deployment suffix (default: prod)",
    )
    parser.add_argument(
        "--deployment-name",
        help="Specific deployment name (overrides naming convention)",
    )

    # Preview deployment arguments
    parser.add_argument("--pr-number", type=int, help="PR number (for preview actions)")
    parser.add_argument("--image-uri", help="Docker image URI")

    # Secrets management
    parser.add_argument(
        "--secrets",
        nargs="*",
        default=[],
        help="Secrets to include (format: KEY=VALUE)",
    )
    parser.add_argument(
        "--secrets-from-env",
        nargs="*",
        default=[],
        help="Environment variables to use as secrets",
    )

    # Resource specifications
    parser.add_argument(
        "--min-scale", type=int, default=1, help="Minimum scale (default: 1)"
    )
    parser.add_argument(
        "--max-scale", type=int, default=1, help="Maximum scale (default: 1)"
    )
    parser.add_argument(
        "--cpu", type=float, default=1.0, help="CPU allocation (default: 1.0)"
    )
    parser.add_argument(
        "--memory-mb", type=int, default=1024, help="Memory in MB (default: 1024)"
    )

    # URL configuration
    parser.add_argument(
        "--domain",
        default="langchain.dev",
        help="Deployment domain (default: langchain.dev)",
    )
    parser.add_argument(
        "--protocol", default="https", help="URL protocol (default: https)"
    )

    args = parser.parse_args()

    # Load configuration file if provided
    config = {}
    if args.config:
        config = load_config(args.config)
        # Override args with config values (config takes precedence)
        for key, value in config.items():
            if hasattr(args, key) and getattr(args, key) in [
                None,
                [],
                0,
                1,
                "text2sql-agent",
                "prod",
                "langchain.dev",
                "https",
            ]:
                setattr(args, key, value)

    # Parse secrets
    secrets = parse_secrets(args.secrets, args.secrets_from_env)

    # Build resource specification
    resource_spec = {
        "min_scale": args.min_scale,
        "max_scale": args.max_scale,
        "cpu": args.cpu,
        "memory_mb": args.memory_mb,
    }

    api = LangGraphAPI(args.api_key, args.base_url)

    if args.action == "deploy-preview":
        if not args.pr_number or not args.image_uri:
            print("❌ PR number and image URI are required for preview deployment")
            sys.exit(1)

        deployment_name = args.deployment_name or f"{args.app_name}-pr-{args.pr_number}"
        deploy_preview(
            api,
            args.pr_number,
            args.image_uri,
            args.app_name,
            secrets,
            resource_spec,
            args.domain,
            args.protocol,
            deployment_name,
        )

    elif args.action == "deploy-production":
        if not args.image_uri:
            print("❌ Image URI is required for production deployment")
            sys.exit(1)

        deployment_name = (
            args.deployment_name or f"{args.app_name}-{args.production_suffix}"
        )
        deploy_production(
            api,
            args.image_uri,
            args.app_name,
            secrets,
            resource_spec,
            args.domain,
            args.protocol,
            args.production_suffix,
            deployment_name,
        )

    elif args.action == "cleanup-preview":
        if not args.pr_number:
            print("❌ PR number is required for preview cleanup")
            sys.exit(1)
        deployment_name = args.deployment_name or f"{args.app_name}-pr-{args.pr_number}"
        cleanup_preview(api, args.pr_number, args.app_name, deployment_name)


if __name__ == "__main__":
    main()
