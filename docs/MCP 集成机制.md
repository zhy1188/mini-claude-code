# MCP 集成机制

## 一、概述

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，用于为 LLM 提供**与外部工具和数据源交互的标准接口**。NexusAgent 通过 `MCPBridge` 连接到本地 stdio MCP 服务器，将远程发现的工具注册到本地 `ToolRegistry`，使 LLM 能像调用内置工具一样使用外部能力。类比浏览器的扩展系统：核心功能有限，通过协议加载第三方能力。

### 为什么需要 MCP

如果所有能力都必须硬编码为内置工具（`tools/builtin/`）：
- **扩展成本高**：每增加一个能力（Web 搜索、数据库查询、API 调用）都需要修改代码
- **无法复用生态**：大量第三方 MCP 服务器已存在（文件搜索、网页抓取、日历管理等）
- **能力边界固定**：用户无法按需接入自己的工具服务器

MCP 让 NexusAgent 通过配置即可获得外部能力，无需改代码。

### MCP 与内置工具系统的关系

MCP 不是独立的子系统，它完全嵌入现有的工具架构：

```
┌───────────────────────────────────────────────────────┐
│                    main.py 启动                        │
│                                                       │
│  1. 注册内置工具: Read, Write, Bash, Glob, Grep, Task │
│  2. 创建 MCPBridge(registry)                          │
│  3. 遍历 config.mcp，connect_server()                 │
│     → 每个服务器发现的工具也注册到同一个 registry       │
└─────────────────────┬─────────────────────────────────┘
                      ▼
┌───────────────────────────────────────────────────────┐
│                  ToolRegistry                          │
│  ┌───────────┬───────────┬──────────────────────────┐│
│  │ Read      │ Write     │ Bash                     ││
│  │ (内置)    │ (内置)    │ (内置)                   ││
│  ├───────────┼───────────┼──────────────────────────┤│
│  │ mcp__web  │ mcp__db__ │ mcp__git__               ││
│  │ _search__ │ query     │ diff                     ││
│  │ (MCP)     │ (MCP)     │ (MCP)                    ││
│  └───────────┴───────────┴──────────────────────────┘│
│                                                       │
│  get_tool_definitions() → 统一返回所有工具 Schema     │
└───────────────────────────────────────────────────────┘
```

**关键设计**：MCP 工具与内置工具共享同一个 `ToolRegistry`。LLM 看到的工具列表是内置工具 + MCP 工具的合并结果，无需区分来源。

---

## 二、核心组件详解

### 2.1 MCPBridge — 服务器连接与协议管理（`tools/mcp/bridge.py`）

```python
class MCPBridge:
    _JSONRPC_TIMEOUT = 30  # JSON-RPC 请求超时（秒）

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._servers: dict[str, dict] = {}  # name -> {proc, info}

    async def connect_server(self, name: str, command: str) -> None:
    async def _jsonrpc_request(self, proc, method: str, params: dict) -> dict:
    async def _jsonrpc_notify(self, proc, method: str, params: dict) -> None:
    async def _drain_stderr(self, proc, name: str) -> None:
    async def disconnect_all(self) -> None:
```

#### 连接流程（`tools/mcp/bridge.py:36-84`）

```
connect_server("web_search", "npx -y @anthropic/mcp-server-web-search")
    │
    ▼
┌─ 1. 派生子进程 ─────────────────────────────────────┐
│  proc = asyncio.create_subprocess_shell(command,     │
│      stdin=PIPE, stdout=PIPE, stderr=PIPE)           │
│  asyncio.create_task(_drain_stderr(proc, name))     │
│  # 后台持续读取 stderr，打印服务器日志               │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─ 2. JSON-RPC 初始化握手 ────────────────────────────┐
│  _jsonrpc_request(proc, "initialize", {              │
│      "protocolVersion": "2024-11-05",                │
│      "capabilities": {},                             │
│      "clientInfo": {"name": "NexusAgent", ...}       │
│  })                                                  │
│  # 服务器返回其支持的协议版本和能力                   │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─ 3. 发送已初始化通知 ───────────────────────────────┐
│  _jsonrpc_notify(proc, "notifications/initialized", │
│                  {})                                 │
│  # 通知服务器客户端已就绪                           │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─ 4. 发现工具 ───────────────────────────────────────┐
│  _jsonrpc_request(proc, "tools/list", {})           │
│  → 返回: {"tools": [                                │
│      {"name": "search", "description": "...",       │
│       "inputSchema": {...}}, ...]}                  │
│                                                      │
│  每个工具定义 → MCPWrappedTool(proc, name, def)     │
│              → registry.register(wrapped)           │
└──────────────────────────────────────────────────────┘
```

#### JSON-RPC 通信的健壮性设计

`_jsonrpc_request`（`tools/mcp/bridge.py:86-125`）是核心通信方法，解决了三个问题：

**问题 1：单行响应假设不成立**

MCP 服务器可能在 stdout 输出日志行（非 JSON）或其他通知消息。当前实现用循环读取+异常捕获处理：

```python
while True:
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
    if not line:
        raise RuntimeError("MCP server closed connection")
    try:
        response = json.loads(line.decode())
        if "id" in response and response["id"] != request_id:
            continue  # 忽略 id 不匹配的通知消息
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        return response.get("result", {})
    except json.JSONDecodeError:
        continue  # 忽略非 JSON 行（如服务器日志）
```

**问题 2：永久阻塞**

每次 `readline()` 都有 `asyncio.wait_for(timeout=30)` 超时保护，防止服务器无响应时永久阻塞 Agent。

**问题 3：stderr 丢失**

`_drain_stderr`（`tools/mcp/bridge.py:140-151`）作为后台 asyncio task 持续读取 stderr：

```python
async def _drain_stderr(self, proc, name: str) -> None:
    while True:
        line = await proc.stderr.readline()
        if not line:
            break
        text = line.decode().strip()
        if text:
            print(f"MCP[{name}] stderr: {text}")
```

### 2.2 MCPWrappedTool — 远程工具适配器（`tools/mcp/wrapper.py`）

```python
class MCPWrappedTool(Tool):
    _EXEC_TIMEOUT = 30  # MCP 工具执行超时（秒）

    def __init__(self, proc, server_name: str, tool_def: dict):
        self.name = f"mcp__{server_name}__{tool_def['name']}"
        # 转换 MCP JSON Schema → 本地 parameters 格式
        # 转换 MCP content → 本地 ToolResult 格式
```

#### 命名约定

MCP 工具的名称格式为 `mcp__{server_name}__{tool_name}`：

```python
self.name = f"mcp__{server_name}__{tool_def['name']}"
# 例如: mcp__web_search__search
#       mcp__database__query
#       mcp__git__diff
```

**为什么需要前缀？** 防止 MCP 工具名称与内置工具冲突。如果远程服务器也提供了一个叫 "Read" 的工具，加上 `mcp__` 前缀后变成 `mcp__server__Read`，不会覆盖内置的 `Read`。

#### Schema 转换

MCP 使用 JSON Schema 格式定义工具参数（`inputSchema`），需要转换为本地 `Tool.parameters` 格式：

```python
# MCP 定义:
# "inputSchema": {
#     "properties": {"query": {"type": "string", "description": "..."}},
#     "required": ["query"]
# }

# 转换后:
self.parameters = {
    "query": {
        "type": "string",
        "description": "...",
        "required": True,
    }
}
```

#### 执行与结果解析（`tools/mcp/wrapper.py:42-87`）

MCP `tools/call` 的响应格式与本地 `ToolResult` 不同：

```python
# MCP 响应:
# {"result": {"content": [
#     {"type": "text", "text": "搜索结果..."},
#     {"type": "image", "data": "...", "mimeType": "image/png"}
# ]}}

# 解析为 ToolResult:
text_parts = []
for item in content:
    if item.get("type") == "text":
        text_parts.append(item.get("text", ""))
    elif item.get("type") == "image":
        text_parts.append("[image data]")

return ToolResult(content="\n".join(text_parts))
```

当前对 image 类型只占位输出 `[image data]`，没有解码或保存。如果未来需要支持图片，需要额外处理 base64 数据。

---

## 三、MCP 在 Agent 主循环中的集成

### 3.1 启动时连接（`main.py:59-62`）

```python
# Phase 2: MCP Bridge
mcp_bridge = MCPBridge(registry)
for server_name, command in config.mcp.items():
    await mcp_bridge.connect_server(server_name, command)
```

连接时机在内置工具注册之后、上下文管理器创建之前。这确保：
1. 内置工具已就绪，MCP 工具不会覆盖它们
2. 所有工具（内置+MCP）在 LLM 首次调用前都已注册

### 3.2 退出时清理（`main.py:246-249`）

```python
try:
    await tui.start_repl(agent)
finally:
    await mcp_bridge.disconnect_all()
```

**`disconnect_all()` 的作用**：遍历 `_servers` 字典，`kill()` 每个 MCP 子进程，然后清空字典。使用 `try/finally` 确保即使 REPL 因异常退出，子进程也会被清理，防止僵尸进程残留。

### 3.3 配置方式（`config.py:54`、`nexus.toml:27-29`）

```python
# config.py
mcp: dict[str, str] = Field(default_factory=dict)
```

```toml
# nexus.toml
[mcp]
# MCP servers: name = "command to launch"
# web_search = "npx -y @anthropic/mcp-server-web-search"
```

配置格式为简单的键值对：`服务器名 = "启动命令"`。MCPBridge 遍历此字典，用 `asyncio.create_subprocess_shell` 启动每个命令。

### 3.4 完整调用链

```
Agent 主循环: llm.stream(messages, tools, system_prompt)
    │
    │ tools = registry.get_tool_definitions()
    │ → 包含内置工具 + MCP 工具的统一 Schema 列表
    │
    ▼
LLM 选择调用 MCP 工具: ToolCall("mcp__web_search__search", {"query": "..."})
    │
    ▼
MasterAgent._execute_tool(tc)
    → tool = registry.get("mcp__web_search__search")
    → tool.execute(query="...")
    → MCPWrappedTool.execute()
       │
       ▼
    构造 JSON-RPC: {
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": "..."}}
    }
       │
       ▼
    写入 proc.stdin → 等待 proc.stdout.readline() → 解析响应
       │
       ▼
    返回 ToolResult(content="搜索结果...")
       │
       ▼
    MasterAgent 将结果加入消息历史 → 继续循环
```

---

## 四、关键设计决策

### 4.1 为什么用 stdio 传输而不是 HTTP/SSE

当前实现仅支持 **stdio（标准输入输出）** 传输方式：

| 维度 | stdio | HTTP/SSE |
|------|-------|----------|
| **实现复杂度** | 低（子进程 + 管道） | 高（HTTP 客户端 + 事件流解析） |
| **服务器类型** | 本地进程（`npx`、`python`） | 远程 HTTP 服务 |
| **认证** | 不需要（本地进程） | 需要（API Key、OAuth） |
| **延迟** | 极低（进程间通信） | 较高（网络往返） |
| **安全性** | 进程隔离，无网络暴露 | 需要 TLS、认证等 |

选择 stdio 的原因：
- **开发阶段够用**：大部分 MCP 服务器都可以作为本地进程启动（`npx`、`uvx`、`python -m`）
- **简单可靠**：不需要处理 HTTP 连接池、重试、超时等网络问题
- **与 Claude Code 一致**：Claude Code 的 MCP 配置也是 stdio 模式

**限制**：无法连接远程 MCP 服务器（如部署在云端的 API）。未来如果需要，可以添加 `MCPSSETransport` 传输层抽象。

### 4.2 为什么 MCP 工具完全透明化

MCPWrappedTool 继承 `Tool` 基类，实现了与内置工具相同的接口（`name`、`description`、`parameters`、`execute()`）。这意味着：

- **LLM 无需区分**：工具定义中看不出哪些是内置、哪些是 MCP
- **Agent 循环无需修改**：`_execute_tool()` 对两者一视同仁
- **权限系统统一**：MCP 工具走同样的 `PermissionGate`（虽然目前没有为 MCP 工具配置单独的权限策略）

**代价**：MCP 工具的调用延迟远高于内置工具（网络/进程间通信 vs 本地调用），但 Agent 循环对此无感知。

### 4.3 `tools/list` 响应格式的兼容性

MCP 规范中 `tools/list` 的响应格式是 `{"result": {"tools": [...]}}`，但某些服务器实现可能直接返回列表或嵌套层级不同。当前代码做了兼容：

```python
tools_resp = await self._jsonrpc_request(proc, "tools/list", {})
tools = tools_resp if isinstance(tools_resp, list) else tools_resp.get("tools", [])
```

`_jsonrpc_request` 返回 `response.get("result", {})`，所以 `tools_resp` 可能是：
- `{"tools": [...]}`（标准格式，再取 `.get("tools")`）
- `[...]`（某些服务器直接返回列表）

### 4.4 已知问题

#### 4.4.1 无认证支持

当前 `_jsonrpc_request` 在初始化握手中只传递了 `clientInfo`，没有认证头或 token。如果 MCP 服务器需要认证（如 Bearer Token），连接会失败。Claude Code 支持通过环境变量或配置传递认证信息。

#### 4.4.2 进程崩溃无自动重连

如果 MCP 子进程因异常退出（崩溃、OOM），`_drain_stderr` 会读到空行退出循环，但 `MCPWrappedTool.execute()` 下次调用时会发现 `proc.stdin is None` 并返回错误。**不会自动重连**，需要重启 NexusAgent。

#### 4.4.3 MCP 工具无独立权限策略

MCP 工具注册到 `ToolRegistry` 后，名称格式为 `mcp__server__tool`。`PermissionGate` 的权限策略（`config.py` 的 `[permissions]` 段）是按工具名精确匹配的，但当前配置中只有内置工具的权限。MCP 工具的权限取决于 `TrustPolicy` 的默认策略（如果默认是 "ask"，所有 MCP 工具都需要用户确认；如果是 "approve"，则自动执行）。

#### 4.4.4 MCP 工具挤占 token 预算

与 Claude Code 一样，每个 MCP 服务器连接后，其所有工具的定义都会注入到每次 LLM 调用的 `tools` 参数中。如果服务器暴露了数十个工具，可能增加上千 token 的开销。当前没有按需加载或工具分组机制。

---

## 五、涉及文件

| 文件 | 职责 |
|------|------|
| `tools/mcp/bridge.py` | MCPBridge：连接、握手、工具发现、JSON-RPC 通信、生命周期清理 |
| `tools/mcp/wrapper.py` | MCPWrappedTool：远程工具适配、Schema 转换、执行与结果解析 |
| `tools/registry.py` | ToolRegistry：统一注册内置工具和 MCP 工具 |
| `tools/base.py` | Tool 基类：`to_llm_schema()` 和 `parameters` 定义 |
| `config.py:54` | NexusConfig.mcp 字段定义 |
| `main.py:59-62` | 启动时创建 MCPBridge 并连接服务器 |
| `main.py:246-249` | REPL 退出时 `disconnect_all()` 清理 |
| `nexus.toml:27-29` | `[mcp]` 配置段 |
