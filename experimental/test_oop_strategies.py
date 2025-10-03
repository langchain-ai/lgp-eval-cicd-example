from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from experimental.oop_agent import (  # Core classes; Mock implementations; Configuration and utilities; State types
    AnswerGenerationNode,
    MockDatabaseProvider,
    MockLLMProvider,
    MockSchemaProvider,
    NodeFactory,
    SQLExecutionNode,
    SQLGenerationNode,
    StateInterceptor,
    TestConfig,
    TestScenario,
    Text2SQLGraphBuilder,
)


class TestIndividualNodes:
    """Test individual nodes in isolation"""

    @pytest.mark.unit
    def test_sql_generation_node_with_mocks(self):
        """Test SQL generation node with mocked dependencies"""
        mock_llm = MockLLMProvider(["SELECT * FROM artists WHERE name = 'AC/DC'"])
        mock_schema = MockSchemaProvider("Mock schema")

        node = SQLGenerationNode(mock_llm, mock_schema)

        state = {
            "messages": [HumanMessage(content="List all AC/DC albums")],
            "schema": "",
            "sql": "",
            "records": [],
        }

        result = node(state)
        assert "SELECT * FROM artists" in result["sql"]
        assert "AC/DC" in result["sql"]

    @pytest.mark.unit
    def test_sql_execution_node_with_mocks(self):
        """Test SQL execution node with mocked database"""
        mock_db = MockDatabaseProvider([{"AlbumId": 1, "Title": "Highway to Hell"}])
        node = SQLExecutionNode(mock_db)

        state = {
            "messages": [],
            "schema": "",
            "sql": "SELECT * FROM albums WHERE ArtistId = 1",
            "records": [],
        }

        result = node(state)
        assert len(result["records"]) == 1
        assert result["records"][0]["Title"] == "Highway to Hell"

    @pytest.mark.unit
    def test_answer_generation_node_with_mocks(self):
        """Test answer generation node with mocked LLM"""
        mock_llm = MockLLMProvider(["AC/DC has 1 album: Highway to Hell"])
        node = AnswerGenerationNode(mock_llm)

        state = {
            "messages": [HumanMessage(content="How many albums does AC/DC have?")],
            "schema": "",
            "sql": "SELECT COUNT(*) FROM albums WHERE ArtistId = 1",
            "records": [{"count": 1}],
        }

        result = node(state)
        assert "AC/DC" in result["messages"][0].content
        assert "1" in result["messages"][0].content


class TestNodeFactory:
    """Test the node factory for easy node creation"""

    @pytest.mark.unit
    def test_factory_creates_nodes_with_defaults(self):
        """Test that factory creates nodes with default mock dependencies"""
        sql_node = NodeFactory.create_sql_generator()
        exec_node = NodeFactory.create_sql_executor()
        answer_node = NodeFactory.create_answer_generator()

        assert isinstance(sql_node, SQLGenerationNode)
        assert isinstance(exec_node, SQLExecutionNode)
        assert isinstance(answer_node, AnswerGenerationNode)

    @pytest.mark.unit
    def test_factory_creates_nodes_with_custom_dependencies(self):
        """Test factory with custom dependencies"""
        custom_llm = MockLLMProvider(["Custom SQL response"])
        custom_db = MockDatabaseProvider([{"custom": "data"}])
        custom_schema = MockSchemaProvider("Custom schema")

        sql_node = NodeFactory.create_sql_generator(custom_llm, custom_schema)
        exec_node = NodeFactory.create_sql_executor(custom_db)

        # Test that custom dependencies are used
        state = {
            "messages": [HumanMessage("test")],
            "schema": "",
            "sql": "",
            "records": [],
        }
        sql_result = sql_node(state)
        assert "Custom SQL response" in sql_result["sql"]

        exec_result = exec_node(state)
        assert exec_result["records"][0]["custom"] == "data"


class TestSubgraphStrategies:
    """Test different subgraph combinations"""

    @pytest.mark.integration
    def test_sql_generation_only_subgraph(self):
        """Test subgraph that only generates SQL"""
        config = TestConfig().with_custom_llm_responses(["SELECT * FROM albums"])

        builder = Text2SQLGraphBuilder()
        graph = builder.add_sql_generation(
            config.llm_provider, config.schema_provider
        ).build_sql_only_subgraph()

        input_state = {"messages": [HumanMessage(content="List all albums")]}

        result = graph.invoke(input_state)
        assert "sql" in result
        assert "SELECT * FROM albums" in result["sql"]
        # Should not have records or final answer
        assert "records" not in result or result["records"] == []

    @pytest.mark.integration
    def test_sql_generation_and_execution_subgraph(self):
        """Test subgraph that generates SQL and executes it"""
        config = (
            TestConfig()
            .with_custom_llm_responses(["SELECT COUNT(*) FROM albums"])
            .with_custom_db_data([{"count": 347}])
        )

        builder = Text2SQLGraphBuilder()
        graph = (
            builder.add_sql_generation(config.llm_provider, config.schema_provider)
            .add_sql_execution(config.db_provider)
            .build_sql_execution_subgraph()
        )

        input_state = {"messages": [HumanMessage(content="How many albums are there?")]}

        result = graph.invoke(input_state)
        assert "sql" in result
        assert "records" in result
        assert result["records"][0]["count"] == 347
        # Should not have final answer
        assert len(result["messages"]) == 1  # Only the input message

    @pytest.mark.integration
    def test_full_pipeline_subgraph(self):
        """Test the complete pipeline"""
        config = (
            TestConfig()
            .with_custom_llm_responses(
                [
                    "SELECT COUNT(*) FROM albums WHERE ArtistId = 1",
                    "AC/DC has 1 album in the database.",
                ]
            )
            .with_custom_db_data([{"count": 1}])
        )

        builder = Text2SQLGraphBuilder()
        graph = (
            builder.add_sql_generation(config.llm_provider, config.schema_provider)
            .add_sql_execution(config.db_provider)
            .add_answer_generation(config.llm_provider)
            .build_full_pipeline()
        )

        input_state = {
            "messages": [HumanMessage(content="How many albums does AC/DC have?")]
        }

        result = graph.invoke(input_state)
        assert "sql" in result
        assert "records" in result
        assert len(result["messages"]) == 2  # Input + answer
        assert "AC/DC" in result["messages"][-1].content


class TestConfigurationStrategies:
    """Test different configuration approaches"""

    @pytest.mark.integration
    def test_mixed_real_and_mock_dependencies(self):
        """Test using real LLM with mocked database"""
        # This would use real OpenAI API - mark as e2e in real implementation
        config = (
            TestConfig()
            .with_real_llm("gpt-4o-mini")
            .with_custom_db_data([{"count": 42}])
        )

        builder = Text2SQLGraphBuilder()
        graph = (
            builder.add_sql_generation(config.llm_provider, config.schema_provider)
            .add_sql_execution(config.db_provider)
            .build_sql_execution_subgraph()
        )

        input_state = {"messages": [HumanMessage(content="How many albums are there?")]}

        result = graph.invoke(input_state)
        assert "sql" in result
        assert result["records"][0]["count"] == 42

    @pytest.mark.integration
    def test_custom_llm_response_sequence(self):
        """Test with specific LLM response sequence"""
        responses = [
            "SELECT COUNT(*) FROM albums WHERE ArtistId = (SELECT ArtistId FROM artists WHERE Name = 'AC/DC')",
            "AC/DC has exactly 1 album in the database.",
        ]
        config = (
            TestConfig()
            .with_custom_llm_responses(responses)
            .with_custom_db_data([{"count": 1}])
        )

        builder = Text2SQLGraphBuilder()
        graph = (
            builder.add_sql_generation(config.llm_provider, config.schema_provider)
            .add_sql_execution(config.db_provider)
            .add_answer_generation(config.llm_provider)
            .build_full_pipeline()
        )

        input_state = {
            "messages": [HumanMessage(content="How many albums does AC/DC have?")]
        }

        result = graph.invoke(input_state)
        assert "AC/DC" in result["sql"]
        assert "exactly 1 album" in result["messages"][-1].content


class TestScenarioBasedTesting:
    """Test scenario-based approach"""

    @pytest.mark.integration
    def test_sql_generation_scenario(self):
        """Test SQL generation only scenario"""
        config = TestConfig().with_custom_llm_responses(["SELECT * FROM artists"])
        scenario = TestScenario("sql_only", ["generate_sql"], config)

        input_state = {"messages": [HumanMessage(content="List all artists")]}

        result = scenario.run(input_state)
        assert "SELECT * FROM artists" in result["sql"]

    @pytest.mark.integration
    def test_sql_execution_scenario(self):
        """Test SQL generation and execution scenario"""
        config = (
            TestConfig()
            .with_custom_llm_responses(["SELECT Name FROM artists WHERE ArtistId = 1"])
            .with_custom_db_data([{"Name": "AC/DC"}])
        )
        scenario = TestScenario(
            "sql_execution", ["generate_sql", "execute_sql"], config
        )

        input_state = {
            "messages": [HumanMessage(content="What is the name of artist with ID 1?")]
        }

        result = scenario.run(input_state)
        assert "SELECT Name FROM artists" in result["sql"]
        assert result["records"][0]["Name"] == "AC/DC"

    @pytest.mark.integration
    def test_full_pipeline_scenario(self):
        """Test complete pipeline scenario"""
        config = (
            TestConfig()
            .with_custom_llm_responses(
                ["SELECT COUNT(*) FROM albums", "There are 347 albums in the database."]
            )
            .with_custom_db_data([{"count": 347}])
        )
        scenario = TestScenario(
            "full_pipeline", ["generate_sql", "execute_sql", "generate_answer"], config
        )

        input_state = {"messages": [HumanMessage(content="How many albums are there?")]}

        result = scenario.run(input_state)
        assert "SELECT COUNT(*)" in result["sql"]
        assert result["records"][0]["count"] == 347
        assert "347 albums" in result["messages"][-1].content


class TestStateInjectionStrategies:
    """Test injecting specific states at different points"""

    @pytest.mark.unit
    def test_answer_generation_with_specific_data(self):
        """Test answer generation with pre-populated data"""
        mock_llm = MockLLMProvider(["The answer is 42"])
        node = AnswerGenerationNode(mock_llm)

        # Inject specific state for answer generation
        state_with_data = {
            "messages": [HumanMessage(content="What is the answer?")],
            "records": [{"value": 42, "description": "The ultimate answer"}],
            "sql": "SELECT 42 as value, 'The ultimate answer' as description",
            "schema": "",
        }

        result = node(state_with_data)
        assert "42" in result["messages"][0].content

    @pytest.mark.unit
    def test_sql_execution_with_specific_sql(self):
        """Test SQL execution with pre-generated SQL"""
        mock_db = MockDatabaseProvider([{"result": "success"}])
        node = SQLExecutionNode(mock_db)

        # Inject specific SQL
        state_with_sql = {
            "messages": [],
            "schema": "",
            "sql": "SELECT 'success' as result",
            "records": [],
        }

        result = node(state_with_sql)
        assert result["records"][0]["result"] == "success"


class TestErrorHandlingStrategies:
    """Test error handling at different points"""

    @pytest.mark.unit
    def test_sql_generation_with_invalid_llm_response(self):
        """Test handling of invalid LLM responses"""
        mock_llm = MockLLMProvider(["This is not SQL at all"])
        mock_schema = MockSchemaProvider("Mock schema")
        node = SQLGenerationNode(mock_llm, mock_schema)

        state = {
            "messages": [HumanMessage(content="List all artists")],
            "schema": "",
            "sql": "",
            "records": [],
        }

        result = node(state)
        # Should still return the response, even if it's not valid SQL
        assert "This is not SQL at all" in result["sql"]

    @pytest.mark.unit
    def test_sql_execution_with_database_error(self):
        """Test handling of database errors"""
        mock_db = MockDatabaseProvider()
        mock_db.run = MagicMock(side_effect=Exception("Database connection failed"))
        node = SQLExecutionNode(mock_db)

        state = {
            "messages": [],
            "schema": "",
            "sql": "SELECT * FROM nonexistent_table",
            "records": [],
        }

        with pytest.raises(Exception, match="Database connection failed"):
            node(state)


class TestStateInterceptor:
    """Test state interception capabilities"""

    @pytest.mark.integration
    def test_state_interception_at_specific_nodes(self):
        """Test capturing state at specific nodes"""
        interceptor = StateInterceptor(["generate_sql", "execute_sql"])

        # This would be integrated into the graph execution
        # For now, we'll test the interceptor directly
        test_state = {
            "messages": [HumanMessage(content="test")],
            "schema": "",
            "sql": "SELECT * FROM test",
            "records": [],
        }

        interceptor.intercept("generate_sql", test_state)
        interceptor.intercept("execute_sql", test_state)

        captured_sql_state = interceptor.get_captured_state("generate_sql")
        captured_exec_state = interceptor.get_captured_state("execute_sql")

        assert captured_sql_state is not None
        assert captured_exec_state is not None
        assert captured_sql_state["sql"] == "SELECT * FROM test"


class TestGraphBuilderFluentInterface:
    """Test the fluent interface of the graph builder"""

    @pytest.mark.integration
    def test_fluent_interface_chaining(self):
        """Test chaining builder methods"""
        config = TestConfig()

        builder = (
            Text2SQLGraphBuilder()
            .add_sql_generation(config.llm_provider, config.schema_provider)
            .add_sql_execution(config.db_provider)
            .add_answer_generation(config.llm_provider)
        )

        # Should be able to chain and build
        graph = builder.build_full_pipeline()
        assert graph is not None

    @pytest.mark.integration
    def test_custom_edge_creation(self):
        """Test creating custom graph structures"""
        config = TestConfig()

        builder = (
            Text2SQLGraphBuilder()
            .add_sql_generation(config.llm_provider, config.schema_provider)
            .add_answer_generation(config.llm_provider)
            .add_edge("generate_sql", "generate_answer")
            .add_edge("generate_answer", "__end__")
        )

        # This creates a graph that skips SQL execution
        graph = builder._compile()
        assert graph is not None


# Example of how to run specific test categories
if __name__ == "__main__":
    # Run only unit tests
    # pytest test_oop_strategies.py::TestIndividualNodes -m unit

    # Run only integration tests
    # pytest test_oop_strategies.py::TestSubgraphStrategies -m integration

    # Run specific test
    # pytest test_oop_strategies.py::TestIndividualNodes::test_sql_generation_node_with_mocks -v
    pass
