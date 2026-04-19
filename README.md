# NexusAgent

NexusAgent 是一个用 Python 编写的类 Claude Code AI 编程助手，复刻了 Claude Code 的核心工作模式与架构设计。

## 核心架构

```
TUI (Rich) → Agent (主循环) → 工具系统 → LLM
```

主循环遵循 **Gather → Act → Verify** 三阶段模式，单线程运行，状态可控。

## 技术特点

- **智能体主循环** — 单线程 Gather-Act-Verify 循环，内置状态机（IDLE / GATHERING / THINKING / ACTING / VERIFYING / COMPACTING），避免多线程竞态，流程可追溯
- **可扩展工具系统** — 通过 JSON Schema 动态定义工具，内置 7 个核心工具（Read / Write / Bash / Glob / Grep / Task / NotebookEdit），支持 MCP 协议扩展
- **上下文工程管理** — 200K token 窗口，75% 阈值触发 LLM 自动压缩摘要，多层 token 计数（API 精确值 → tiktoken → 粗略估算），`.nexus.md` 项目上下文自动加载且不被压缩
- **子智能体并发编排** — 支持隔离上下文的并发子任务，基于 asyncio.gather 并行执行，结果自动聚合回主上下文
- **声明式权限控制** — 按工具粒度配置信任策略（自动批准 / 询问用户 / 拒绝），Bash 工具内置危险命令拦截、超时控制和输出截断
- **生命周期钩子** — 支持工具执行前/后、用户输入前/后等事件触发 shell 命令，阻塞/非阻塞可选
- **多 LLM 后端** — 同时支持 Anthropic Claude 和任意 OpenAI 兼容 API（DashScope、Ollama、vLLM 等），流式输出
- **跨会话记忆** — 会话持久化为 JSON，`.nexus/` 目录管理用户偏好、项目、反馈等多类记忆文件

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| 异步 | asyncio |
| 数据模型 | Pydantic v2 |
| 终端 UI | Rich |
| LLM SDK | Anthropic SDK + OpenAI SDK |
| Token 计数 | tiktoken |
| 构建 | hatchling |

## 快速开始

```bash
# 安装依赖
pip install -e .

# 设置 API 密钥（以 Anthropic 为例）
export ANTHROPIC_API_KEY=your_key_here

# 运行
python -m nexusagent
```

## 配置

编辑 `nexus.toml` 修改模型、API、权限等设置：

```toml
[llm]
provider = "openai"          # 或 "anthropic"
model = "qwen3.6-plus"       # 模型名称
base_url = "https://..."     # OpenAI 兼容 API 地址

[context]
max_tokens = 200000          # 上下文窗口上限
compact_threshold = 0.75     # 75% 时触发压缩

[permissions]
Read = "approve"             # 自动批准
Write = "ask"                # 执行前询问
Bash = "ask"
```

## 项目结构

```
src/nexusagent/
├── agent/          # 主循环、子智能体编排、状态机
├── tools/          # 内置工具 + MCP 桥接
├── context/        # 上下文管理、压缩、Token 计数
├── llm/            # Anthropic + OpenAI 兼容客户端
├── permission/     # 信任策略 + 权限门控
├── hooks/          # 生命周期钩子引擎
├── memory/         # 会话持久化 + 跨会话记忆
└── tui/            # Rich 终端界面
```

## .nexus.md

在项目根目录放置 `.nexus.md` 文件（对标 Claude Code 的 CLAUDE.md），提供项目架构、编码规范等上下文信息，系统会自动加载并注入提示词，且不会被上下文压缩删除。
