import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import text

from agents.utils import (
    SQLDatabase,
    get_db_table_names,
    get_detailed_table_info,
    get_engine_for_chinook_db,
    get_schema_overview,
)


@pytest.mark.utils
def test_get_engine_for_chinook_db():
    engine = get_engine_for_chinook_db()
    assert engine is not None
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [row[0] for row in result.fetchall()]
    assert "Album" in tables
    assert "Artist" in tables


@pytest.mark.utils
def test_get_db_table_names():
    table_names = get_db_table_names()
    assert isinstance(table_names, list)
    assert "Album" in table_names
    assert "Track" in table_names


@pytest.mark.utils
def test_get_detailed_table_info():
    detailed_info = get_detailed_table_info()
    assert isinstance(detailed_info, dict)
    assert "Album" in detailed_info

    album_info = detailed_info["Album"]
    assert "columns" in album_info
    assert isinstance(album_info["columns"], list)
    assert any(col["name"] == "Title" for col in album_info["columns"])
    assert "sample_data" in album_info

    # Updated: sample_data is returned as a string
    sample_data = album_info["sample_data"]
    assert isinstance(sample_data, str)
    assert sample_data.startswith("[")  # basic sanity check
    assert "For Those About To Rock" in sample_data  # verify content presence


@pytest.mark.utils
def test_get_schema_overview():
    overview = get_schema_overview()
    assert isinstance(overview, dict)
    assert "Track" in overview
    track_schema = overview["Track"]
    assert isinstance(track_schema, list)
    assert any(col["name"] == "Name" for col in track_schema)


@pytest.mark.utils
def test_sqldatabase_defers_engine_creation():
    """A callable engine source must not be resolved until the db is used.

    The Agent Server imports the graph during startup. If that import opens a
    network connection, a cluster with restricted egress hangs startup and the
    whole deployment times out.
    """
    calls = []

    def factory():
        calls.append(1)
        return get_engine_for_chinook_db()

    db = SQLDatabase(factory)
    assert calls == [], "engine was built at construction time"

    db.get_usable_table_names()
    assert calls == [1], "engine should be built on first use"

    db.run("SELECT 1")
    assert calls == [1], "engine should be reused, not rebuilt"


@pytest.mark.utils
def test_importing_the_graph_makes_no_http_calls():
    """Guards the deployment-startup path in a fresh interpreter."""
    script = textwrap.dedent("""
        import requests
        def blocked(*args, **kwargs):
            raise AssertionError("HTTP call during module import")
        requests.get = blocked
        requests.Session.get = lambda self, *a, **k: blocked()

        import agents.simple_text2sql  # noqa: F401
        print("OK")
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


@pytest.mark.utils
@pytest.mark.parametrize(
    "env,expected",
    [
        ({"LLM_GATEWAY_BASE_URL": "https://gw/v1"}, "gateway"),
        ({"ANTHROPIC_API_KEY": "x"}, "anthropic"),
        ({}, "openai"),
        # An explicit choice beats auto-detection either way.
        ({"LLM_PROVIDER": "openai", "LLM_GATEWAY_BASE_URL": "https://gw/v1"}, "openai"),
        ({"LLM_PROVIDER": "gateway"}, "gateway"),
        ({"LLM_PROVIDER": "ANTHROPIC"}, "anthropic"),
    ],
)
def test_llm_route_resolution(monkeypatch, env, expected):
    """Gateway, direct Anthropic and direct OpenAI must all be reachable."""
    from agents.simple_text2sql import resolve_llm_route

    for key in ("LLM_GATEWAY_BASE_URL", "ANTHROPIC_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert resolve_llm_route() == expected


@pytest.mark.utils
def test_unknown_llm_provider_is_rejected(monkeypatch):
    from agents.simple_text2sql import resolve_llm_route

    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    with pytest.raises(ValueError, match="not supported"):
        resolve_llm_route()


@pytest.mark.utils
def test_gateway_route_requires_a_langsmith_key(monkeypatch):
    """Cloud injects LANGSMITH_API_KEY; elsewhere its absence must be explicit."""
    from agents.simple_text2sql import build_llm

    monkeypatch.setenv("LLM_PROVIDER", "gateway")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        build_llm()


@pytest.mark.utils
def test_gateway_errors_do_not_blame_openai():
    """The gateway speaks the OpenAI API, so the OpenAI SDK names its errors.

    A 403 from the gateway surfaced as OpenAIPermissionDeniedError, which points
    at a service that was never contacted and sends people to check the wrong
    credential. Restate it so it names the gateway.
    """
    from agents.simple_text2sql import GatewayChatModel

    class FakePermissionDenied(Exception):
        pass

    FakePermissionDenied.__name__ = "OpenAIPermissionDeniedError"

    class Boom:
        def invoke(self, *a, **k):
            raise FakePermissionDenied(
                "Error code: 403 - {'error': 'API key has expired'}"
            )

    wrapped = GatewayChatModel("https://gateway.example/v1", Boom())
    with pytest.raises(RuntimeError) as excinfo:
        wrapped.invoke("hi")

    message = str(excinfo.value)
    assert "LangSmith LLM Gateway" in message
    assert "gateway.example" in message
    assert "not OpenAI" in message
    assert "LLM_GATEWAY_API_KEY" in message


@pytest.mark.utils
def test_gateway_wrapper_leaves_unrelated_errors_alone():
    """Only auth/permission errors are restated; everything else passes through."""
    from agents.simple_text2sql import GatewayChatModel

    class Boom:
        def invoke(self, *a, **k):
            raise TimeoutError("upstream timed out")

    wrapped = GatewayChatModel("https://gateway.example/v1", Boom())
    with pytest.raises(TimeoutError):
        wrapped.invoke("hi")
