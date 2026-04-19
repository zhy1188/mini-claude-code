# 主 Agent 与子 Agent 的协作机制

## 一、概述

NexusAgent 的主 Agent 和子 Agent 采用 **中心化编排 + 隔离执行** 模式。主 Agent 拥有完整的上下文、所有工具和权限系统；子 Agent 是轻量的、上下文隔离的执行单元，只获得有限的工具集，完成独立任务后以结构化结果返回给主 Agent。

### 为什么需要子 Agent

1. **并行化**：主 Agent 识别到多个可独立执行的任务时，可以并发派生子 Agent（如同时读取 3 个文件、同时运行 2 个测试），减少总等待时间
2. **上下文隔离**：子 Agent 的消息历史不污染主上下文，避免中间过程挤占主对话的 token 预算
3. **能力约束**：通过工具过滤，限制子 Agent 只能做特定类型的事（如研究助手不能写文件）
4. **预算控制**：子 Agent 有独立的 token 上限（50K）和迭代上限（20 次），防止失控

---

## 二、架构总览

```
                    ┌───────────────────────────────────────┐
                    │            MasterAgent                 │
                    │  ┌───────────────┐  ┌───────────────┐ │
                    │  │ 完整上下文     │  │ 所有工具       │ │
                    │  │ ContextManager│  │ ToolRegistry  │ │
                    │  └───────┬───────┘  └───────┬───────┘ │
                    │          │                  │         │
                    │          ▼                  ▼         │
                    │  ┌──────────────────────────────────┐ │
                    │  │   AgentOrchestrator (编排器)      │ │
                    │  │   - 持有 LLM 引用                 │ │
                    │  │   - 持有 ToolRegistry 引用        │ │
                    │  │   - asyncio.gather 并发执行       │ │
                    │  └───────────────┬──────────────────┘ │
                    └──────────────────┼──────────────────┘
                                       │
                     ┌─────────────────┼─────────────────┐
                     ▼                 ▼                 ▼
              ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
              │  SubAgent 1 │  │  SubAgent 2 │  │  SubAgent 3 │
              │  ┌────────┐ │  │  ┌────────┐ │  │  ┌────────┐ │
              │  │独立上下文│ │  │  │独立上下文│ │  │  │独立上下文│ │
              │  │50K token│ │  │  │50K token│ │  │  │50K token│ │
              │  │受限工具集│ │  │  │受限工具集│ │  │  │受限工具集│ │
              │  └────────┘ │  │  └────────┘ │  │  └────────┘ │
              └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
                     │                │                │
                     ▼                ▼                ▼
              ┌────────────────────────────────────────────────┐
              │           AgentResult (结构化结果)              │
              │  status | summary | artifacts | token_usage    │
              └────────────────────────────────────────────────┘
```

---

## 三、核心组件详解

### 3.1 三种子 Agent 类型

定义在 `agent/orchestrator.py:11-37`：

| 类型 | 系统提示 | 可用工具 | 用途 |
|------|---------|---------|------|
| **general** | "你是专注的编程助手" | Read, Write, Bash, Glob, Grep | 通用编程任务 |
| **research** | "你是研究助手，不要修改文件" | Read, Glob, Grep | 只读分析，无写/执行权限 |
| **code** | "你是代码修改助手" | Read, Write, Bash, Glob, Grep | 代码变更和验证 |

**关键设计——动态工具过滤**：
```python
_SUBAGENT_TOOLS = {
    "general": ["Read", "Write", "Bash", "Glob", "Grep"],
    "research": ["Read", "Glob", "Grep"],  # 只读，没有 Write/Bash
    "code": ["Read", "Write", "Bash", "Glob", "Grep"],
}
```

`research` 类型被剥离了 `Write` 和 `Bash` 工具，这意味着即使 LLM 想修改文件或执行命令，API 请求中也不会包含这些工具的 schema，LLM **根本无法生成对应的工具调用**。这是比"运行时拦截"更安全的约束方式——从源头上消除能力。

### 3.2 SubTask — 任务定义

```python
class SubTask:
    def __init__(self, description, tool_names=None, subagent_type="general", prompt=""):
        ...

    @property
    def resolved_tool_names(self) -> list[str]:
        """显式列表 > 类型默认值"""
        if self.tool_names is not None:
            return self.tool_names
        return list(_SUBAGENT_TOOLS.get(self.subagent_type, ["Read", "Grep"]))
```

工具解析优先级：
1. **显式传入 `tool_names`**（当前 TaskTool 未使用此字段，预留扩展）
2. **按 `subagent_type` 查 `_SUBAGENT_TOOLS` 默认表**
3. **回退到 `["Read", "Grep"]`**（最小安全集）

### 3.3 SubAgent — 隔离执行单元

定义在 `agent/sub_agent.py:11-133`，核心设计点：

#### 3.3.1 独立上下文

```python
class SubAgent:
    def __init__(self, task, tools, llm, system_prompt, max_tokens=50_000, max_iterations=20):
        self.task = task
        self.llm = llm                              # 共享 LLM 客户端
        self.registry = ToolRegistry()              # 独立注册表（不是主注册表的引用）
        for tool in tools:
            self.registry.register(tool)            # 只注册被分配的工具
        self.system_prompt = system_prompt
        self.context = ContextManager(max_tokens=max_tokens, compact_threshold=0.8)  # 独立上下文
        self.tool_calls_made = 0
        self.token_usage = 0
```

**关键细节**：SubAgent 创建了一个**全新的 `ToolRegistry` 实例**，只包含被分配的工具。它不持有主注册表的引用，这意味着：
- 子 Agent **无法访问**未分配给它的工具
- 子 Agent 的工具调用不会影响到主 Agent 的工具列表
- 每个子 Agent 的上下文是物理隔离的

#### 3.3.2 简化循环

SubAgent 拥有自己的简化版 Agent 循环（`sub_agent.py:40-104`），与 MasterAgent 的主循环相比，缺少：
- ❌ 状态机（FSM）
- ❌ 检查点系统
- ❌ 权限门控（PermissionGate）
- ❌ 钩子系统
- ❌ 主动上下文检索
- ❌ 上下文压缩
- ✅ 保留：LLM 流式调用 + 工具执行 + 迭代限制

**为什么简化？** 子 Agent 是"一次性"的执行单元，不需要主 Agent 那样完整的生命周期管理。它的简化循环就是一个 `for` 循环：调 LLM → 执行工具 → 循环，直到返回文本或达到迭代上限。

#### 3.3.3 产物追踪

```python
# 追踪产出品
if tc.name == "Write" and not result.is_error:
    path = tc.input.get("file_path", "")
    if path:
        artifacts.append(path)
```

SubAgent 自动追踪所有成功的 `Write` 操作，记录修改了哪些文件。这个信息通过 `AgentResult.artifacts` 返回给主 Agent。

#### 3.3.4 结构化结果

```python
class AgentResult(BaseModel):
    task: str                  # 任务描述
    status: str = "success"    # success / error
    summary: str = ""          # LLM 的文本回复
    artifacts: list[str]       # 修改的文件列表
    tool_calls_made: int       # 工具调用次数
    token_usage: int           # token 消耗
```

这是一个统一的返回格式，主 Agent 收到后可以清楚地知道每个子 Agent 做了什么、花了多少资源。

---

## 四、协作流程：从主 Agent 到子 Agent 再回来

### 4.1 连接关系建立

定义在 `agent/master.py:102-137`，初始化顺序是关键：

```python
# 1. 创建编排器（此时 TaskTool 还没有编排器引用）
self.orchestrator = AgentOrchestrator(self.llm, self.registry)

# 2. 将编排器注入到 TaskTool 中（打破循环依赖）
self._wire_task_tool()

def _wire_task_tool(self):
    task = self.registry.get("Task")
    if isinstance(task, TaskTool):
        task.set_orchestrator(self.orchestrator, self.registry)
```

**为什么需要 `_wire_task_tool()`？** 这是一个循环依赖问题：
- `MasterAgent` 需要 `AgentOrchestrator`，它需要 `ToolRegistry`
- `TaskTool` 是注册在 `ToolRegistry` 中的工具
- `TaskTool` 需要引用 `AgentOrchestrator` 才能派生子 Agent
- 但 `AgentOrchestrator` 创建时，`TaskTool` 已经注册在 registry 里了

解法：**先创建，后连接**。`TaskTool` 初始化时 `orchestrator=None`，在 `MasterAgent.__init__` 的最后阶段通过 `set_orchestrator()` 注入引用。

### 4.2 完整调用链

```
用户输入: "帮我分析 auth.py 和 db.py 的性能问题"

┌─────────────────────────────────────────────────────────┐
│  MasterAgent.run(user_input)                            │
│  状态: idle → gathering → thinking                       │
│                                                         │
│  LLM 返回: "我将分别分析这两个文件的性能"                   │
│       + ToolCall(Task, "分析 auth.py 性能")               │
│       + ToolCall(Task, "分析 db.py 性能")                 │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  MasterAgent → 状态切换到 acting                          │
│  执行 TaskTool.execute()                                  │
│  TaskTool 内部:                                          │
│    1. 创建 SubTask(description="分析 auth.py 性能")       │
│    2. 调用 self._orchestrator.spawn([task])               │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  AgentOrchestrator.spawn([task1, task2])                  │
│                                                         │
│  for task in tasks:                                     │
│    1. tools = 从主注册表中筛选出该类型需要的工具             │
│    2. 创建 SubAgent(task=task.desc, tools=tools, ...)    │
│                                                         │
│  await asyncio.gather(                                   │
│      agent1.run(),   ← 并发执行                           │
│      agent2.run(),                                      │
│      return_exceptions=True                             │
│  )                                                      │
└────────────────────────┬────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              ▼                      ▼
┌──────────────────────┐  ┌──────────────────────┐
│  SubAgent 1 运行      │  │  SubAgent 2 运行      │
│  独立 LLM 调用         │  │  独立 LLM 调用         │
│  独立工具执行          │  │  独立工具执行          │
│  独立上下文            │  │  独立上下文            │
│  最多 20 次迭代        │  │  最多 20 次迭代        │
│  token 上限 50K       │  │  token 上限 50K       │
│                      │  │                      │
│  返回 AgentResult:    │  │  返回 AgentResult:    │
│  status=success       │  │  status=success       │
│  summary="auth.py..." │  │  summary="db.py..."   │
│  token_usage=3200     │  │  token_usage=2800     │
└──────────┬───────────┘  └──────────┬───────────┘
           │                         │
           └──────────┬──────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  AgentOrchestrator 聚合结果                               │
│  处理异常（如果有）                                        │
│  返回 list[AgentResult]                                  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  TaskTool.execute() 收到结果                               │
│  构造 ToolResult:                                        │
│    content = "Sub-agent completed:\n{summary}"            │
│    metadata = {tool_calls_made, token_usage, artifacts}  │
│  返回给 MasterAgent                                       │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  MasterAgent 收到 ToolResult                              │
│  将结果加入消息历史:                                       │
│    ToolResultMessage(content=..., tool_call_id=...)       │
│                                                         │
│  状态: acting → gathering → thinking                      │
│  带着子 Agent 的结果再次调用 LLM                            │
│  LLM 汇总两个子 Agent 的发现并回复用户                       │
│                                                         │
│  状态: thinking → verifying → done                        │
└─────────────────────────────────────────────────────────┘
```

### 4.3 主 Agent 对子 Agent 结果的消费

子 Agent 的结果以 `ToolResultMessage` 形式注入主 Agent 的消息历史（`master.py:323-329`）：

```python
tool_msg = ToolResultMessage(
    content=result_content,        # "Sub-agent completed:\n{summary}"
    tool_call_id=tc.id,
    tool_name=tc.name,             # "Task"
)
self.context.add_message(tool_msg)
```

然后主 Agent **再次循环**（`continue` → 回到循环开头 → 调 LLM），LLM 看到工具结果后，可以继续：
- 发起更多 Task 调用（更多子 Agent）
- 或者返回纯文本回复用户

---

## 五、关键设计决策

### 5.1 为什么子 Agent 没有权限系统

子 Agent **不经过 PermissionGate**。原因：
1. **能力已被工具过滤限制**：子 Agent 只拥有分配的工具，不需要额外的权限检查
2. **权限检查在主 Agent 层**：主 Agent 决定是否调用 Task 工具（`Task` 的权限是 "ask"），用户在此层确认
3. **用户体验**：如果每个子 Agent 的工具调用都弹出权限确认，交互会变得很嘈杂

### 5.2 为什么子 Agent 不共享主上下文

如果子 Agent 直接读写主上下文的消息列表，会导致：
- **token 污染**：子 Agent 的中间步骤（"我读了这个文件，然后..."）挤占主对话的 token 预算
- **状态不一致**：多个子 Agent 并发修改同一消息列表需要加锁
- **压缩干扰**：主 Agent 的压缩逻辑会被子 Agent 的消息打乱

**隔离方案的代价**：子 Agent 看不到主对话的上下文。它只知道 `task.description` 和自己的 `system_prompt`。所以主 Agent 需要通过精心设计的任务描述，把子 Agent 需要的上下文传递进去。

### 5.3 并发执行 vs 顺序执行

```python
results = await asyncio.gather(
    *[agent.run() for agent in agents],
    return_exceptions=True,
)
```

使用 `asyncio.gather` 实现并发，而不是逐个 `await`。关键区别：
- **并发**：3 个子 Agent 同时调 LLM、同时执行工具，总耗时 ≈ max(单个耗时)
- **顺序**：3 个子 Agent 依次执行，总耗时 = sum(单个耗时)

`return_exceptions=True` 确保即使某个子 Agent 抛出异常，其他子 Agent 仍能完成，异常被包装成 `AgentResult(status="error")` 而不是中断整个流程。

### 5.4 资源限制

| 维度 | 子 Agent 限制 | 主 Agent 限制 |
|------|-------------|-------------|
| Token 上限 | 50,000 | 200,000（可配置） |
| 迭代次数 | 20 | 50（可配置） |
| 压缩阈值 | 80% | 75%（可配置） |
| 工具数量 | 按类型过滤 | 全部 |

子 Agent 的限制更严格，因为它是一个"专注"的执行单元，不应该进行长时间的对话式交互。

---

## 六、涉及文件

| 文件 | 职责 |
|------|------|
| `agent/orchestrator.py` | 子 Agent 编排器，并发调度，工具过滤表 |
| `agent/sub_agent.py` | 子 Agent 实现，隔离上下文，简化循环 |
| `tools/builtin/task.py` | TaskTool，主 Agent 调用子 Agent 的入口 |
| `agent/master.py:102-137` | 编排器创建与 TaskTool 连接 |
| `models.py:91-97` | AgentResult 结构化结果模型 |
