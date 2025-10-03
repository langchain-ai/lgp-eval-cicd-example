from dataclasses import dataclass
from operator import add
from unittest.mock import MagicMock

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime
from typing_extensions import Annotated, TypedDict

load_dotenv()

llm = init_chat_model("openai:gpt-4o-mini")
mock_llm = MagicMock()
mock_llm.invoke.return_value = AIMessage(content="Mocked response")


@dataclass
class ContextSchema:
    mock_llm: MagicMock | None = None


class InputState(TypedDict):
    messages: Annotated[list[str], add]


def one(state: InputState) -> InputState:
    print("-- Node One --")
    return {"messages": ["first_message"]}


def two(state: InputState, runtime: Runtime[ContextSchema]) -> InputState:
    print("-- Node Two --")
    if not runtime.context.mock_llm:
        print("Using real LLM")
        return {"messages": [llm.invoke("how are you?").content]}
    else:
        print("Using mock LLM")
        return {"messages": [runtime.context.mock_llm.invoke("how are you?").content]}


def three(state: InputState) -> InputState:
    print("-- Node Three --")
    return {"messages": ["third_message"]}


graph = StateGraph(InputState)
graph.add_node("one", one)
graph.add_node("two", two)
graph.add_node("three", three)
graph.add_edge("one", "two")
graph.add_edge("two", "three")
graph.set_entry_point("one")
graph.set_finish_point("three")
test_checkpointer = MemorySaver()
compiled = graph.compile(checkpointer=test_checkpointer)

configuration = {"thread_id": "1"}

compiled.update_state(
    values={"messages": ["first_message"]},
    as_node="one",
    config={"configurable": configuration},
)

response = compiled.invoke(
    None,
    config=configuration,
    interrupt_before=["three"],
    context=ContextSchema(mock_llm=mock_llm),  # using mock llm
    # context=ContextSchema(mock_llm=None), # using real llm
)

print(response)
