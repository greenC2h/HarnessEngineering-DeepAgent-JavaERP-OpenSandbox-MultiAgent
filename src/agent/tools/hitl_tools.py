"""需要人工补充上下文时使用的 Human-in-the-Loop 工具。"""

from __future__ import annotations

import json

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def request_additional_info(information_needed: str, context: str = "") -> str:
    """暂停当前任务，要求用户补充继续执行所需的任意信息。

    Args:
        information_needed: 需要用户确认、选择或补充的内容及原因。
        context: 可选的已知上下文，帮助用户判断如何补充。

    Returns:
        会话恢复时由前端提交的自由文本补充内容。
    """
    # interrupt 会保存当前图状态；恢复后从同一调用点返回前端提供的数据。
    response = interrupt(
        {
            "type": "information_request",
            "information_needed": information_needed,
            "context": context,
        }
    )
    return json.dumps(response, ensure_ascii=False)
