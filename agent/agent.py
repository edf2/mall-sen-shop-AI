import json
from typing import AsyncGenerator, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, MessagesState, StateGraph

from agent.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, MODEL_NAME
from agent.tools import TOOL_MAP, TOOLS

llm = ChatOpenAI(                                       #初始话大模型
    model=MODEL_NAME,
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
    temperature=0,
)

llm_with_tools = llm.bind_tools(TOOLS)


def call_model(state: MessagesState) -> dict:       #调用模型节点
    system_msg = SystemMessage(content="你是一个智能助手，可以通过工具获取实时信息。请根据用户问题判断是否需要调用工具。")  #设置系统角色
    messages = [system_msg, *state["messages"]]             #将系统角色和之前的消息合并
    response = llm_with_tools.invoke(messages)              #调用大模型
    return {"messages": [response]}                         #将大模型的回复添加到messages列表中


def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:       #路由决策函数，判断是否需要调用工具
    last = state["messages"][-1]                                                #获取最后一条消息
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else END  #如果last是AIMessage且tool_calls不为空，则返回"tools"，否则返回"__end__"


def execute_tools(state: MessagesState) -> dict:     #调用工具节点
    last: AIMessage = state["messages"][-1]             #获取最后一条消息
    tool_messages = []                                  #创建一个空列表，用于存储工具的回复
    for tc in last.tool_calls:                          #遍历tool_calls列表
        fn = TOOL_MAP.get(tc["name"])                   #根据工具名称获取对应的函数
        if fn:
            result = fn(**tc.get("args", {}))           #调用函数，并将args作为参数
            tool_messages.append(
                ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tc["id"]) #将结果转换为json字符串，并和tool_call_id一起添加到tool_messages列表中
            )
        else:
            tool_messages.append(
                ToolMessage(content=f"未知工具: {tc['name']}", tool_call_id=tc["id"])
            )
    return {"messages": tool_messages}


workflow = StateGraph(MessagesState)                                #定义状态图，MessagesState 是内置状态类型，包含 messages 列表
workflow.add_node("agent", call_model)                              #添加agent节点
workflow.add_node("tools", execute_tools)                           #添加tools节点

workflow.set_entry_point("agent")                                   #设置入口节点，从agent开始
workflow.add_conditional_edges("agent", should_continue)     #添加条件边，根据should_continue函数的返回值决定下一个节点
workflow.add_edge("tools", "agent")                #添加固定边，从tools节点到agent节点

app = workflow.compile()                                            #编译状态图，生成可执行的程序


async def run_agent(user_message: str) -> str:                      #运行入口
    inputs = {"messages": [HumanMessage(content=user_message)]}     #将用户消息转换为HumanMessage类型，并添加到messages列表中
    result = await app.ainvoke(inputs)                              #调用编译后的程序
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:              #遍历result["messages"]列表，找到第一个AIMessage类型且内容不为空的消息
            return msg.content
    return "抱歉，我没有生成有效的回复。"

async def run_agent_stream(user_message: str) -> AsyncGenerator[str, None]:
    inputs = {"messages": [HumanMessage(content=user_message)]}
    async for event in app.astream_events(inputs, version="v1"):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                yield content


