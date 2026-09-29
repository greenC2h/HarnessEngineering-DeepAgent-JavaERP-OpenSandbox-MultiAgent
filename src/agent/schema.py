
"""采购 Agent、对话和会话历史共用的数据模型。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

@dataclass
class ProcurementContext:
    """
    运行时上下文，由调用方在 invoke 时传入。
    用于传递当前用户身份等基础信息。
    """
    user_id: str  # 必填，用户唯一标识。
    username: str  # 必填，用户姓名或登录名。


@dataclass
class AsyncSandboxContext:
    """传给 Agent Protocol 异步图的身份和共享沙箱引用。"""

    user_id: str
    username: str
    sandbox_id: str


@dataclass
class UserPreferences:
    """表示持久化在用户 StoreBackend 中的精简个性化偏好。"""

    recent_queries: list[str] = field(default_factory=list)
    preferred: dict[str, Any] = field(default_factory=dict)


# ============================================================
# 对话相关
# ============================================================


class ChatRequest(BaseModel):
    """
    接收单轮对话请求，并兼容旧版姓名字段。
    """

    message: str = Field(..., min_length=1, description="用户消息")
    thread_id: Optional[str] = Field(None, description="会话 ID，为空则创建新会话")
    user_id: str = Field("laoxiao", min_length=1, description="用户唯一标识")
    username: Optional[str] = Field(None, min_length=1, description="用户名")
    name: Optional[str] = Field(None, min_length=1, description="username 的兼容字段")

    @model_validator(mode="after")
    def set_username(self) -> "ChatRequest":
        """
        统一 `username` 和旧版 `name` 字段，保证后续调用链始终可读取用户名。
        """
        # 优先使用显式 username；旧客户端只传 name 时保持兼容，均未提供时退回 user_id。
        self.username = self.username or self.name or self.user_id
        return self


# ============================================================
# 认证相关
# ============================================================


class CaptchaResponse(BaseModel):
    """返回一次性验证码图片及其短期标识。"""

    captcha_id: str = Field(..., description="验证码标识")
    image: str = Field(..., description="data:image/svg+xml;base64 图片")


class AuthRequest(BaseModel):
    """接收账号密码登录请求。"""

    account: str = Field(..., min_length=6, max_length=20, pattern=r"^\d+$", description="6-20 位数字账号")
    password: str = Field(..., min_length=8, max_length=64, description="8-64 位密码")


class RegisterRequest(AuthRequest):
    """接收注册请求；注册必须携带一次性数字验证码。"""

    captcha_id: str = Field(..., min_length=1, description="验证码标识")
    captcha: str = Field(..., min_length=1, max_length=8, description="验证码")


class AuthResponse(BaseModel):
    """返回认证后的持久化用户身份。"""

    user_id: str = Field(..., description="用户唯一标识")
    username: str = Field(..., description="用户名")


class Message(BaseModel):
    """
    表示前端展示的一条用户、助手或工具消息。
    """

    id: str = Field(..., description="消息唯一标识")
    role: str = Field(..., description="消息角色: user/assistant/tool/delegation")
    content: str = Field("", description="消息内容")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="工具调用信息")
    tool_call_id: Optional[str] = Field(None, description="工具调用 ID")
    source: Optional[str] = Field(None, description="消息来源: main 或子代理名称")
    visualization: Optional["Visualization"] = Field(
        None,
        description="工具结果中的可视化资源",
    )
    report: Optional["ReportArtifact"] = Field(
        None,
        description="仅可通过受控下载接口读取的沙箱分析报告",
    )
    # 以下字段只用于工具消息，使历史恢复后的展示与 SSE 过程一致。
    tool_name: Optional[str] = Field(None, description="工具名称")
    tool_status: Optional[str] = Field(None, description="工具状态: calling / done / error")
    text: Optional[str] = Field(None, description="工具结果文本")
    images: Optional[List[str]] = Field(None, description="工具结果图片列表")
    args: Optional[str] = Field(None, description="工具调用参数")
    async_task_id: Optional[str] = Field(None, description="可继续轮询的远程异步任务 ID")


class Visualization(BaseModel):
    """
    表示工具返回的图片预览或本地 HTML 图表资源入口。

    新图表只保存为本地 HTML 文件，并通过 ``link`` 与 ``download_src``
    提供打开和下载入口；不在消息中传输或嵌入原始 HTML。
    """

    kind: Literal["image", "link"] = Field(..., description="资源类型")
    src: Optional[str] = Field(None, description="图片或本地资源链接")
    artifact_id: Optional[str] = Field(None, description="持久化图表资源标识")
    mime_type: Optional[str] = Field(None, description="资源 MIME 类型")
    label: Optional[str] = Field(None, description="资源链接显示文本")
    download_src: Optional[str] = Field(None, description="HTML 图表下载链接")


class ReportArtifact(BaseModel):
    """表示仅保存在用户沙箱中的采购分析报告下载入口。"""

    report_id: str = Field(..., description="报告元数据标识，不是沙箱文件路径")
    label: str = Field("下载采购分析报告", description="下载入口显示文本")
    download_src: str = Field(..., description="按需读取沙箱文件的受控下载链接")


# Message 在关联资源模型之前声明了前向引用，定义完成后显式解析，确保 API
# 序列化时使用真正的资源模型而不是未经校验的字典。
Message.model_rebuild()


class ChatResponse(BaseModel):
    """
    返回非流式对话结果，并兼容消息列表和单轮回答两种调用方式。
    """

    thread_id: str = Field(..., description="会话 ID")
    messages: List[Message] = Field(default_factory=list, description="消息列表")
    user_id: Optional[str] = Field(None, description="用户唯一标识")
    username: Optional[str] = Field(None, description="用户名")
    answer: Optional[str] = Field(None, description="单轮对话回答")
    interrupt: Optional[Dict[str, Any]] = Field(None, description="等待恢复的中断")


class ResumeChatRequest(BaseModel):
    """
    接收中断恢复数据，并将其传给 LangGraph ``Command(resume=...)``。
    """

    resume: Dict[str, Any] = Field(..., description="补充信息或人工审批决策")
    user_id: str = Field("laoxiao", min_length=1, description="用户唯一标识")
    username: Optional[str] = Field(None, min_length=1, description="用户名")


class AsyncTaskStatusResponse(BaseModel):
    """返回异步子 Agent 任务的状态及其主会话投递状态。"""

    task_id: str = Field(..., description="Agent Protocol 任务线程 ID")
    status: str = Field(..., description="任务运行状态")
    done: bool = Field(..., description="任务是否已进入终态")
    delivered: bool = Field(False, description="终态结果是否已写入主会话")
    result: Optional[str] = Field(None, description="终态任务报告")
    visualization: Optional["Visualization"] = Field(None, description="终态任务图表资源")
    report: Optional["ReportArtifact"] = Field(None, description="终态任务的沙箱报告下载入口")
    error: Optional[str] = Field(None, description="失败原因")
    run_id: Optional[str] = Field(None, description="最近一次运行 ID")
    updated_at: Optional[str] = Field(None, description="最近更新时间")


AsyncTaskStatusResponse.model_rebuild()


# ============================================================
# 会话历史相关
# ============================================================

class Session(BaseModel):
    """
    表示侧边栏中展示的一条用户会话。
    """

    thread_id: str = Field(..., description="会话 ID")
    title: str = Field(..., description="由首条用户消息生成的会话标题")
    created_at: datetime = Field(..., description="会话创建时间")
    updated_at: datetime = Field(..., description="最后一次消息写入时间")
    message_count: int = Field(0, ge=0, description="会话中的展示消息数")


class SessionListResponse(BaseModel):
    """
    返回当前用户可访问的会话列表。
    """

    sessions: List[Session] = Field(default_factory=list, description="按更新时间倒序的会话")


class SessionMessagesResponse(BaseModel):
    """
    返回恢复单个会话所需的完整展示消息。
    """

    thread_id: str = Field(..., description="会话 ID")
    messages: List[Message] = Field(default_factory=list, description="按原顺序排列的消息")
    interrupt: Optional[Dict[str, Any]] = Field(None, description="等待恢复的中断，与 SSE 格式一致")


class DeleteSessionResponse(BaseModel):
    """
    返回删除会话后的操作结果。
    """

    success: bool = Field(..., description="是否已删除")

# ============================================================
# 进程内运行时状态
# ============================================================


@dataclass(frozen=True)
class AsyncTaskBinding:
    """记录远程异步任务归属的主会话，用于完成后回写 checkpoint。"""

    task_id: str
    user_id: str
    username: str
    thread_id: str

@dataclass
class UserGroup:
    """当前进程中的用户分组索引。

    对话状态和 memories 由 PostgreSQL checkpoint/store 持久化；此结构只
    负责在当前进程内归拢用户的 Agent 实例和会话 ID。
    """

    username: str  # 用户最近一次使用的名称
    thread_ids: set[str] = field(default_factory=set)  # 用户关联的会话 ID
    agent: Any | None = None  # 用户专属的 Agent 实例
