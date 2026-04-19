# NexusAgent — 仿 Claude Code 的 AI Agent 终端

## 1. 项目背景与目标

### 1.1 背景
Claude Code 是 Anthropic 开发的终端 AI 编程助手，基于 Bun/TypeScript 实现。其核心架构特点包括：
- 单线程主循环（Gather → Act → Verify）
- React + Ink 的 TUI 渲染
- 扁平化消息历史 + Compaction 压缩
- MCP (Model Context Protocol) 工具扩展
- CLAUDE.md 持久化项目上下文
- 子 Agent 并行执行
- Hooks 生命周期钩子
- 严格的权限/安全框架

### 1.2 目标
用 Python 实现一个精简但完整的 Claude Code 克隆，覆盖其核心架构模式，用于面试展示。重点不在功能数量，而在**架构设计的深度和可讲性**。

### 1.3 核心设计原则
- **Harness Engineering**: 不是 LLM 的薄包装，而是一个让模型感知和行动的**运行时环境**
- **Thin Loop, Deep Tools**: 循环简单，工具深入
- **Immutable State**: 单一扁平消息历史，状态可追溯
- **Security First**: 严格的安全边界和权限控制

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                        Terminal UI                            │
│  (Rich: 输入框、流式输出、状态栏、工具结果面板)                 │
├──────────────────────────────────────────────────────────────┤
│                     Agent Orchestrator                        │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │ Master   │  │ Sub-Agent    │  │ Context Manager          │ │
│  │ Agent    │─>│ Pool         │  │ (Compaction, Trimming,  │ │
│  │ (主循环) │  │ (并发执行)   │  │  Token Budget)           │ │
│  └──────────┘  └──────────────┘  └─────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│                      Tool Runtime                            │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────────────┐  │
│  │ Builtin    │ │ MCP        │ │ Hooks                    │  │
│  │ Tools      │ │ Bridges    │ │ (Pre/Post/Tool)          │  │
│  │ (7个核心)  │ │ (stdio/sse)│ │ (生命周期钩子)            │  │
│  └────────────┘ └────────────┘ └──────────────────────────┘  │
├──────────────────────────────────────────────────────────────┤
│                      LLM Client Layer                        │
│  ┌─────────────────┐  ┌──────────────────────────────────┐   │
│  │ Anthropic API   │  │ OpenAI-Compatible (vLLM, Ollama) │   │
│  │ (Claude)        │  │ (任何兼容 API)                     │   │
│  └─────────────────┘  └──────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────┤
│                      Persistence Layer                       │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐               │
│  │ Session    │ │ Memory     │ │ Project    │               │
│  │ (JSON)     │ │ (Vector DB)│ │ Context    │               │
│  │            │ │            │ │ (.nexus.md)│               │
│  └────────────┘ └────────────┘ └────────────┘               │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 核心子系统详细设计

### 3.1 Agent 主循环 (Master Agent Loop)

**设计参考**: Claude Code 的单线程主循环，Gather → Act → Verify 三阶段。

```python
class AgentState(Enum):
    IDLE = "idle"
    GATHERING = "gathering"      # 收集上下文（读文件、搜索代码）
    THINKING = "thinking"         # 等待 LLM 响应
    ACTING = "acting"            # 执行工具调用
    VERIFYING = "verifying"      # 验证结果
    COMPACTING = "compacting"    # 上下文压缩
    DONE = "done"
    ERROR = "error"

class MasterAgent:
    """
    单线程主循环，管理整个对话生命周期。
    核心循环:
        1. 接收用户输入
        2. 构建消息列表（系统提示 + 历史 + 工具定义）
        3. 调用 LLM
        4. 解析响应（文本 or 工具调用）
        5. 如果是工具调用 → 执行 → 结果回传 → 回到 3
        6. 如果是文本响应 → 检查是否需要压缩上下文 → 回到 1
    """

    async def run_loop(self, user_input: str):
        self.state = AgentState.GATHERING
        self.history.append(UserMessage(content=user_input))

        while self.state != AgentState.DONE:
            # 检查是否需要上下文压缩
            if self.context_manager.needs_compaction():
                await self.compact_context()

            # 构建 LLM 请求
            messages = self.context_manager.build_messages()
            tools = self.tool_registry.get_tool_definitions()

            # 调用 LLM（流式）
            self.state = AgentState.THINKING
            response = await self.llm_client.stream(
                messages=messages, tools=tools, system=self.system_prompt
            )

            # 处理响应
            if response.tool_calls:
                self.state = AgentState.ACTING
                for tool_call in response.tool_calls:
                    result = await self.execute_tool(tool_call)
                    self.history.append(ToolResultMessage(tool_call, result))
            elif response.content:
                self.state = AgentState.VERIFYING
                self.history.append(AssistantMessage(content=response.content))
                self.state = AgentState.DONE
```

**面试要点**:
- 单线程设计避免竞态条件，状态机保证流程可控
- Gather→Act→Verify 是 Claude Code 的核心设计模式
- 循环内嵌上下文压缩检查，体现对 LLM 约束的理解

---

### 3.2 工具系统 (Tool System)

**设计参考**: Claude Code 的 7 个内置工具 + MCP 扩展协议。

#### 3.2.1 工具抽象

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field

class ToolParameter(BaseModel):
    type: str
    description: str
    required: bool = False

class Tool(ABC):
    """所有工具的基类，直接映射到 LLM Tool Use API"""
    name: str
    description: str
    parameters: dict[str, ToolParameter]  # JSON Schema 格式

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        ...

    def to_llm_schema(self) -> dict:
        """转换为 LLM API 需要的 JSON Schema 格式"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    k: {"type": v.type, "description": v.description}
                    for k, v in self.parameters.items()
                },
                "required": [k for k, v in self.parameters.items() if v.required],
            },
        }

class ToolResult(BaseModel):
    content: str
    is_error: bool = False
    metadata: dict = Field(default_factory=dict)
```

#### 3.2.2 7 个核心内置工具（对标 Claude Code）

| 工具 | 对应 Claude Code 工具 | 功能 |
|------|----------------------|------|
| `Read` | `Read` | 读取文件内容，支持行范围、图片 |
| `Write` | `Edit`/`Write` | 写入/创建文件，支持精确字符串替换 |
| `Bash` | `Bash` | 执行 shell 命令，超时控制，安全限制 |
| `Glob` | `Glob` | 文件模式匹配搜索 |
| `Grep` | `Grep` | 文件内容正则搜索 |
| `Task` | `Agent` | 启动子 Agent 并行任务 |
| `NotebookEdit` | `NotebookEdit` | 编辑 Jupyter Notebook |

#### 3.2.3 Bash 工具的安全设计

```python
class BashTool(Tool):
    """
    安全受限的 Bash 执行器：
    - 超时控制（默认 120s）
    - 危险命令拦截（rm -rf /, sudo 等）
    - 工作目录锁定
    - 输出截断（防止上下文爆炸）
    """
    DANGIOUS_PATTERNS = ["rm -rf /", "sudo", ":(){:|:&};:"]
    MAX_OUTPUT_BYTES = 50_000
    DEFAULT_TIMEOUT = 120

    async def execute(self, command: str, timeout: int = None, dangerous: bool = False):
        # 1. 安全检查
        if not dangerous:
            self._check_dangerous(command)

        # 2. 执行
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir,
        )

        # 3. 超时控制 + 输出截断
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or self.DEFAULT_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(content=f"命令超时 ({self.DEFAULT_TIMEOUT}s)", is_error=True)

        # 4. 输出截断
        output = self._truncate_output(stdout.decode() + stderr.decode())
        return ToolResult(content=output, metadata={"exit_code": proc.returncode})
```

#### 3.2.4 MCP 桥接

```python
class MCPBridge:
    """
    实现 MCP (Model Context Protocol) 的子集：
    - 连接本地 stdio MCP Server
    - 自动发现工具 (tools/list)
    - 调用远程工具 (tools/call)
    - 工具定义合并到 ToolRegistry

    MCP 协议流程:
        1. 启动子进程（stdio 通信）
        2. JSON-RPC 初始化握手
        3. tools/list 获取工具定义
        4. tools/call 执行工具
    """
    async def connect(self, command: str):
        """连接一个 stdio MCP Server"""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        # JSON-RPC 初始化
        await self._jsonrpc_initialize(proc)
        # 获取工具列表
        tools = await self._jsonrpc_list_tools(proc)
        # 注册到工具注册表
        for tool in tools:
            self.registry.register(MCPWrappedTool(proc, tool))
```

**面试要点**:
- 工具抽象是 LLM Agent 的核心，Tool→JSON Schema→LLM→Tool Call→Execute 是标准流程
- MCP 协议是 Anthropic 提出的开放标准，理解其 JSON-RPC 通信模式
- Bash 工具的安全设计体现生产意识

---

### 3.3 上下文管理系统 (Context Manager)

**设计参考**: Claude Code 的 Compaction + CLAUDE.md + 工具结果管理。

```python
class ContextManager:
    """
    管理 LLM 上下文窗口的全生命周期。
    核心策略:
        1. Token 预算追踪（实时计算已用 token 数）
        2. 渐进式压缩（Compaction）
           - 阶段1: 删除最老的非关键消息
           - 阶段2: 调用 LLM 摘要历史消息
           - 阶段3: 极端压缩（仅保留系统提示+最近消息）
        3. 工具结果管理（截断长输出、清除过时结果）
        4. 持久化上下文（.nexus.md 文件，类似 CLAUDE.md）
    """

    def __init__(self, max_tokens: int = 200_000, compact_threshold: float = 0.75):
        self.max_tokens = max_tokens
        self.compact_threshold = compact_threshold  # 75% 时触发压缩
        self.messages: list[Message] = []
        self.system_prompt: str = ""  # 始终保留，不计入动态 token

    def needs_compaction(self) -> bool:
        used = self.count_tokens()
        return used > self.max_tokens * self.compact_threshold

    async def compact_context(self, llm: LLMClient):
        """
        Compaction 是 Claude Code 的核心上下文管理技术。
        将消息历史发给 LLM，让它生成压缩摘要。
        """
        # 分离关键消息（系统提示、最近一轮对话）
        critical = self._extract_critical_messages()
        compressible = self._get_compressible_messages()

        # 调用 LLM 压缩
        summary = await llm.compress_messages(compressible)

        # 重建消息列表：系统提示 + 摘要 + 关键消息
        self.messages = [
            SystemMessage(content=self.system_prompt),
            AssistantMessage(content=f"[上下文压缩摘要]\n{summary}"),
            *critical,
        ]

    def build_messages(self) -> list[dict]:
        """构建 LLM API 需要的消息格式"""
        return [msg.to_api_format() for msg in self.messages]

    def count_tokens(self) -> int:
        """实时 token 计数"""
        return sum(msg.token_count for msg in self.messages)
```

#### 3.3.1 Token 计数器

```python
class TokenCounter:
    """
    多层 Token 计数策略：
        1. 优先使用 API 返回的 usage 字段（精确）
        2. 降级使用 tiktoken 估算
        3. 粗略估算：字符数 / 4（应急）
    """
    @classmethod
    def count(cls, text: str, model: str = "claude-sonnet-4-6") -> int:
        # 优先使用 anthropic 官方 token 计数
        # 降级方案
        return len(text) // 4
```

#### 3.3.2 .nexus.md 项目上下文（对标 CLAUDE.md）

```
项目根目录下的 .nexus.md 文件：
- 自动加载为系统提示的一部分
- 不会被上下文压缩删除
- 支持模式匹配（特定目录下使用特定上下文文件）
- 内容示例：项目架构、编码规范、技术栈说明
```

**面试要点**:
- Context Engineering 是 AI Agent 领域最核心的挑战之一
- Compaction 类比于操作系统的内存分页/虚拟内存
- 理解 token 作为 LLM 的"内存单位"，管理它就像管理 RAM

---

### 3.4 子 Agent 系统 (Sub-Agent Orchestration)

**设计参考**: Claude Code 的 Agent 工具，支持并发子任务。

```python
class SubAgent:
    """
    子 Agent 是隔离的执行单元：
    - 独立的消息历史（不污染主 Agent 上下文）
    - 受限的工具集（根据任务类型分配）
    - 结构化返回结果
    """

    def __init__(self, task: str, tools: list[Tool], system_prompt: str = None):
        self.task = task
        self.tools = tools
        self.system_prompt = system_prompt or self._default_prompt()
        self.history: list[Message] = [UserMessage(content=task)]
        self.result: AgentResult | None = None

class AgentResult(BaseModel):
    """子 Agent 返回给父 Agent 的结构化结果"""
    task: str
    status: Literal["success", "error", "cancelled"]
    summary: str           # 人类可读的摘要
    artifacts: list[str]   # 产出的文件路径
    tool_calls_made: int   # 执行了多少次工具调用
    token_usage: int       # 消耗了多少 token

class AgentOrchestrator:
    """
    编排器：决定何时派生子 Agent、如何并发、如何聚合结果。

    派生策略:
        1. 任务分解：主 Agent 识别可并行的子任务
        2. 工具路由：根据子任务类型分配工具集
        3. 并发执行：asyncio.gather 并行运行
        4. 结果聚合：收集所有子结果，整合到主上下文
    """

    async def spawn_sub_agents(self, sub_tasks: list[SubTask]) -> list[AgentResult]:
        """并发执行多个子 Agent"""
        agents = [SubAgent(task.description, self._select_tools(task)) for task in sub_tasks]

        # 并发执行
        results = await asyncio.gather(
            *[agent.run(self.llm_client) for agent in agents],
            return_exceptions=True,
        )

        # 错误隔离：单个子 Agent 失败不影响其他
        return [
            AgentResult(status="success", summary=r) if not isinstance(r, Exception)
            else AgentResult(status="error", summary=str(r))
            for r in results
        ]
```

**面试要点**:
- 子 Agent 解决的是上下文隔离问题：每个子任务有独立上下文窗口
- 并发执行利用 asyncio 实现真正的并行 I/O
- 结果聚合是一个设计难点：如何在有限 token 内整合多个子结果

---

### 3.5 权限与安全系统 (Permission System)

**设计参考**: Claude Code 的权限门控和信任策略。

```python
class PermissionLevel(Enum):
    ASK = "ask"              # 每次都询问用户
    AUTO_APPROVE = "approve" # 自动通过
    DENY = "deny"            # 始终拒绝

class TrustPolicy(BaseModel):
    """
    声明式信任策略配置：
    - 按工具配置权限
    - 支持通配符匹配
    - 支持命令级别的安全分类
    """
    tool_permissions: dict[str, PermissionLevel] = {
        "Read": PermissionLevel.AUTO_APPROVE,
        "Glob": PermissionLevel.AUTO_APPROVE,
        "Grep": PermissionLevel.AUTO_APPROVE,
        "Write": PermissionLevel.ASK,
        "Bash": PermissionLevel.ASK,
        "Task": PermissionLevel.ASK,
    }

    # Bash 命令安全分类
    safe_commands: set[str] = {"ls", "cat", "echo", "find", "grep", "git status"}
    dangerous_patterns: set[str] = {"rm -rf", "sudo", "dd", "mkfs"}

class PermissionGate:
    """
    权限门控：在执行工具前拦截并检查策略。
    流程:
        1. 工具被调用
        2. PermissionGate 检查 TrustPolicy
        3. 如果 ASK → 阻塞循环，等待用户输入
        4. 如果 APPROVE → 放行
        5. 如果 DENY → 返回错误给 LLM
    """
    async def check(self, tool_call: ToolCall) -> PermissionDecision:
        policy = self.trust_policy.tool_permissions.get(
            tool_call.tool_name, PermissionLevel.ASK
        )

        if policy == PermissionLevel.AUTO_APPROVE:
            return PermissionDecision.APPROVE

        if policy == PermissionLevel.DENY:
            return PermissionDecision.DENY

        # ASK: 呈现给用户，等待确认
        return await self.prompt_user(tool_call)
```

**面试要点**:
- 声明式权限系统：配置驱动而非硬编码
- Human-in-the-loop 是 AI Agent 安全的核心模式
- 信任策略可以映射到 RBAC（基于角色的访问控制）概念

---

### 3.6 Hooks 系统 (生命周期钩子)

**设计参考**: Claude Code 的 hooks 配置，支持 pre/post/tool 钩子。

```python
class HookType(Enum):
    PRE_USER_MESSAGE = "pre_user_message"   # 用户输入前
    POST_USER_MESSAGE = "post_user_message" # 用户输入后
    PRE_TOOL_USE = "pre_tool_use"          # 工具执行前
    POST_TOOL_USE = "post_tool_use"        # 工具执行后
    PRE_RESPONSE = "pre_response"          # LLM 响应前
    POST_RESPONSE = "post_response"        # LLM 响应后

class HookConfig(BaseModel):
    """
    hooks.json 配置格式（对标 Claude Code 的 settings.json hooks）:
    {
        "hooks": {
            "pre_tool_use": {
                "matcher": "Bash",
                "command": "echo '即将执行: {command}' >> audit.log"
            },
            "post_tool_use": {
                "matcher": "*",
                "command": "python scripts/log_tool.py {tool_name} {duration}"
            }
        }
    }
    """
    hook_type: HookType
    matcher: str  # 工具名或通配符
    command: str  # 要执行的 shell 命令
    blocking: bool = False  # 是否阻塞主循环

class HookEngine:
    """
    钩子引擎：在 Agent 生命周期的关键节点触发配置的钩子。
    类似 Web 框架的 middleware 或 Git 的 hooks。
    """
    async def trigger(self, hook_type: HookType, context: dict):
        for hook in self.hooks.get(hook_type, []):
            if self._matches(hook.matcher, context):
                cmd = self._interpolate(hook.command, context)
                if hook.blocking:
                    result = await self._execute(cmd)
                    if result.is_error:
                        return HookResult(blocked=True, reason=result.output)
                else:
                    asyncio.create_task(self._execute(cmd))  # 后台执行
```

**面试要点**:
- Hooks 是可扩展性的关键设计：用户无需改代码即可定制行为
- 阻塞 vs 非阻塞钩子的权衡
- 类比 Git hooks、Webpack loaders、Express middleware

---

### 3.7 终端 UI (Terminal UI)

**设计参考**: Claude Code 使用 React + Ink，我们用 Rich 实现。

```python
class NexusTUI:
    """
    基于 Rich 的终端界面：
    - Prompt 输入（带命令历史）
    - 流式输出显示（逐 token 刷新）
    - 工具调用可视化（缩进、图标、状态）
    - 状态栏（token 使用量、模型名称、当前状态）
    - 分栏布局（左侧对话、右侧工具输出）
    """

    def render_streaming(self, text: str):
        """实时流式渲染：每次收到 token 时刷新显示"""
        with Live(self.console.renderable, refresh_per_second=20) as live:
            for token in text:
                live.update(Panel(token, title="Thinking"))

    def render_tool_call(self, tool_name: str, args: dict, status: str):
        """工具调用可视化"""
        status_icon = {"running": "⏳", "done": "✅", "error": "❌"}[status]
        self.console.print(Panel(
            f"[bold]{tool_name}[/bold]\n{json.dumps(args, indent=2)}",
            title=f"{status_icon} Tool Call",
            border_style={"running": "yellow", "done": "green", "error": "red"}[status],
        ))
```

---

### 3.8 LLM 客户端层

```python
class LLMClient(ABC):
    """
    抽象 LLM 客户端，支持多种后端：
    - Anthropic API（Claude）
    - OpenAI 兼容 API（vLLM, Ollama, DeepSeek 等）
    """
    @abstractmethod
    async def stream(
        self, messages: list, tools: list[dict], system: str
    ) -> LLMResponse:
        """流式请求，逐 token 返回"""
        ...

    @abstractmethod
    async def compress_messages(self, messages: list) -> str:
        """上下文压缩：将多条消息压缩为摘要"""
        ...

class AnthropicClient(LLMClient):
    """使用 anthropic SDK 连接 Claude API"""
    async def stream(self, messages, tools, system):
        async with Anthropic() as client:
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                system=system,
                messages=messages,
                tools=tools,
            ) as stream:
                async for text in stream.text_stream:
                    yield text

class OpenAICompatibleClient(LLMClient):
    """使用 OpenAI SDK 连接任何兼容 API"""
    async def stream(self, messages, tools, system):
        async with AsyncOpenAI(base_url=self.base_url, api_key=self.api_key) as client:
            response = await client.chat.completions.create(
                model=self.model, messages=[{"role": "system", "content": system}] + messages,
                tools=tools, stream=True,
            )
            async for chunk in response:
                yield chunk
```

---

### 3.9 会话与记忆系统

```python
class SessionManager:
    """
    会话管理：
    - 自动保存对话历史到 JSON
    - 支持恢复上次会话
    - 会话文件按时间戳命名
    """
    def save(self, session_id: str, messages: list[Message]):
        path = self.sessions_dir / f"{session_id}.json"
        with open(path, "w") as f:
            json.dump([msg.model_dump() for msg in messages], f, indent=2)

class MemorySystem:
    """
    跨会话记忆（类似 Claude Code 的 .claude/ 目录）：
    - 用户偏好记忆（user.md）
    - 项目记忆（project.md）
    - 反馈记忆（feedback.md）
    - 参考记忆（reference.md）
    自动加载为系统提示的一部分。
    """
    def load_memories(self, project_dir: Path) -> str:
        """加载所有记忆文件，注入系统提示"""
        memory_dir = project_dir / ".nexus" / "memory"
        memories = []
        for f in memory_dir.glob("*.md"):
            memories.append(f"## {f.stem}\n{f.read_text()}")
        return "\n\n".join(memories)
```

---

## 4. 项目结构

```
nexusagent/
├── pyproject.toml                  # 依赖: rich, pydantic, anthropic, httpx, tiktoken
├── README.md
├── nexus.toml                      # 项目配置（对标 claude_code_settings.json）
│
├── src/nexusagent/
│   ├── __init__.py
│   ├── __main__.py                 # 入口: python -m nexusagent
│   │
│   ├── main.py                     # 启动器: 解析 CLI 参数, 初始化所有组件
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── master.py               # MasterAgent: 主循环状态机
│   │   ├── sub_agent.py            # SubAgent: 隔离执行单元
│   │   ├── orchestrator.py         # AgentOrchestrator: 并发编排
│   │   └── state.py                # AgentState 枚举, AgentResult 模型
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                 # Tool ABC, ToolResult
│   │   ├── registry.py             # ToolRegistry: 注册/发现/路由
│   │   ├── builtin/
│   │   │   ├── read.py             # Read 工具
│   │   │   ├── write.py            # Write 工具
│   │   │   ├── bash.py             # Bash 工具（安全受限）
│   │   │   ├── glob.py             # Glob 工具
│   │   │   ├── grep.py             # Grep 工具
│   │   │   └── task.py             # Task 工具（子 Agent 派发）
│   │   └── mcp/
│   │       ├── __init__.py
│   │       ├── bridge.py           # MCPBridge: JSON-RPC stdio 通信
│   │       └── wrapper.py          # MCPWrappedTool: 包装远程工具
│   │
│   ├── context/
│   │   ├── __init__.py
│   │   ├── manager.py              # ContextManager: 消息管理 + 压缩
│   │   ├── compaction.py           # CompactionStrategy: LLM 摘要压缩
│   │   ├── tokenizer.py            # TokenCounter: 多层计数
│   │   └── project_context.py      # ProjectContext: .nexus.md 加载
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py                 # LLMClient ABC
│   │   ├── anthropic.py            # AnthropicClient
│   │   ├── openai_compat.py        # OpenAICompatibleClient
│   │   └── response.py             # LLMResponse, ToolCall 模型
│   │
│   ├── permission/
│   │   ├── __init__.py
│   │   ├── policy.py               # TrustPolicy: 声明式配置
│   │   └── gate.py                 # PermissionGate: 拦截/放行
│   │
│   ├── hooks/
│   │   ├── __init__.py
│   │   ├── engine.py               # HookEngine: 触发/执行
│   │   └── types.py                # HookType, HookConfig
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── session.py              # SessionManager: JSON 持久化
│   │   └── memory.py               # MemorySystem: .nexus/ 目录
│   │
│   └── tui/
│       ├── __init__.py
│       ├── app.py                  # NexusTUI: Rich 主界面
│       ├── input.py                # 命令行输入（历史、补全）
│       ├── streaming.py            # 流式输出渲染
│       └── statusbar.py            # 状态栏（token, 模型, 状态）
│
├── plugins/                        # 用户插件目录
│   └── example/
│       └── plugin.py
│
├── tests/
│   ├── test_agent.py
│   ├── test_tools.py
│   ├── test_context.py
│   ├── test_permission.py
│   ├── test_mcp.py
│   ├── test_hooks.py
│   └── test_integration.py
│
└── examples/
    ├── basic_chat.py               # 基础对话示例
    ├── code_edit.py                # 代码编辑示例
    └── multi_agent.py              # 多 Agent 示例
```

---

## 5. 数据流与关键交互

### 5.1 完整对话流程

```
用户输入 "帮我重构 agent.py"
    │
    ▼
[TUI] 显示输入，添加到历史
    │
    ▼
[ContextManager] 检查 token 使用量 → 未超阈值
    │
    ▼
[MasterAgent] 构建消息列表：系统提示 + .nexus.md + 历史 + 工具定义
    │
    ▼
[LLMClient.stream] 发送请求，逐 token 返回给 TUI 渲染
    │
    ▼
LLM 返回 ToolCall: Bash("grep -n 'def ' agent.py")
    │
    ▼
[PermissionGate] 检查 TrustPolicy → Bash = ASK → 等待用户确认
    │
    ▼
用户确认 → [HookEngine] 触发 pre_tool_use → [BashTool] 执行
    │
    ▼
[HookEngine] 触发 post_tool_use → [ContextManager] 添加工具结果到历史
    │
    ▼
LLM 继续分析（循环继续）...
    │
    ▼
LLM 返回文本响应 → [ContextManager] 添加到历史 → [MasterAgent] 回到 IDLE
```

### 5.2 上下文压缩流程

```
Token 使用量 > 75% 阈值
    │
    ▼
[ContextManager] 分离关键消息 vs 可压缩消息
    │
    ▼
[CompactionStrategy] 调用 LLM 压缩: "请摘要以下对话，保留关键决策和发现"
    │
    ▼
[ContextManager] 重建消息列表: [系统提示] + [摘要] + [最近消息]
    │
    ▼
主循环继续，上下文窗口已释放
```

### 5.3 子 Agent 派生流程

```
主 Agent 识别可并行任务:
    - "读取并分析 auth.py"
    - "读取并分析 db.py"
    - "运行测试验证"
    │
    ▼
[AgentOrchestrator] 创建 3 个 SubAgent，各自分配 Read + Bash 工具
    │
    ▼
[asyncio.gather] 并发执行 3 个子 Agent
    │
    ▼
各 SubAgent 独立循环 → 产出 AgentResult
    │
    ▼
[AgentOrchestrator] 聚合结果 → 主 Agent 上下文添加聚合摘要
```

---

## 6. 技术栈

| 组件 | 技术选型 | 理由 |
|------|---------|------|
| 核心运行时 | Python 3.12+ | 异步支持成熟，LLM 生态最完善 |
| 异步框架 | asyncio | 标准库，支持 TaskGroup、结构化并发 |
| LLM SDK | anthropic + openai | 覆盖 Claude 和所有兼容 API |
| 数据模型 | Pydantic v2 | 类型安全、验证、序列化一体 |
| 终端 UI | Rich | 最成熟的 Python TUI 库 |
| Token 计数 | tiktoken | OpenAI 官方，也适用于估算 |
| 配置管理 | Pydantic Settings | JSON 配置 + 环境变量 |
| HTTP 客户端 | httpx | 异步，SSE 流式支持 |
| 测试 | pytest + pytest-asyncio | 异步测试标准方案 |
| 包管理 | uv / pip | 现代 Python 项目管理 |

---

## 7. 面试核心讲述点

### 7.1 架构层面
1. **"我实现了 Claude Code 的核心架构模式"**
   - 单线程主循环 + 状态机 → 为什么不是多线程？（避免竞态，可追溯）
   - Harness Engineering 理念 → 模型是 Agent 的"大脑"，不是全部
   - 单一扁平消息历史 → 简单、可追溯、可压缩

2. **"工具系统是可扩展 Agent 的基础"**
   - JSON Schema 工具定义 → LLM 如何理解工具
   - Tool Call → Execute → Result 的闭环流程
   - MCP 协议如何标准化 AI-Tool 交互

### 7.2 工程层面
3. **"上下文管理是 LLM 应用最难的工程问题"**
   - Compaction 类比虚拟内存管理
   - Token 作为"内存单位"的抽象
   - 渐进式压缩策略的 trade-off

4. **"权限系统是安全的关键"**
   - 声明式 TrustPolicy vs 硬编码权限检查
   - Human-in-the-loop 的 UX 设计
   - Bash 命令的安全沙箱

### 7.3 高级模式
5. **"多 Agent 解决上下文隔离问题"**
   - 为什么需要子 Agent？（独立上下文窗口）
   - asyncio.gather 实现真正并发
   - 结果聚合的设计挑战

6. **"Hooks 是可扩展性的通用模式"**
   - 生命周期钩子如何让用户定制行为
   - 阻塞 vs 非阻塞钩子的权衡
   - 类比 Git hooks、Express middleware

### 7.4 对比 Claude Code
7. **"我知道 Claude Code 怎么做的，也知道为什么我选择不同"**
   - Claude Code 用 Bun/TypeScript，我用 Python → 面试中可讨论 trade-off
   - Claude Code 用 React/Ink，我用 Rich → 同样的 TUI 目标，不同实现
   - Claude Code 用 JSONL 存储会话，我用 JSON → 可读性 vs 性能

---

## 8. 实现优先级（分阶段）

### Phase 1: 核心基础（必须完成）
- MasterAgent 主循环
- 3 个核心工具：Read、Write、Bash
- 基础权限系统
- 简单 TUI
- LLM 客户端（Anthropic）

### Phase 2: 工程深度（加分项）
- 完整的 7 个内置工具
- 上下文压缩（Compaction）
- SSE 流式输出
- 高级权限系统（TrustPolicy JSON）
- 会话持久化

### Phase 3: 架构野心（展示级）
- 子 Agent 系统 + 编排器
- MCP 桥接
- Hooks 系统
- .nexus.md 项目上下文
- 记忆系统

---

## 9. 配置示例

### nexus.toml（对标 Claude Code 配置）

```toml
[llm]
provider = "anthropic"           # 或 "openai"
model = "claude-sonnet-4-6"      # 或 "gpt-4o"
api_key = "${ANTHROPIC_API_KEY}" # 支持环境变量
max_tokens = 8192
temperature = 0.7

[context]
max_tokens = 200000              # 上下文窗口上限
compact_threshold = 0.75         # 75% 时触发压缩
compact_strategy = "llm_summary" # 或 "truncate_oldest"

[permissions]
Read = "approve"
Glob = "approve"
Grep = "approve"
Write = "ask"
Bash = "ask"
Task = "ask"

[bash]
timeout = 120
max_output_bytes = 50000
dangerous_patterns = ["rm -rf /", "sudo", ":(){:|:&};:"]

[hooks.pre_tool_use]
Bash = "echo '{command}' >> audit.log"

[mcp.servers]
# MCP 服务器配置
# web_search = "npx -y @anthropic/mcp-server-web-search"
```

### .nexus.md（对标 CLAUDE.md）

```markdown
# 项目上下文

## 技术栈
- Python 3.12+
- FastAPI 后端
- PostgreSQL 数据库

## 编码规范
- 使用类型注解
- 优先组合而非继承
- 错误处理用异常而非返回码

## 架构决策
- 分层架构：controller → service → repository
- 异步优先
```

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM API 调用失败 | 核心功能不可用 | 重试 + 降级 + 清晰错误信息 |
| 上下文压缩丢失关键信息 | Agent 行为异常 | 保守的压缩阈值，保留最近消息 |
| Bash 命令执行安全风险 | 系统损坏 | 危险模式拦截 + 工作目录锁定 |
| MCP 服务器不兼容 | 工具不可用 | 超时 + 隔离 + 优雅降级 |
| 子 Agent 上下文爆炸 | 主 Agent 被阻塞 | 子 Agent token 上限 + 超时 |
