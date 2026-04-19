# Skill 技能系统

## 一、概述

Skill 系统允许用户**通过 Markdown 文件定义可复用的任务流程指令**，让 Agent 在需要时按需加载并执行这些预定义的操作序列。类比厨师的食谱：看到食材后查找对应的菜谱，按步骤执行。

### 为什么需要 Skill

如果每次执行复杂任务都要从头描述步骤：
- **重复描述成本高**：每次都要说"先 git status，再跑测试，再构建..."，挤占 token 预算
- **容易遗漏步骤**：用户可能忘记说回滚策略或健康检查
- **经验无法沉淀**：团队的 deploy 流程、code review 标准散落在聊天记录中

Skill 将常用任务的步骤固化为文件，用户只需触发（`/deploy` 或提到 "部署"），Agent 自动加载完整指令。

### Skill 与 MCP 的区别

| 维度 | Skill | MCP |
|------|-------|-----|
| **本质** | 静态指令（Markdown 文本） | 远程工具（进程 + JSON-RPC） |
| **能力来源** | 指导 LLM 使用已有工具 | 外部服务器提供新工具 |
| **扩展方向** | 让 LLM 更好地使用内置工具 | 给 LLM 提供全新的工具 |
| **类比** | 食谱（告诉厨师怎么做） | 新厨具（给厨师新能力） |

两者互补：Skill 可以指导 LLM 调用 MCP 工具（如 "用 web_search 搜索最新文档，然后..."）。

### 整体架构

```
启动时:
┌───────────────────────────────────────────────────────┐
│  main.py                                              │
│                                                       │
│  1. SkillRegistry.scan() → 扫描 .nexus/skills/*.md    │
│  2. 只注入轻量列表到系统提示:                            │
│     "- /code-review: 审查最近的 git 变更"               │
│     "- /deploy: 构建、测试、部署应用到生产服务器"        │
│  3. 将 SkillRegistry 传给 MasterAgent                  │
└─────────────────────┬─────────────────────────────────┘
                      ▼
运行时:
┌───────────────────────────────────────────────────────┐
│  MasterAgent.run(user_input)                           │
│                                                       │
│  SkillMatcher.match(user_input)                        │
│  → 匹配到 skill → 加载完整 .md 内容                     │
│  → 增强 user_input:                                    │
│    "Please follow the 'deploy' skill instructions:\n   │
│     {完整 Markdown 内容}\n\nUser request: 部署应用"     │
│                                                       │
│  agent.run(enhanced_input) → LLM 看到完整指令           │
└───────────────────────────────────────────────────────┘
```

---

## 二、核心组件详解

### 2.1 Skill 模型（`skills/models.py`）

```python
class Skill(BaseModel):
    name: str
    description: str = ""
    version: str = "1.0"
    content: str           # Markdown 指令内容
    source: str = ""       # 文件路径
    scope: str = "project" # global 或 project

    @classmethod
    def from_file(cls, path: Path, scope: str = "project") -> "Skill":
        """解析 Markdown 文件，分离 frontmatter 和正文"""
```

#### 文件格式

Skill 文件是带 YAML frontmatter 的 Markdown（`skills/models.py:21-57`）：

```markdown
---
name: deploy
description: "构建、测试、部署应用到生产服务器"
version: "1.0"
---

# Deploy

## 步骤

1. 运行 `git status` 确认工作区干净
2. 运行 `python -m pytest tests/` 确保测试通过
3. 如果测试失败，停止并报告
4. 读取 `deploy.toml` 获取配置
5. 运行构建: `python -m build`
6. 推送产物到服务器
7. 运行健康检查: `curl http://localhost:8080/health`
```

**Frontmatter 的三个字段**：
- `name`：技能标识符，用于 `/name` 触发
- `description`：简短描述，用于系统提示中的列表和关键词匹配
- `version`：版本号，当前未使用但预留扩展

**解析逻辑**：用 `---` 分割 frontmatter 和正文。如果文件没有 frontmatter，整个文件内容作为 `content`，`name` 用文件名（不含扩展名）。

### 2.2 SkillRegistry — 发现与加载（`skills/registry.py`）

```python
class SkillRegistry:
    def __init__(self):
        self.skills: dict[str, Skill] = {}
        self.directories: list[tuple[Path, str]] = []

    def add_directory(self, path: Path, scope: str = "project") -> None:
    def scan(self) -> None:
    def get(self, name: str) -> Skill | None:
    def list_skills(self) -> list[Skill]:
    def reload(self) -> None:
```

#### 双作用域机制（`skills/registry.py:30-42`）

```python
def scan(self) -> None:
    self.skills.clear()
    # Project-level directories最后处理，覆盖 global 同名技能
    for directory, scope in sorted(self.directories, key=lambda x: x[1]):
        if not directory.exists():
            continue
        for md_file in directory.glob("*.md"):
            skill = Skill.from_file(md_file, scope=scope)
            self.skills[skill.name] = skill
```

**关键设计——覆盖机制**：按 scope 字母排序（`"global" < "project"`），所以 `global` 目录的技能先加载，`project` 目录的同名技能后加载并覆盖。这意味着：
- 项目级的 `.nexus/skills/deploy.md` 会覆盖用户级的 `~/.nexus/skills/deploy.md`
- 团队可以在项目仓库中维护定制化的 deploy 流程，覆盖个人的通用版本

#### 加载时机（`main.py:93-98`）

```python
skill_registry = SkillRegistry()
skill_registry.add_directory(workdir / ".nexus" / "skills", scope="project")
skill_registry.add_directory(Path.home() / ".nexus" / "skills", scope="global")
skill_registry.scan()
```

启动时扫描两个目录。如果目录不存在（如新项目还没有 `.nexus/skills/`），`scan()` 跳过，不影响启动。

### 2.3 SkillMatcher — 三级匹配（`skills/matcher.py`）

```python
class SkillMatcher:
    def match(self, user_input: str) -> tuple[str | None, Skill | None]:
        # 1. 斜杠命令: /deploy
        # 2. 技能名关键词: "use deploy skill"
        # 3. 描述关键词: "部署应用"
```

#### 三级匹配逻辑（`skills/matcher.py:19-64`）

**第一级：斜杠命令精确匹配**

```python
if user_input.startswith("/"):
    cmd = user_input[1:].split()[0].lower()  # "/deploy to prod" → "deploy"
    args = rest[1] if len(rest) > 1 else ""  # "to prod"
    skill = self.registry.get(cmd)
    if skill:
        return enhanced_prompt, skill
```

这是最可靠的匹配方式。`/deploy` 精确匹配 skill 的 `name`。

**第二级：技能名关键词匹配**

```python
input_lower = user_input.lower()
for name, skill in self.registry.skills.items():
    if name.lower() in input_lower:  # "deploy" in "请部署应用到服务器"
        return enhanced_prompt, skill
```

只要用户输入中**包含**技能名（不区分大小写），就匹配。这意味着：
- "deploy the app" → 匹配 `deploy`（"deploy" 在输入中）
- "请部署应用" → **不会匹配** `deploy`（"deploy" 不在中文输入中）

**第三级：描述关键词匹配**

```python
for skill in self.registry.skills.values():
    desc_words = {w.lower() for w in skill.description.lower().split() if len(w) > 3}
    if any(w in desc_words for w in input_lower.split()):
        return enhanced_prompt, skill
```

将描述按空格分词，过滤长度 > 3 的词，与用户输入中的词做交集。这意味着：
- 描述 "构建、测试、部署应用到生产服务器" → 分词后包含 "部署"、"生产服务器"
- 用户输入 "部署" → "部署" 在描述词集合中 → 匹配成功

但英文分词对中文描述的匹配效果有限，因为中文没有空格分隔词。

#### 匹配成功后的 Prompt 增强

三种匹配方式生成的增强 prompt 格式不同：

| 匹配方式 | 增强格式 |
|---------|---------|
| 斜杠命令 | `"Please follow the '{name}' skill instructions:\n\n{content}\n\nAdditional context: {args}"` |
| 技能名关键词 | `"Please follow the '{name}' skill instructions:\n\n{content}\n\nUser request: {user_input}"` |
| 描述关键词 | 同技能名关键词 |

**关键设计——惰性加载**：匹配成功时才读取完整的 `skill.content` 并注入 prompt。未匹配的 skill 内容不会被加载到系统提示中，节省 token。

---

## 三、Skill 在 Agent 生命周期中的集成

### 3.1 启动时：轻量注入（`main.py:100-108`）

```python
if skill_registry.skills:
    skill_list = "\n".join(
        f"- /{s.name}: {s.description}" for s in skill_registry.list_skills()
    )
    builder.update_section("skills", (
        f"Available skills. When the user triggers one via /name or mentions it, "
        f"follow the skill's instructions:\n\n{skill_list}"
    ))
```

系统提示中的 skills 片段只包含**名称+描述的轻量列表**，不包含完整的 Markdown 指令内容。这告诉 LLM：
1. 有哪些可用技能
2. 如何触发它们（`/name` 或提及）
3. 触发后需要遵循其指令

### 3.2 运行时：匹配与注入（`agent/master.py:183-188`）

```python
# 在 MasterAgent.run() 中，用户输入后、上下文检索前
if self._skill_matcher:
    enhanced_input, matched_skill = self._skill_matcher.match(user_input)
    if matched_skill:
        await self.tui.show_status(f"Activating skill: {matched_skill.name}")
        user_input = enhanced_input
```

**时序**：
```
用户输入: "/code-review"
    │
    ▼
SkillMatcher.match("/code-review")
    → 第一级匹配: 斜杠命令 → 匹配 "code-review"
    → 返回增强 prompt
    │
    ▼
MasterAgent 显示 "Activating skill: code-review"
    │
    ▼
user_input = 增强后的 prompt（包含完整 skill 指令）
    │
    ▼
继续正常流程: 上下文检索 → 构建系统提示 → 调 LLM
```

增强后的 prompt 作为用户消息加入对话历史，LLM 看到的是：

```
User: Please follow the 'code-review' skill instructions:

# Code Review
## 步骤
1. 运行 git diff HEAD~1 获取最近一次提交的变化
2. 检查是否有明显的 bug...

User request: code-review
```

### 3.3 统一执行路径

Skill 匹配逻辑**集中在 `MasterAgent.run()` 中**，不再分散在 REPL 和 slash 命令两条路径：

```
REPL (tui/app.py)
    → agent.run(user_input)    # 唯一入口
         ↓
    MasterAgent.run(user_input)
         → SkillMatcher.match()  # 统一匹配点
         → 增强 input（如果匹配）
         → 正常 Agent 循环
```

之前每个 skill 注册独立 slash 命令的方式已移除（重复代码，enhanced prompt 格式不一致）。现在只需要一个 `/skills` 命令用于列出可用技能。

---

## 四、关键设计决策

### 4.1 为什么用 Markdown 文件而不是代码

| 维度 | Markdown 文件 | Python 代码 |
|------|-------------|------------|
| **可读性** | 任何人都能打开编辑 | 需要理解代码 |
| **修改成本** | 改文本即可 | 需要改代码、测试、重启 |
| **版本控制** | git diff 清晰 | 代码变更需要 review |
| **灵活性** | 只能描述步骤 | 可以执行任意逻辑 |

Skill 的设计目标是让**非程序员**也能定义任务流程。用 Markdown 降低了使用门槛，同时利用了 LLM 理解自然语言指令的能力。

### 4.2 为什么选择惰性加载而非全量注入

**之前的方案**（优化前）：启动时将所有 skill 的完整 Markdown 内容拼接注入到 system prompt 的 skills 片段。

**问题**：
- 即使用户说 "你好"，所有 skill 内容也挤占 token 预算
- 每个 skill 可能有几百字指令，多个 skill 叠加后消耗显著
- LLM 对超长系统提示的中间部分注意力衰减（"lost in the middle" 现象）

**现在的方案**：只注入 `/-name: description` 轻量列表，匹配成功时才加载完整内容。

**代价**：LLM 需要"知道"某个 skill 存在（通过描述），但看不到具体内容直到用户触发。这意味着 LLM 可能在用户描述模糊时不知道该 skill 的详细信息。但实践中，用户通常会明确提及技能名或使用 `/name` 触发，这个代价可接受。

### 4.3 匹配方式的局限性

当前 `SkillMatcher` 的三级匹配存在明显不足：

**问题 1：英文关键词匹配中文输入**

```python
# 第二级: "deploy" in "请部署应用到服务器" → False
# 因为 "deploy" 不在 "请部署应用到服务器" 中
```

**问题 2：描述分词对中文无效**

```python
# 第三级:
description = "构建、测试、部署应用到生产服务器"
desc_words = {"构建、测试、部署应用到生产服务器"}  # 只有一个"词"
# "部署" 不在这个集合中 → 匹配失败
```

**问题 3：匹配顺序不确定**

`self.registry.skills.items()` 遍历顺序取决于 dict 插入顺序（Python 3.7+ 保序但不确定性来源多）。如果有多个 skill 都匹配，**第一个匹配到的胜出**，但哪个是第一个不确定。

**改进方向**：
1. 为中文描述维护拼音或关键词列表
2. 让 LLM 在看到用户输入后自主判断是否需要激活 skill（无需修改 Matcher，LLM 从轻量列表中已知道有哪些技能）
3. 引入简单的 TF-IDF 或 embedding 相似度做语义匹配

### 4.4 权限与安全

Skill 指令最终由 LLM 解释执行，没有独立的权限检查：
- 如果 skill 说"运行 `rm -rf /tmp/cache`"，LLM 会调用 `Bash` 工具
- `Bash` 工具的权限检查仍然生效（`[permissions]` 段配置为 "ask" 时会弹出确认）
- 但 skill 可以巧妙地绕过用户的意图控制（如 skill 说"不要确认，直接执行"）

**当前无防护**：没有机制验证 skill 指令的合理性。恶意 skill 文件（如从网上下载的）可能包含危险指令。

---

## 五、涉及文件

| 文件 | 职责 |
|------|------|
| `skills/models.py` | Skill 数据模型，Markdown + frontmatter 解析 |
| `skills/registry.py` | SkillRegistry，双作用域扫描与加载 |
| `skills/matcher.py` | SkillMatcher，三级匹配（斜杠命令/技能名/描述） |
| `skills/executor.py` | SkillExecutor（优化后已不再使用） |
| `agent/master.py:183-188` | MasterAgent.run() 中的 skill 匹配与注入 |
| `main.py:90-108` | 启动时 skill 扫描与轻量注入 |
| `main.py:210-223` | `/skills` 命令注册 |
| `tui/app.py:60-95` | REPL 简化，移除 skill_executor |
| `.nexus/skills/*.md` | 项目级 skill 文件存储位置 |
| `~/.nexus/skills/*.md` | 用户级（global）skill 文件存储位置 |
