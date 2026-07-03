from datetime import datetime
from typing import Any


def get_current_time(location: str = "中国") -> dict[str, Any]:
    """获取指定地点的当前日期和时间"""
    now = datetime.now()
    return {
        "location": location,
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Shanghai",
    }


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取指定地点的当前日期和时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "地点名称，如'北京'、'东京'",
                    }
                },
                "required": ["location"],
            },
        },
    }
]

TOOL_MAP = {"get_current_time": get_current_time}
