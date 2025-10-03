from abc import ABC, abstractmethod
from typing import List, Optional

from dotenv import load_dotenv
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from agents.prompts import QA_SYSTEM_PROMPT, SQL_SYSTEM_PROMPT
from agents.utils import get_detailed_table_info, get_engine_for_chinook_db

load_dotenv(override=True)


class OverallState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    schema: str
    sql: str
    records: List[dict]


class InputState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class OutputState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# Abstract interfaces for dependency injection
class LLMProvider(ABC):
    @abstractmethod
    def invoke(self, messages: List[AnyMessage]) -> AnyMessage:
        pass


class DatabaseProvider(ABC):
    @abstractmethod
    def run(self, sql: str) -> List[dict]:
        pass


class SchemaProvider(ABC):
    @abstractmethod
    def get_schema(self) -> str:
        pass


# Concrete implementations
class OpenAILLMProvider(LLMProvider):
    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0):
        self.llm = ChatOpenAI(model=model, temperature=temperature)

    def invoke(self, messages: List[AnyMessage]) -> AnyMessage:
        return self.llm.invoke(messages)


class SQLDatabaseProvider(DatabaseProvider):
    def __init__(self, engine):
        self.db = SQLDatabase(engine)

    def run(self, sql: str) -> List[dict]:
        return self.db.run(sql)


class ChinookSchemaProvider(SchemaProvider):
    def get_schema(self) -> str:
        return get_detailed_table_info()


# Node classes with dependency injection
class SQLGenerationNode:
    def __init__(self, llm_provider: LLMProvider, schema_provider: SchemaProvider):
        self.llm_provider = llm_provider
        self.schema_provider = schema_provider

    def __call__(self, state: OverallState) -> dict:
        last_message = state["messages"][-1]
        prompt = f"""Generate a SQL query for the following question:
        Question: {last_message.content}
        Schema: {self.schema_provider.get_schema()}
        SQL:
        """
        sql_query = self.llm_provider.invoke(
            [SystemMessage(SQL_SYSTEM_PROMPT)]
            + state["messages"]
            + [HumanMessage(prompt)]
        )
        sql_query = sql_query.content.replace("```sql", "").replace("```", "")
        return {"sql": sql_query}


class SQLExecutionNode:
    def __init__(self, db_provider: DatabaseProvider):
        self.db_provider = db_provider

    def __call__(self, state: OverallState) -> dict:
        records = self.db_provider.run(state["sql"])
        return {"records": records}


class AnswerGenerationNode:
    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    def __call__(self, state: OverallState) -> dict:
        last_message = state["messages"][-1]
        prompt = f"Given the question: {last_message.content} and the database results: {state['records']}, provide a concise answer."
        answer = self.llm_provider.invoke(
            [SystemMessage(QA_SYSTEM_PROMPT)]
            + state["messages"]
            + [HumanMessage(prompt)]
        )
        return {"messages": [answer]}


# Graph builder with fluent interface
class Text2SQLGraphBuilder:
    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.input_schema = InputState
        self.output_schema = OutputState

    def add_sql_generation(
        self, llm_provider: LLMProvider, schema_provider: SchemaProvider
    ):
        self.nodes["generate_sql"] = SQLGenerationNode(llm_provider, schema_provider)
        return self

    def add_sql_execution(self, db_provider: DatabaseProvider):
        self.nodes["execute_sql"] = SQLExecutionNode(db_provider)
        return self

    def add_answer_generation(self, llm_provider: LLMProvider):
        self.nodes["generate_answer"] = AnswerGenerationNode(llm_provider)
        return self

    def add_edge(self, from_node: str, to_node: str):
        self.edges.append((from_node, to_node))
        return self

    def build_full_pipeline(self):
        """Build the complete text2sql pipeline"""
        self.add_edge(START, "generate_sql")
        self.add_edge("generate_sql", "execute_sql")
        self.add_edge("execute_sql", "generate_answer")
        self.add_edge("generate_answer", END)
        return self._compile()

    def build_sql_only_subgraph(self):
        """Build subgraph that only generates SQL"""
        self.add_edge(START, "generate_sql")
        self.add_edge("generate_sql", END)
        return self._compile()

    def build_sql_execution_subgraph(self):
        """Build subgraph that generates SQL and executes it"""
        self.add_edge(START, "generate_sql")
        self.add_edge("generate_sql", "execute_sql")
        self.add_edge("execute_sql", END)
        return self._compile()

    def _compile(self):
        builder = StateGraph(
            OverallState,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
        )

        for node_name, node_func in self.nodes.items():
            builder.add_node(node_name, node_func)

        for from_node, to_node in self.edges:
            builder.add_edge(from_node, to_node)

        return builder.compile()


# Test-specific builders and utilities
class TestGraphBuilder(Text2SQLGraphBuilder):
    def build_with_interceptor(self, interceptor):
        """Build graph with state interception capabilities"""
        # This would add state capture at specific nodes
        # Implementation depends on specific interception needs
        return self.build_full_pipeline()


class NodeFactory:
    @staticmethod
    def create_sql_generator(
        llm_provider: Optional[LLMProvider] = None,
        schema_provider: Optional[SchemaProvider] = None,
    ):
        return SQLGenerationNode(
            llm_provider or MockLLMProvider(), schema_provider or MockSchemaProvider()
        )

    @staticmethod
    def create_sql_executor(db_provider: Optional[DatabaseProvider] = None):
        return SQLExecutionNode(db_provider or MockDatabaseProvider())

    @staticmethod
    def create_answer_generator(llm_provider: Optional[LLMProvider] = None):
        return AnswerGenerationNode(llm_provider or MockLLMProvider())


# Mock implementations for testing
class MockLLMProvider(LLMProvider):
    def __init__(self, responses: List[str] = None):
        self.responses = responses or [
            "SELECT * FROM artists",
            "We have 20 songs by James Brown.",
        ]
        self.call_count = 0

    def invoke(self, messages: List[AnyMessage]) -> AnyMessage:
        from langchain_core.messages import AIMessage

        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return AIMessage(content=response)


class MockDatabaseProvider(DatabaseProvider):
    def __init__(self, return_data: List[dict] = None):
        self.return_data = return_data or [{"Artist": "James Brown", "Songs": 20}]

    def run(self, sql: str) -> List[dict]:
        return self.return_data


class MockSchemaProvider(SchemaProvider):
    def __init__(self, schema: str = None):
        self.schema = schema or "Mock schema: Album, Artist, Track tables"

    def get_schema(self) -> str:
        return self.schema


# Configuration classes for different test scenarios
class TestConfig:
    def __init__(self):
        self.llm_provider = MockLLMProvider()
        self.db_provider = MockDatabaseProvider()
        self.schema_provider = MockSchemaProvider()

    def with_real_llm(self, model: str = "gpt-4o-mini"):
        self.llm_provider = OpenAILLMProvider(model=model)
        return self

    def with_real_db(self):
        engine = get_engine_for_chinook_db()
        self.db_provider = SQLDatabaseProvider(engine)
        return self

    def with_real_schema(self):
        self.schema_provider = ChinookSchemaProvider()
        return self

    def with_custom_llm_responses(self, responses: List[str]):
        self.llm_provider = MockLLMProvider(responses=responses)
        return self

    def with_custom_db_data(self, data: List[dict]):
        self.db_provider = MockDatabaseProvider(return_data=data)
        return self


# State interceptor for testing
class StateInterceptor:
    def __init__(self, capture_points: List[str]):
        self.captured_states = {}
        self.capture_points = capture_points

    def intercept(self, node_name: str, state: OverallState):
        if node_name in self.capture_points:
            self.captured_states[node_name] = state.copy()

    def get_captured_state(self, node_name: str) -> Optional[OverallState]:
        return self.captured_states.get(node_name)


# Test scenario class
class TestScenario:
    def __init__(self, name: str, nodes: List[str], config: TestConfig):
        self.name = name
        self.nodes = nodes
        self.config = config

    def run(self, input_state: OverallState) -> OverallState:
        builder = Text2SQLGraphBuilder()

        if "generate_sql" in self.nodes:
            builder.add_sql_generation(
                self.config.llm_provider, self.config.schema_provider
            )
        if "execute_sql" in self.nodes:
            builder.add_sql_execution(self.config.db_provider)
        if "generate_answer" in self.nodes:
            builder.add_answer_generation(self.config.llm_provider)

        # Build appropriate subgraph based on nodes
        if self.nodes == ["generate_sql"]:
            graph = builder.build_sql_only_subgraph()
        elif self.nodes == ["generate_sql", "execute_sql"]:
            graph = builder.build_sql_execution_subgraph()
        else:
            graph = builder.build_full_pipeline()

        return graph.invoke(input_state)


# Factory function for creating the default agent
def create_default_agent():
    """Create the default text2sql agent with real dependencies"""
    config = TestConfig().with_real_llm().with_real_db().with_real_schema()
    builder = Text2SQLGraphBuilder()
    return (
        builder.add_sql_generation(config.llm_provider, config.schema_provider)
        .add_sql_execution(config.db_provider)
        .add_answer_generation(config.llm_provider)
        .build_full_pipeline()
    )
