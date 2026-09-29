"""构造 Agent 共用的上下文压缩和调用次数保护中间件。"""

from __future__ import annotations

from typing import Any

from deepagents.middleware.summarization import (
    SummarizationToolMiddleware,
    create_summarization_middleware,
)
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel


COMPACTION_SYSTEM_PROMPT = """
当已完成一段较长的分析、已消化子 Agent 的长报告，且接下来需要继续处理新阶段任务时，
可调用 compact_conversation 压缩已不再需要逐条保留的中间过程。摘要必须保留已确认的业务结论、
订单字段、审批或补充信息状态、异步 task_id、图表 artifact_id 与未完成事项。
""".strip()


def build_agent_protection_middleware(
    *,
    backend: Any,
    summary_model: BaseChatModel,
    model_run_limit: int,
    tool_run_limit: int,
    enable_compaction_tool: bool = False,
) -> list[Any]:
    """创建一套摘要和循环保护中间件。

    自动摘要中间件与可选的 ``compact_conversation`` 工具共享同一摘要实例，
    因此手动和自动压缩会复用同一份状态和历史归档位置。调用次数只限制当前
    Agent run，避免长期会话因历史累计而失效。
    """
    summarization = create_summarization_middleware(summary_model, backend)
    middleware: list[Any] = [summarization]
    if enable_compaction_tool:
        middleware.append(
            SummarizationToolMiddleware(
                summarization,
                system_prompt=COMPACTION_SYSTEM_PROMPT,
            )
        )
    middleware.extend(
        [
            ModelCallLimitMiddleware(
                run_limit=model_run_limit,
                exit_behavior="end",
            ),
            ToolCallLimitMiddleware(
                run_limit=tool_run_limit,
                exit_behavior="end",
            ),
        ]
    )
    return middleware
