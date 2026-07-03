import json
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, MessagesState, StateGraph

from agent.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, MODEL_NAME
from agent.tools import TOOL_MAP, TOOLS

llm = ChatOpenAI(
    model=MODEL_NAME,
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
    temperature=0,
)

llm_with_tools = llm.bind_tools(TOOLS)


def call_model(state: MessagesState) -> dict:
    system_msg = SystemMessage(content="你是一个智能助手，可以通过工具获取实时信息。请根据用户问题判断是否需要调用工具。")
    messages = [system_msg, *state["messages"]]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else END


def execute_tools(state: MessagesState) -> dict:
    last: AIMessage = state["messages"][-1]
    tool_messages = []
    for tc in last.tool_calls:
        fn = TOOL_MAP.get(tc["name"])
        if fn:
            result = fn(**tc.get("args", {}))
            tool_messages.append(
                ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tc["id"])
            )
        else:
            tool_messages.append(
                ToolMessage(content=f"未知工具: {tc['name']}", tool_call_id=tc["id"])
            )
    return {"messages": tool_messages}


workflow = StateGraph(MessagesState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", execute_tools)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

app = workflow.compile()


async def run_agent(user_message: str) -> str:
    inputs = {"messages": [HumanMessage(content=user_message)]}
    result = await app.ainvoke(inputs)
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
    return "抱歉，我没有生成有效的回复。"
