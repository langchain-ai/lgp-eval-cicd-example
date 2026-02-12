#!/usr/bin/env python3
"""
LangGraph deployment status reporter.
Generates deployment status reports and creates PR comments with deployment details.
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

import requests


class DeploymentReporter:
    """LangGraph deployment status reporter."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://gtm.smith.langchain.dev/api-host/v2"
        # Fix header name to match working script
        self.headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    def get_deployment_status(self, deployment_name: str) -> Optional[Dict[str, Any]]:
        """Get deployment status by name."""
        try:
            response = requests.get(
                f"{self.base_url}/deployments",
                headers=self.headers,
                params={"name_contains": deployment_name},
            )

            if response.status_code == 200:
                deployments = response.json()
                for deployment in deployments.get("resources", []):
                    if deployment.get("name") == deployment_name:
                        return deployment
            else:
                print(f"❌ Failed to get deployment status: {response.status_code}")
                print(f"Response: {response.text}")

        except Exception as e:
            print(f"❌ Error getting deployment status: {e}")

        return None

    def get_deployment_revisions(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """Get deployment revisions."""
        try:
            response = requests.get(
                f"{self.base_url}/deployments/{deployment_id}/revisions",
                headers=self.headers,
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Failed to get deployment revisions: {response.status_code}")
                print(f"Response: {response.text}")

        except Exception as e:
            print(f"❌ Error getting deployment revisions: {e}")

        return None

    def format_status_emoji(self, status: str) -> str:
        """Format deployment status with emoji."""
        status_map = {
            "AWAITING_DATABASE": "⏳",
            "READY": "✅",
            "UNUSED": "⏸️",
            "AWAITING_DELETE": "🗑️",
            "UNKNOWN": "❓",
        }
        return status_map.get(status, "❓")

    def format_revision_status_emoji(self, status: str) -> str:
        """Format revision status with emoji."""
        status_map = {
            "CREATING": "🔨",
            "AWAITING_BUILD": "⏳",
            "BUILDING": "🔨",
            "AWAITING_DEPLOY": "⏳",
            "DEPLOYING": "🚀",
            "CREATE_FAILED": "❌",
            "BUILD_FAILED": "❌",
            "DEPLOY_FAILED": "❌",
            "DEPLOYED": "✅",
            "INTERRUPTED": "⏸️",
            "UNKNOWN": "❓",
        }
        return status_map.get(status, "❓")

    def get_deployment_url(self, deployment_name: str) -> str:
        """Get deployment URL."""
        return f"https://{deployment_name}.langchain.dev"

    def generate_deployment_report(
        self, deployment_name: str, image_uri: str, deployment_type: str = "preview"
    ) -> Dict[str, Any]:
        """Generate comprehensive deployment report."""
        print(f"🔍 Generating deployment report for: {deployment_name}")

        deployment = self.get_deployment_status(deployment_name)

        if not deployment:
            return {
                "deployment_name": deployment_name,
                "status": "NOT_FOUND",
                "error": "Deployment not found",
            }

        # Get latest revision details
        latest_revision = None
        if deployment.get("latest_revision_id"):
            revisions = self.get_deployment_revisions(deployment["id"])
            if revisions and revisions.get("resources"):
                latest_revision = revisions["resources"][0]  # Most recent revision

        # Extract image info
        image_info = {
            "uri": image_uri,
            "tag": image_uri.split(":")[-1] if ":" in image_uri else "latest",
            "registry": image_uri.split("/")[0] if "/" in image_uri else "unknown",
        }

        # Build report
        report = {
            "deployment_name": deployment_name,
            "deployment_id": deployment.get("id"),
            "status": deployment.get("status", "UNKNOWN"),
            "status_emoji": self.format_status_emoji(
                deployment.get("status", "UNKNOWN")
            ),
            "url": self.get_deployment_url(deployment_name),
            "created_at": deployment.get("created_at"),
            "updated_at": deployment.get("updated_at"),
            "deployment_type": deployment_type,
            "image_info": image_info,
            "latest_revision": latest_revision,
            "revision_status": (
                latest_revision.get("status", "UNKNOWN")
                if latest_revision
                else "UNKNOWN"
            ),
            "revision_status_emoji": (
                self.format_revision_status_emoji(
                    latest_revision.get("status", "UNKNOWN")
                )
                if latest_revision
                else "❓"
            ),
        }

        return report

    def write_markdown_report(
        self, report: Dict[str, Any], output_file: str = "deployment_comment.md"
    ):
        """Write deployment report to markdown file."""
        print(f"📝 Writing deployment report to {output_file}")

        with open(output_file, "w") as f:
            f.write("# 🚀 LangSmith Deployment Status\n\n")

            if "error" in report:
                f.write("### ❌ Deployment Failed\n\n")
                f.write(f"**Error:** {report['error']}\n\n")
                return

            # Deployment header
            deployment_type = report.get("deployment_type", "unknown").title()
            status_emoji = report.get("status_emoji", "❓")
            status = report.get("status", "UNKNOWN")

            f.write(
                f"### {status_emoji} {deployment_type} Deployment: `{report['deployment_name']}`\n\n"
            )

            # Status table
            f.write("| Property | Value |\n")
            f.write("|----------|-------|\n")
            f.write(f"| **Status** | {status_emoji} {status} |\n")
            f.write(f"| **URL** | [{report['url']}]({report['url']}) |\n")
            f.write(f"| **Deployment ID** | `{report['deployment_id']}` |\n")

            # Image info
            image_info = report.get("image_info", {})
            f.write(f"| **Image** | `{image_info.get('uri', 'N/A')}` |\n")
            f.write(f"| **Tag** | `{image_info.get('tag', 'N/A')}` |\n")

            # Timestamps
            if report.get("created_at"):
                created_time = datetime.fromisoformat(
                    report["created_at"].replace("Z", "+00:00")
                )
                f.write(
                    f"| **Created** | {created_time.strftime('%Y-%m-%d %H:%M:%S UTC')} |\n"
                )

            if report.get("updated_at"):
                updated_time = datetime.fromisoformat(
                    report["updated_at"].replace("Z", "+00:00")
                )
                f.write(
                    f"| **Updated** | {updated_time.strftime('%Y-%m-%d %H:%M:%S UTC')} |\n"
                )

            # Revision status
            revision_status = report.get("revision_status", "UNKNOWN")
            revision_emoji = report.get("revision_status_emoji", "❓")
            f.write(f"| **Revision Status** | {revision_emoji} {revision_status} |\n")

            f.write("\n")

            # Additional info based on status
            if status == "READY" and revision_status == "DEPLOYED":
                f.write("🎉 **Deployment is ready and accessible!**\n\n")
            elif status == "AWAITING_DATABASE":
                f.write("⏳ **Deployment is being set up...**\n\n")
            elif "FAILED" in revision_status:
                f.write(
                    "❌ **Deployment failed. Check the logs for more details.**\n\n"
                )
            elif revision_status in ["BUILDING", "DEPLOYING"]:
                f.write("🚀 **Deployment is in progress...**\n\n")

            # Footer
            f.write("---\n")
            f.write(
                f"*Deployment report generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}*\n"
            )

        print(f"✅ Deployment report written to {output_file}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate LangGraph deployment status reports for PR comments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate deployment report for preview deployment
  python report_deployment.py --deployment-name text2sql-agent-pr-123 --image-uri docker.io/perinim98/text2sql-agent:preview-123 --deployment-type preview

  # Generate deployment report for production deployment
  python report_deployment.py --deployment-name text2sql-agent-prod --image-uri docker.io/perinim98/text2sql-agent:latest --deployment-type production
        """,
    )

    parser.add_argument(
        "--deployment-name", required=True, help="Name of the deployment to report on"
    )

    parser.add_argument(
        "--image-uri", required=True, help="Docker image URI used for deployment"
    )

    parser.add_argument(
        "--deployment-type",
        choices=["preview", "production"],
        default="preview",
        help="Type of deployment (default: preview)",
    )

    parser.add_argument(
        "--output",
        "-o",
        default="deployment_comment.md",
        help="Output markdown file (default: deployment_comment.md)",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output"
    )

    args = parser.parse_args()

    # Set up API client
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        print("❌ LANGSMITH_API_KEY environment variable is required")
        sys.exit(1)

    reporter = DeploymentReporter(api_key)

    # Generate report
    report = reporter.generate_deployment_report(
        args.deployment_name, args.image_uri, args.deployment_type
    )

    # Write report
    reporter.write_markdown_report(report, args.output)

    # Summary
    if "error" in report:
        print(f"❌ Deployment report failed: {report['error']}")
        sys.exit(1)
    else:
        status = report.get("status", "UNKNOWN")
        print("✅ Deployment report generated successfully!")
        print(f"📊 Status: {status}")
        print(f"🔗 URL: {report.get('url', 'N/A')}")


if __name__ == "__main__":
    main()
