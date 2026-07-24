import json
import asyncio
from typing import AsyncGenerator, Literal

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

ADMIN_SYSTEM_PROMPT = """你是一个商家智能助手，可以分析销售数据、预测库存缺货、给出补货建议。
你可以使用以下工具：
- analyze_product_sales: 分析指定商品的销售趋势
- predict_stock_shortage: 预测未来可能缺货的商品列表
- generate_sales_report: 生成指定日期范围的销售趋势分析报告
- get_inventory_overview: 获取库存概览
- get_current_time: 获取当前时间

请根据用户的问题判断是否需要调用工具。回答时请使用清晰、专业的中文，
对于数据类问题请先调用工具获取数据再进行分析和回答。
如果用户询问具体商品，请先确认商品ID再进行分析。"""

USER_SYSTEM_PROMPT = """你是一个用户智能客服，帮助用户查找商品、修改地址、退款等。
请用友好、简洁的中文回答用户问题。"""


def _get_system_prompt(role: str) -> SystemMessage:
    if role == "admin":
        return SystemMessage(content=ADMIN_SYSTEM_PROMPT)
    return SystemMessage(content=USER_SYSTEM_PROMPT)


def call_model(state: MessagesState) -> dict:
    role = state.get("role", "user")
    system_msg = _get_system_prompt(role)
    messages = [system_msg, *state["messages"]]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else END


async def execute_tools(state: MessagesState) -> dict:
    last: AIMessage = state["messages"][-1]
    tool_messages = []
    for tc in last.tool_calls:
        fn = TOOL_MAP.get(tc["name"])
        if fn:
            try:
                if asyncio.iscoroutinefunction(fn):
                    result = await fn(**tc.get("args", {}))
                else:
                    result = fn(**tc.get("args", {}))
            except Exception as e:
                result = {"error": f"工具执行失败: {str(e)}"}
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


async def run_agent(user_message: str, role: str = "user") -> str:
    inputs = {"messages": [HumanMessage(content=user_message)], "role": role}
    result = await app.ainvoke(inputs)
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
    return "抱歉，我没有生成有效的回复。"


async def run_agent_stream(user_message: str, role: str = "user") -> AsyncGenerator[str, None]:
    inputs = {"messages": [HumanMessage(content=user_message)], "role": role}
    async for event in app.astream_events(inputs, version="v1"):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                yield content
