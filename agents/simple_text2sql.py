import os

from dotenv import load_dotenv
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, List, TypedDict

from agents.prompts import QA_SYSTEM_PROMPT, SQL_SYSTEM_PROMPT
from agents.utils import (
    SQLDatabase,
    get_detailed_table_info,
    get_engine_for_chinook_db,
)

# Not override=True: real environment variables must win over a local .env.
# Otherwise a stale .env silently overrides credentials that CI or a deployment
# set deliberately, which is confusing to debug.
load_dotenv()

#: Default model per route. Gateway IDs are provider-qualified; direct ones are not.
DEFAULT_MODELS = {
    "gateway": "anthropic/claude-haiku-4-5-20251001",
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
}


def resolve_llm_route() -> str:
    """Decide how to reach a model, honouring an explicit ``LLM_PROVIDER``.

    Otherwise pick the first route that is actually configured, preferring the
    gateway because it needs no provider key at all.
    """
    explicit = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if explicit:
        if explicit not in DEFAULT_MODELS:
            raise ValueError(
                f"LLM_PROVIDER={explicit!r} is not supported; expected one of "
                f"{', '.join(sorted(DEFAULT_MODELS))}."
            )
        return explicit
    if os.environ.get("LLM_GATEWAY_BASE_URL"):
        return "gateway"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "openai"


def build_llm():
    """Build the chat model, supporting three ways to reach a provider.

    ``gateway``
        Route through the `LangSmith LLM Gateway
        <https://docs.langchain.com/langsmith/llm-gateway-api-formats>`_, which is
        OpenAI-compatible and authenticates with a LangSmith API key. No provider
        key is needed, which is the only workable setup where developers are not
        issued them. Model IDs are provider-qualified, e.g.
        ``anthropic/claude-sonnet-4-6``. LangSmith Cloud injects
        ``LANGSMITH_API_KEY`` into deployments automatically.

    ``anthropic``
        Call Anthropic directly with ``ANTHROPIC_API_KEY``.

    ``openai``
        Call OpenAI directly with ``OPENAI_API_KEY`` -- the original behaviour.

    Set ``LLM_PROVIDER`` to force a route, or ``LLM_MODEL`` to override the model.
    """
    route = resolve_llm_route()
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODELS[route]

    if route == "gateway":
        # Wrap gateway failures. The gateway is OpenAI-compatible, so the OpenAI
        # SDK raises OpenAI-named exceptions for errors that have nothing to do
        # with OpenAI -- a 403 from the gateway surfaces as
        # OpenAIPermissionDeniedError, which sends people to check the wrong
        # credential entirely.
        # LLM_GATEWAY_API_KEY first: a self-hosted deployment calling Cloud's
        # gateway needs a Cloud key, which is not the same as the LANGSMITH_API_KEY
        # its own instance issues. On Cloud the two coincide and the fallback works.
        api_key = os.environ.get("LLM_GATEWAY_API_KEY") or os.environ.get(
            "LANGSMITH_API_KEY"
        )
        if not api_key:
            raise ValueError(
                "The LLM gateway needs a LangSmith key: set LLM_GATEWAY_API_KEY, "
                "or LANGSMITH_API_KEY when they are the same instance. LangSmith "
                "Cloud injects LANGSMITH_API_KEY into deployments for you."
            )
        base_url = os.environ.get(
            "LLM_GATEWAY_BASE_URL", "https://gateway.smith.langchain.com/v1"
        )
        return GatewayChatModel(
            base_url,
            ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0),
        )

    if route == "anthropic":
        # Imported lazily so the OpenAI-only path needs no Anthropic install.
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, temperature=0)

    return ChatOpenAI(model=model, temperature=0)


class OverallState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    schema: str
    sql: str
    records: List[dict]


class InputState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class OutputState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def generate_sql(llm):
    def _generate(state: OverallState) -> dict:
        last_message = state["messages"][-1]
        prompt = f"""Generate a SQL query for the following question:
        Question: {last_message.content}
        Schema: {get_detailed_table_info()}
        SQL:
        """
        sql_query = llm.invoke(
            [SystemMessage(SQL_SYSTEM_PROMPT)]
            + state["messages"]
            + [HumanMessage(prompt)]
        )
        sql_query = sql_query.content.replace("```sql", "").replace("```", "")
        return {"sql": sql_query}

    return _generate


def execute_sql(db):
    def _execute(state: OverallState) -> dict:
        records = db.run(state["sql"])
        return {"records": records}

    return _execute


def generate_answer(llm):
    def _answer(state: OverallState) -> dict:
        last_message = state["messages"][-1]
        prompt = f"Given the question: {last_message.content} and the database results: {state['records']}, provide a concise answer."
        answer = llm.invoke(
            [SystemMessage(QA_SYSTEM_PROMPT)]
            + state["messages"]
            + [HumanMessage(prompt)]
        )
        return {"messages": [answer]}

    return _answer


def create_agent(llm, db):
    builder = StateGraph(
        OverallState, input_schema=InputState, output_schema=OutputState
    )
    builder.add_node("generate_sql", generate_sql(llm))
    builder.add_node("execute_sql", execute_sql(db))
    builder.add_node("generate_answer", generate_answer(llm))
    builder.add_edge(START, "generate_sql")
    builder.add_edge("generate_sql", "execute_sql")
    builder.add_edge("execute_sql", "generate_answer")
    builder.add_edge("generate_answer", END)
    return builder.compile()


class GatewayChatModel:
    """Wrap a gateway-backed model so its errors name the gateway.

    The LangSmith LLM Gateway speaks the OpenAI API, so the OpenAI SDK raises
    ``OpenAIAuthenticationError`` / ``OpenAIPermissionDeniedError`` for gateway
    problems. Those names point at OpenAI, which is not involved at all -- the
    request goes to the gateway and the credential is a LangSmith key. Restate
    the error so it names what actually failed.
    """

    def __init__(self, base_url, model):
        self._base_url = base_url
        self._model = model

    def _wrap(self, exc: Exception) -> Exception:
        name = type(exc).__name__
        if "Authentication" not in name and "PermissionDenied" not in name:
            return exc
        return RuntimeError(
            f"The LangSmith LLM Gateway at {self._base_url} rejected the request: "
            f"{exc}. This is a gateway/LangSmith credential problem, not OpenAI -- "
            "no request was made to OpenAI. Check LLM_GATEWAY_API_KEY (or "
            "LANGSMITH_API_KEY), and note the gateway only accepts Cloud keys, "
            "not a self-hosted instance's own key."
        )

    def invoke(self, *args, **kwargs):
        try:
            return self._model.invoke(*args, **kwargs)
        except Exception as exc:
            raise self._wrap(exc) from exc

    async def ainvoke(self, *args, **kwargs):
        try:
            return await self._model.ainvoke(*args, **kwargs)
        except Exception as exc:
            raise self._wrap(exc) from exc

    def __getattr__(self, name):
        return getattr(self._model, name)


class LazyChatModel:
    """Defer model construction until the first call.

    The Agent Server imports this module during startup, and every chat model
    validates its credentials in the constructor. Building eagerly means the
    module cannot be imported without a key -- which fails the deployment at
    import rather than at the call, and forces credentials on test jobs that
    only ever use mocks.
    """

    def __init__(self, factory):
        self._factory = factory
        self._model = None

    def _resolve(self):
        if self._model is None:
            self._model = self._factory()
        return self._model

    def invoke(self, *args, **kwargs):
        return self._resolve().invoke(*args, **kwargs)

    async def ainvoke(self, *args, **kwargs):
        return await self._resolve().ainvoke(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._resolve(), name)


llm = LazyChatModel(build_llm)
# Pass the factory, not an engine: the Agent Server imports this module
# during startup, and a network call there would block the deployment.
db = SQLDatabase(get_engine_for_chinook_db)
agent = create_agent(llm, db)
