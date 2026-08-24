"""Tests for the SaaS and self-hosted deployment paths.

The control plane accepts different payloads per hosting model, and a wrong
payload only surfaces as a 4xx in CI. These tests pin the host, headers and
request body that each target produces, and assert that secrets stay out of
logs.
"""

import json

import pytest
import responses

from .conftest import control_plane, langgraph_api


def _load_report_module():
    from .conftest import _load

    return _load("report_deployment")


API_KEY = "test-api-key"
WORKSPACE_ID = "11111111-2222-3333-4444-555555555555"
SAAS_HOST = "https://api.host.langchain.com"
SELF_HOSTED_HOST = "https://langsmith.internal.example.com/api-host"


def make_client(host=SAAS_HOST, **kwargs):
    return control_plane.ControlPlaneClient(host, API_KEY, WORKSPACE_ID, **kwargs)


# -- host resolution ------------------------------------------------------


@pytest.mark.deployment
@pytest.mark.parametrize(
    "region,expected",
    [
        ("us", "https://api.host.langchain.com"),
        ("eu", "https://eu.api.host.langchain.com"),
        ("apac", "https://apac.api.host.langchain.com"),
        ("aws-us", "https://aws.api.host.langchain.com"),
    ],
)
def test_saas_region_hosts(region, expected):
    assert control_plane.resolve_host("saas", host=None, region=region) == expected


@pytest.mark.deployment
def test_self_hosted_requires_explicit_host():
    with pytest.raises(
        control_plane.ControlPlaneError, match="explicit control plane host"
    ):
        control_plane.resolve_host("self-hosted", host=None, region="us")


@pytest.mark.deployment
def test_explicit_host_overrides_region():
    assert (
        control_plane.resolve_host("saas", host=SELF_HOSTED_HOST, region="eu")
        == SELF_HOSTED_HOST
    )


@pytest.mark.deployment
@pytest.mark.parametrize(
    "given,expected",
    [
        ("https://host.example.com/api-host/", "https://host.example.com/api-host"),
        ("https://host.example.com/api-host/v2", "https://host.example.com/api-host"),
        ("https://host.example.com", "https://host.example.com"),
    ],
)
def test_host_normalisation(given, expected):
    assert control_plane.normalise_host(given) == expected


@pytest.mark.deployment
@pytest.mark.parametrize(
    "bad_host",
    ["", "  ", "not-a-url", "ftp://host.example.com", "https://?q=1", "//host"],
)
def test_host_rejects_malformed_values(bad_host):
    with pytest.raises(ValueError):
        control_plane.normalise_host(bad_host)


@pytest.mark.deployment
def test_plain_http_requires_opt_in():
    """An API key must not be sent over http unless explicitly allowed."""
    with pytest.raises(ValueError, match="plain http"):
        control_plane.normalise_host("http://langsmith.internal")
    assert (
        control_plane.normalise_host("http://langsmith.internal", allow_insecure=True)
        == "http://langsmith.internal"
    )


# -- payload shape per target --------------------------------------------


@pytest.mark.deployment
def test_saas_uses_github_source():
    payload = control_plane.build_saas_payload(
        integration_id="integration-1",
        repo_url="https://github.com/org/repo",
        repo_ref="feature-branch",
        langgraph_config_path="langgraph.json",
        deployment_type="dev",
    )
    assert control_plane.source_for_target("saas") == "github"
    assert payload["source_config"]["integration_id"] == "integration-1"
    assert payload["source_config"]["repo_url"] == "https://github.com/org/repo"
    assert payload["source_config"]["deployment_type"] == "dev"
    assert payload["source_revision_config"]["repo_ref"] == "feature-branch"
    assert (
        payload["source_revision_config"]["langgraph_config_path"] == "langgraph.json"
    )
    # Cloud builds from source; an image URI would be rejected.
    assert "image_uri" not in payload["source_revision_config"]


@pytest.mark.deployment
def test_saas_requires_integration_id():
    with pytest.raises(control_plane.ControlPlaneError, match="INTEGRATION_ID"):
        control_plane.build_saas_payload(
            integration_id="",
            repo_url="https://github.com/org/repo",
            repo_ref="main",
            langgraph_config_path="langgraph.json",
            deployment_type="dev",
        )


@pytest.mark.deployment
def test_self_hosted_uses_external_docker_source():
    payload = control_plane.build_self_hosted_payload(
        image_uri="docker.io/org/agent:preview-7", listener_id="listener-9"
    )
    assert control_plane.source_for_target("self-hosted") == "external_docker"
    assert (
        payload["source_revision_config"]["image_uri"]
        == "docker.io/org/agent:preview-7"
    )
    assert payload["source_config"]["listener_id"] == "listener-9"
    assert payload["source_config"]["resource_spec"]["memory_mb"] == 1024
    # Self-hosted never builds from a repo.
    assert "repo_url" not in payload["source_config"]


@pytest.mark.deployment
def test_self_hosted_requires_image_uri():
    with pytest.raises(control_plane.ControlPlaneError, match="image-uri"):
        control_plane.build_self_hosted_payload(image_uri="")


@pytest.mark.deployment
def test_listener_id_omitted_when_unset():
    payload = control_plane.build_self_hosted_payload(image_uri="img:1")
    assert "listener_id" not in payload["source_config"]


# -- requests on the wire -------------------------------------------------


@pytest.mark.deployment
@responses.activate
def test_create_deployment_sends_auth_headers_and_body():
    responses.add(
        responses.POST,
        f"{SAAS_HOST}/v2/deployments",
        json={"id": "dep-1", "url": "https://dep-1.example.com", "status": "READY"},
        status=201,
    )
    client = make_client()
    payload = control_plane.build_saas_payload(
        integration_id="integration-1",
        repo_url="https://github.com/org/repo",
        repo_ref="main",
        langgraph_config_path="langgraph.json",
        deployment_type="prod",
    )
    result = client.create_deployment(
        "text2sql-agent-prod",
        "github",
        payload["source_config"],
        payload["source_revision_config"],
        [{"name": "OPENAI_API_KEY", "value": "secret-value"}],
    )

    assert result["id"] == "dep-1"
    request = responses.calls[0].request
    assert request.headers["X-Api-Key"] == API_KEY
    assert request.headers["X-Tenant-Id"] == WORKSPACE_ID
    body = json.loads(request.body)
    assert body["name"] == "text2sql-agent-prod"
    assert body["source"] == "github"
    assert body["secrets"] == [{"name": "OPENAI_API_KEY", "value": "secret-value"}]


@pytest.mark.deployment
@responses.activate
def test_self_hosted_requests_go_to_the_instance_host():
    responses.add(
        responses.POST,
        f"{SELF_HOSTED_HOST}/v2/deployments",
        json={"id": "dep-2", "status": "AWAITING_DATABASE"},
        status=201,
    )
    client = make_client(SELF_HOSTED_HOST)
    payload = control_plane.build_self_hosted_payload(image_uri="docker.io/org/agent:1")
    client.create_deployment(
        "text2sql-agent-pr-3",
        "external_docker",
        payload["source_config"],
        payload["source_revision_config"],
        [],
    )
    assert responses.calls[0].request.url.startswith(
        "https://langsmith.internal.example.com/api-host/v2/deployments"
    )


@pytest.mark.deployment
@responses.activate
def test_find_deployment_filters_by_exact_name():
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments",
        json={"resources": [{"name": "text2sql-agent-pr-1", "id": "dep-1"}]},
        status=200,
    )
    client = make_client()
    assert client.find_deployment("text2sql-agent-pr-1")["id"] == "dep-1"
    assert "name=text2sql-agent-pr-1" in responses.calls[0].request.url


@pytest.mark.deployment
@responses.activate
def test_find_deployment_ignores_partial_name_matches():
    """The API filter is a prefix match, so the client must confirm exact equality."""
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments",
        json={"resources": [{"name": "text2sql-agent-pr-11", "id": "other"}]},
        status=200,
    )
    assert make_client().find_deployment("text2sql-agent-pr-1") is None


@pytest.mark.deployment
@responses.activate
def test_patch_creates_a_new_revision():
    responses.add(
        responses.PATCH,
        f"{SAAS_HOST}/v2/deployments/dep-1",
        json={"id": "dep-1", "latest_revision_id": "rev-2"},
        status=200,
    )
    client = make_client()
    client.patch_deployment("dep-1", {"image_uri": "docker.io/org/agent:2"})
    body = json.loads(responses.calls[0].request.body)
    assert body["source_revision_config"]["image_uri"] == "docker.io/org/agent:2"


@pytest.mark.deployment
@responses.activate
def test_delete_accepts_204():
    responses.add(responses.DELETE, f"{SAAS_HOST}/v2/deployments/dep-1", status=204)
    make_client().delete_deployment("dep-1")
    assert len(responses.calls) == 1


@pytest.mark.deployment
@responses.activate
def test_error_response_raises_with_status():
    """Unexpected statuses surface the code and body so CI logs are diagnosable."""
    responses.add(
        responses.POST,
        f"{SAAS_HOST}/v2/deployments",
        json={"detail": "resource_spec.cpu must be greater than 0"},
        status=400,
    )
    with pytest.raises(control_plane.ControlPlaneError, match="400") as excinfo:
        make_client().create_deployment("x", "github", {}, {}, [])
    assert "resource_spec.cpu" in str(excinfo.value)


@pytest.mark.deployment
def test_requests_carry_a_timeout():
    """A hung control plane must not hang the CI job forever."""
    client = make_client()
    assert client.timeout > 0


# -- revision polling -----------------------------------------------------


@pytest.mark.deployment
@responses.activate
def test_wait_for_revision_returns_when_deployed():
    url = f"{SAAS_HOST}/v2/deployments/dep-1/revisions/rev-1"
    responses.add(responses.GET, url, json={"status": "BUILDING"}, status=200)
    responses.add(responses.GET, url, json={"status": "DEPLOYING"}, status=200)
    responses.add(responses.GET, url, json={"status": "DEPLOYED"}, status=200)

    revision = make_client().wait_for_revision(
        "dep-1", "rev-1", interval=0, sleep=lambda _: None
    )
    assert revision["status"] == "DEPLOYED"


@pytest.mark.deployment
@responses.activate
def test_wait_for_revision_raises_on_build_failure():
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments/dep-1/revisions/rev-1",
        json={"status": "BUILD_FAILED", "status_message": "missing dependency"},
        status=200,
    )
    with pytest.raises(control_plane.ControlPlaneError, match="missing dependency"):
        make_client().wait_for_revision(
            "dep-1", "rev-1", interval=0, sleep=lambda _: None
        )


@pytest.mark.deployment
@responses.activate
def test_wait_for_revision_times_out():
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments/dep-1/revisions/rev-1",
        json={"status": "BUILDING"},
        status=200,
    )
    clock = iter([0.0, 1.0, 2.0, 99.0])
    with pytest.raises(control_plane.ControlPlaneError, match="Timed out"):
        make_client().wait_for_revision(
            "dep-1",
            "rev-1",
            timeout=10,
            interval=0,
            sleep=lambda _: None,
            monotonic=lambda: next(clock),
        )


# -- naming and secrets ---------------------------------------------------


@pytest.mark.deployment
def test_preview_and_production_names():
    assert langgraph_api.preview_name("text2sql-agent", 42) == "text2sql-agent-pr-42"
    assert langgraph_api.production_name("text2sql-agent") == "text2sql-agent-prod"


@pytest.mark.deployment
@pytest.mark.parametrize(
    "bad_name",
    [
        "Text2SQL",
        "agent_underscore",
        "-leading",
        "trailing-",
        "path/traversal",
        "a" * 70,
    ],
)
def test_invalid_deployment_names_rejected(bad_name):
    with pytest.raises(ValueError):
        control_plane.validate_deployment_name(bad_name)


@pytest.mark.deployment
def test_collect_secrets_reads_from_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-value")
    assert control_plane.collect_secrets(["OPENAI_API_KEY"]) == [
        {"name": "OPENAI_API_KEY", "value": "test-openai-value"}
    ]


@pytest.mark.deployment
def test_collect_secrets_fails_loudly_when_unset(monkeypatch):
    monkeypatch.delenv("SOME_MISSING_KEY", raising=False)
    with pytest.raises(control_plane.ControlPlaneError, match="SOME_MISSING_KEY"):
        control_plane.collect_secrets(["SOME_MISSING_KEY"])


@pytest.mark.deployment
def test_print_deployment_never_prints_secret_values(capsys):
    """Deployment output is echoed into CI logs and PR comments."""
    control_plane.print_deployment(
        {
            "id": "dep-1",
            "url": "https://dep-1.example.com",
            "status": "READY",
            "secrets": [{"name": "OPENAI_API_KEY", "value": "test-secret-value"}],
        }
    )
    output = capsys.readouterr().out
    assert "OPENAI_API_KEY" in output
    assert "test-secret-value" not in output


@pytest.mark.deployment
@responses.activate
def test_report_leads_with_failure_when_revision_failed(tmp_path):
    """A deployment can be READY while its newest revision failed.

    The PR comment must not show a green tick in that case -- a reviewer skims
    the heading and would otherwise read a failed deploy as a success.
    """
    report_deployment = _load_report_module()
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments",
        json={
            "resources": [
                {"name": "text2sql-agent-pr-999", "id": "dep-1", "status": "READY"}
            ]
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments/dep-1/revisions",
        json={"resources": [{"id": "rev-1", "status": "DEPLOY_FAILED"}]},
        status=200,
    )

    report = report_deployment.build_report(
        make_client(), "text2sql-agent-pr-999", "preview", "self-hosted"
    )
    out = tmp_path / "comment.md"
    report_deployment.write_markdown_report(report, str(out))
    body = out.read_text()

    heading = next(line for line in body.splitlines() if line.startswith("### "))
    assert "❌" in heading, heading
    assert "✅" not in heading, heading
    assert "DEPLOY_FAILED" in body


@pytest.mark.deployment
@responses.activate
def test_leftover_tracing_project_gives_actionable_error():
    """Deleting a deployment leaves its tracing project, blocking the name.

    A reopened pull request whose preview was already cleaned up hits this, so
    the message has to say how to fix it rather than dumping a raw 409.
    """
    responses.add(
        responses.POST,
        f"{SAAS_HOST}/v2/deployments",
        json={
            "detail": (
                "Deployments create a tracing project in LangSmith with the same "
                "name as the deployment. There already exists a project in "
                "LangSmith named: text2sql-agent-pr-999."
            )
        },
        status=409,
    )
    with pytest.raises(control_plane.NameConflictError) as excinfo:
        make_client().create_deployment(
            "text2sql-agent-pr-999", "external_docker", {}, {}, []
        )

    message = str(excinfo.value)
    assert "tracing project" in message
    assert "Delete the tracing project" in message
    # Still a ControlPlaneError, so existing handling keeps working.
    assert isinstance(excinfo.value, control_plane.ControlPlaneError)


@pytest.mark.deployment
def test_queue_resources_can_be_set_explicitly():
    """queue_cpu defaults to cpu, so 1 CPU silently reserves 2 on the cluster."""
    default = control_plane.build_self_hosted_payload(image_uri="img:1", cpu=1)
    assert "queue_cpu" not in default["source_config"]["resource_spec"]

    tuned = control_plane.build_self_hosted_payload(
        image_uri="img:1", cpu=0.25, memory_mb=512, queue_cpu=0.25, queue_memory_mb=512
    )
    spec = tuned["source_config"]["resource_spec"]
    assert spec["cpu"] == 0.25
    assert spec["queue_cpu"] == 0.25
    assert spec["queue_memory_mb"] == 512


@pytest.mark.deployment
@responses.activate
def test_patch_can_update_resources():
    responses.add(
        responses.PATCH,
        f"{SAAS_HOST}/v2/deployments/dep-1",
        json={"id": "dep-1"},
        status=200,
    )
    make_client().patch_deployment(
        "dep-1",
        {"image_uri": "img:2"},
        source_config={"resource_spec": {"cpu": 0.25}},
    )
    body = json.loads(responses.calls[0].request.body)
    assert body["source_config"]["resource_spec"]["cpu"] == 0.25


@pytest.mark.deployment
@responses.activate
def test_patch_omits_immutable_source_config_fields():
    """repo_url, integration_id, deployment_type and listener_id are fixed at
    creation; resending them on a revision would be rejected."""
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments",
        json={"resources": [{"name": "text2sql-agent-prod", "id": "dep-1"}]},
        status=200,
    )
    responses.add(
        responses.PATCH,
        f"{SAAS_HOST}/v2/deployments/dep-1",
        json={"id": "dep-1", "latest_revision_id": None},
        status=200,
    )

    args = langgraph_api.parse_args(
        [
            "--target",
            "saas",
            "--action",
            "deploy-production",
            "--repo-url",
            "https://github.com/org/repo",
        ]
    )
    import os as _os

    _os.environ["LANGSMITH_GITHUB_INTEGRATION_ID"] = "integration-1"
    langgraph_api.deploy(make_client(), args, "text2sql-agent-prod", "prod", [])

    body = json.loads(responses.calls[-1].request.body)
    sent = body.get("source_config") or {}
    for immutable in ("integration_id", "repo_url", "deployment_type", "listener_id"):
        assert immutable not in sent, f"{immutable} must not be sent on a revision"


@pytest.mark.deployment
def test_self_hosted_rejects_names_that_break_keda():
    """KEDA derives keda-hpa-<name>-<32-char-hash>, capped at 63 characters.

    Exceeding it is the worst kind of failure: every other component reconciles
    and the deployment serves traffic, but the autoscaler is rejected so the
    revision is never marked ready and dies on the platform timeout with no
    reason. Catch it before deploying.
    """
    # 21 characters is the limit: 9 + 21 + 1 + 32 == 63.
    ok = "text2sql-agent-pr-999"
    assert len(ok) == 21
    assert control_plane.validate_new_deployment_name(ok, "self-hosted") == ok

    too_long = "text2sql-agent-pr-9004"
    assert len(too_long) == 22
    with pytest.raises(ValueError) as excinfo:
        control_plane.validate_new_deployment_name(too_long, "self-hosted")
    assert "64 characters" in str(excinfo.value)
    assert "--name-prefix" in str(excinfo.value)

    # SaaS does not use KEDA, so the limit does not apply there.
    assert control_plane.validate_new_deployment_name(too_long, "saas") == too_long

    # An existing deployment with an over-long name must stay findable and
    # deletable -- the rule only governs creating new ones.
    assert control_plane.validate_deployment_name(too_long) == too_long


@pytest.mark.deployment
def test_four_digit_pr_numbers_break_the_default_prefix():
    """The default prefix silently breaks once a repo reaches PR #1000."""
    assert langgraph_api.preview_name("text2sql-agent", 999, "self-hosted")
    with pytest.raises(ValueError, match="self-hosted allows at most 21"):
        langgraph_api.preview_name("text2sql-agent", 1000, "self-hosted")
    # Production is short enough at any time.
    assert langgraph_api.production_name("text2sql-agent", "self-hosted")


@pytest.mark.deployment
@responses.activate
def test_over_long_existing_deployment_can_still_be_deleted():
    """The length rule must not strand a deployment created before it existed."""
    responses.add(
        responses.GET,
        f"{SELF_HOSTED_HOST}/v2/deployments",
        json={"resources": [{"name": "text2sql-agent-pr-9004", "id": "dep-1"}]},
        status=200,
    )
    responses.add(
        responses.DELETE, f"{SELF_HOSTED_HOST}/v2/deployments/dep-1", status=204
    )
    client = make_client(SELF_HOSTED_HOST)
    langgraph_api.cleanup_preview(
        client, langgraph_api.preview_name("text2sql-agent", 9004)
    )
    assert responses.calls[-1].request.method == "DELETE"


@pytest.mark.deployment
def test_default_prefix_survives_large_pr_numbers():
    """The default prefix must not break as a repository accumulates PRs."""
    args = langgraph_api.parse_args(["--action", "status"])
    for pr in (1, 999, 1000, 999999):
        name = langgraph_api.preview_name(args.name_prefix, pr, "self-hosted")
        assert len(name) <= control_plane.MAX_SELF_HOSTED_NAME_LEN, name
    assert langgraph_api.production_name(args.name_prefix, "self-hosted")


@pytest.mark.deployment
@responses.activate
def test_interrupt_cancels_an_in_progress_revision():
    """A stuck revision blocks later ones, so CI needs a way to cancel it."""
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments",
        json={"resources": [{"name": "t2sql-pr-1", "id": "dep-1"}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments/dep-1/revisions",
        json={"resources": [{"id": "rev-1", "status": "DEPLOYING"}]},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{SAAS_HOST}/v2/deployments/dep-1/revisions/rev-1/interruption",
        status=204,
    )
    langgraph_api.interrupt_latest(make_client(), "t2sql-pr-1")
    assert responses.calls[-1].request.url.endswith("/interruption")


@pytest.mark.deployment
@responses.activate
def test_interrupt_is_a_noop_on_a_settled_revision():
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments",
        json={"resources": [{"name": "t2sql-pr-1", "id": "dep-1"}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{SAAS_HOST}/v2/deployments/dep-1/revisions",
        json={"resources": [{"id": "rev-1", "status": "DEPLOYED"}]},
        status=200,
    )
    langgraph_api.interrupt_latest(make_client(), "t2sql-pr-1")
    # No interruption call attempted.
    assert not any("interruption" in c.request.url for c in responses.calls)


@pytest.mark.deployment
def test_explicit_name_overrides_the_pr_convention():
    """Long-lived deployments should not be named after a pull request."""
    args = langgraph_api.parse_args(
        ["--action", "status", "--name", "t2sql-demo", "--pr-number", "7"]
    )
    assert langgraph_api.resolve_name(args) == "t2sql-demo"
    # And it is still length-checked when creating on self-hosted.
    long_args = langgraph_api.parse_args(
        ["--action", "status", "--name", "a-very-long-deployment-name-here"]
    )
    with pytest.raises(ValueError, match="self-hosted allows at most 21"):
        langgraph_api.resolve_name(long_args, target="self-hosted")


@pytest.mark.deployment
def test_name_falls_back_to_the_convention():
    pr = langgraph_api.parse_args(["--action", "status", "--pr-number", "7"])
    assert langgraph_api.resolve_name(pr) == "text2sql-pr-7"
    prod = langgraph_api.parse_args(["--action", "status"])
    assert langgraph_api.resolve_name(prod) == "text2sql-prod"


@pytest.mark.deployment
def test_self_hosted_serving_url_comes_from_custom_url():
    """Self-hosted leaves `url` null and serves under source_config.custom_url.

    Reading only `url` reported "not provisioned yet" in the PR comment for a
    deployment that was serving fine.
    """
    cloud = {"url": "https://x.us.langgraph.app", "source_config": {}}
    assert control_plane.deployment_url(cloud) == "https://x.us.langgraph.app"

    self_hosted = {
        "url": None,
        "source_config": {"custom_url": "https://ls.internal/lgp/t2sql-demo-abc"},
    }
    assert (
        control_plane.deployment_url(self_hosted)
        == "https://ls.internal/lgp/t2sql-demo-abc"
    )

    assert control_plane.deployment_url({"url": None, "source_config": {}}) is None


@pytest.mark.deployment
def test_route_through_gateway_is_sent_when_requested():
    """Cloud accepts the flag; the client must actually include it."""
    import inspect

    src = inspect.getsource(control_plane.ControlPlaneClient.create_deployment)
    assert "route_through_gateway" in src
    src = inspect.getsource(control_plane.ControlPlaneClient.patch_deployment)
    assert "route_through_gateway" in src


@pytest.mark.deployment
def test_route_through_gateway_help_states_it_is_cloud_only():
    """The flag is silently ignored by self-hosted, so the help must say so."""
    parser_help = langgraph_api.parse_args.__doc__ or ""
    import pathlib
    import subprocess
    import sys as _s

    out = subprocess.run(
        [
            _s.executable,
            str(
                pathlib.Path(__file__).resolve().parents[2]
                / ".github/scripts/langgraph_api.py"
            ),
            "--help",
        ],
        capture_output=True,
        text=True,
    ).stdout
    assert "Cloud only" in out
    assert "silently ignore" in out
