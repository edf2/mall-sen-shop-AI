import os
import httpx
from datetime import datetime
from typing import Any

JAVA_BACKEND_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")
ADMIN_JWT_TOKEN = os.getenv("ADMIN_JWT_TOKEN", "")


def get_current_time(location: str = "中国") -> dict[str, Any]:
    """获取指定地点的当前日期和时间"""
    now = datetime.now()
    return {
        "location": location,
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Shanghai",
    }


async def analyze_product_sales(product_id: int, days: int = 30) -> dict[str, Any]:
    """
    分析指定商品的销售趋势
    调用 Java 后端 API: GET /api/business/ai/product-sales?productId={id}&days={days}
    返回: 历史销量、日均销量、当前库存、预计耗尽天数
    """
def _get_headers() -> dict:
    headers = {}
    if ADMIN_JWT_TOKEN:
        headers["token"] = ADMIN_JWT_TOKEN
    return headers


async def analyze_product_sales(product_id: int, days: int = 30) -> dict[str, Any]:
    """
    分析指定商品的销售趋势
    调用 Java 后端 API: GET /admin/business/ai/product-sales?productId={id}&days={days}
    返回: 历史销量、日均销量、当前库存、预计耗尽天数
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/business/ai/product-sales",
                params={"productId": product_id, "days": days},
                headers=_get_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"调用后端API失败: {str(e)}"}
        except Exception as e:
            return {"error": f"分析商品销售失败: {str(e)}"}


async def predict_stock_shortage(days_ahead: int = 7) -> list[dict[str, Any]]:
    """
    预测未来指定天数内可能缺货的商品列表
    调用 Java 后端 API: GET /admin/business/ai/stock-prediction?days={days}
    返回: [{productId, productName, currentStock, dailySales, estimatedDaysLeft}, ...]
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/business/ai/stock-prediction",
                params={"days": days_ahead},
                headers=_get_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return [{"error": f"调用后端API失败: {str(e)}"}]
        except Exception as e:
            return [{"error": f"预测缺货商品失败: {str(e)}"}]


async def generate_sales_report(start_date: str, end_date: str) -> dict[str, Any]:
    """
    生成销售趋势分析报告
    调用 Java 后端 API: GET /admin/business/ai/sales-report?start={start}&end={end}
    返回: 总销售额、销量Top商品、趋势变化等
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/business/ai/sales-report",
                params={"start": start_date, "end": end_date},
                headers=_get_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"调用后端API失败: {str(e)}"}
        except Exception as e:
            return {"error": f"生成销售报告失败: {str(e)}"}


async def get_inventory_overview() -> dict[str, Any]:
    """
    获取库存概览
    调用 Java 后端 API: GET /admin/business/ai/inventory-overview
    返回: 库存总量、零库存商品数、低库存商品数、各分类库存分布
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/business/ai/inventory-overview",
                headers=_get_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"调用后端API失败: {str(e)}"}
        except Exception as e:
            return {"error": f"获取库存概览失败: {str(e)}"}


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
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_product_sales",
            "description": "分析指定商品的销售趋势，返回历史销量、日均销量、当前库存、预计耗尽天数",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "商品ID",
                    },
                    "days": {
                        "type": "integer",
                        "description": "统计天数，默认30天",
                        "default": 30,
                    }
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_stock_shortage",
            "description": "预测未来指定天数内可能缺货的商品列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "预测未来天数，默认7天",
                        "default": 7,
                    }
                },
                "required": ["days_ahead"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_sales_report",
            "description": "生成指定日期范围的销售趋势分析报告",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "开始日期，格式YYYY-MM-DD",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束日期，格式YYYY-MM-DD",
                    }
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory_overview",
            "description": "获取库存概览，包括库存总量、零库存商品数、低库存商品数、各分类库存分布",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

TOOL_MAP = {
    "get_current_time": get_current_time,
    "analyze_product_sales": analyze_product_sales,
    "predict_stock_shortage": predict_stock_shortage,
    "generate_sales_report": generate_sales_report,
    "get_inventory_overview": get_inventory_overview,
}
