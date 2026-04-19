# NexusAgent 项目理解

## 项目定位

NexusAgent 是一个**用 Python 编写的类 Claude Code AI 编程助手**，复刻了 Claude Code 的核心工作模式。

## 核心架构

```
TUI (Rich) → Agent (Master Loop) → Tools → LLM
```

主循环模式：**Gather → Act → Verify**（单线程）

## 模块结构

| 模块 | 文件 | 职责 |
|------|------|------|
| **Agent** | `master.py`, `orchestrator.py`, `sub_agent.py`, `state_machine.py`, `checkpoint.py`, `tool_tracker.py` | 主循环、子智能体编排、状态机、断点恢复、工具调用计数 |
| **Tools** | 内置工具 + MCP 桥接 | 通过 JSON Schema 动态定义工具，支持 MCP 协议扩展 |
| **Context** | `builder.py`, `manager.py`, `compaction.py`, `retriever.py`, `tokenizer.py`, `project_context.py` | 上下文组装、Token 预算、LLM 压缩摘要、`.nexus.md` 自动加载 |
| **LLM** | `base.py`, `anthropic.py`, `openai_compat.py` | 抽象 LLM 接口，支持 Anthropic 原生和 OpenAI 兼容 API |
| **Permission** | 声明式信任策略 | 按工具粒度控制：自动批准 / 询问用户 / 拒绝 |
| **Hooks** | `engine.py`, `types.py` | 生命周期钩子，支持工具使用前/后等事件触发 |
| **Memory** | `memory.py`, `session.py`, `index.py`, `frontmatter.py` | 会话持久化 + 跨会话文件记忆系统 |
| **TUI** | 基于 Rich | 终端用户界面 |

## 技术栈

- **语言**: Python 3.12+
- **异步**: asyncio
- **数据校验**: Pydantic v2
- **UI**: Rich
- **LLM SDK**: Anthropic SDK + OpenAI SDK
- **Token 计数**: tiktoken
- **构建**: hatchling

## 当前配置（nexus.toml）

- **LLM 提供商**: OpenAI 兼容模式（阿里云 DashScope）
- **模型**: `qwen3.6-plus`
- **API**: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **上下文窗口**: 200K tokens
- **压缩阈值**: 75%，策略为 LLM 摘要
- **权限**: Read/Glob/Grep 自动批准，Write/Bash/Task 需确认
- **Bash 超时**: 120 秒

## 目录结构

```
nexusagent/
├── src/nexusagent/
│   ├── agent/        # 主循环、子智能体、编排
│   ├── tools/        # 内置工具 + MCP 桥接
│   ├── context/      # 上下文管理、压缩、Token 计数
│   ├── llm/          # Anthropic + OpenAI 兼容客户端
│   ├── permission/   # 信任策略 + 权限门控
│   ├── hooks/        # 生命周期钩子引擎
│   ├── memory/       # 会话持久化 + 跨会话记忆
│   └── tui/          # Rich 终端界面
├── plugins/          # 插件目录（当前为空）
├── tests/            # 测试
├── docs/             # 文档
├── examples/         # 示例
├── nexus.toml        # 配置文件
├── .nexus.md         # 项目上下文（类似 CLAUDE.md）
└── pyproject.toml    # 项目元数据
```

## 关键设计点

1. **单一扁平消息历史** — 不使用嵌套结构，简化上下文管理
2. **工具通过 JSON Schema 定义** — 易于扩展新工具
3. **上下文自动压缩** — 达到 75% 阈值时触发 LLM 生成摘要
4. **子智能体并发** — 支持隔离上下文的并发子任务
5. **`.nexus.md` 自动加载** — 项目根目录放置，自动注入系统提示
