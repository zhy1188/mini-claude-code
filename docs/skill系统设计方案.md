# NexusAgent Skill 系统设计方案

## 一、设计目标

1. **Skill = Markdown 指令文件**：和 Claude Code 一致，一个 `.md` 文件定义一个 skill
2. **自动发现**：放在 `.nexus/skills/` 目录下的 skill 文件自动加载
3. **显式调用**：通过 `/skill-name` 或 "使用 xxx skill" 触发
4. **两级作用域**：全局 skill（`~/.nexus/skills/`）+ 项目级 skill（`项目/.nexus/skills/`）
5. **与现有系统正交**：Skill 不改变 Agent 循环、Tool 系统、Hooks 的现有架构

---

## 二、Skill 文件格式

每个 skill 是一个 Markdown 文件，遵循固定结构：

```markdown
---
name: deploy
description: "部署应用到服务器，包含构建、测试、推送、重启流程"
version: "1.0"
---

# Deploy Skill

## 触发条件
- 用户输入包含 "部署"、"deploy"、"发布"
- 或用户显式调用 /deploy

## 执行步骤

1. 运行 `git status` 确认没有未提交的修改
2. 运行 `python -m pytest` 确保测试通过
3. 读取 `deploy.toml` 获取部署配置
4. 运行构建命令
5. 将产物推送到服务器
6. 重启服务
7. 运行健康检查确认部署成功

## 验证
- 确认服务返回 200
- 确认版本号和预期一致

## 注意事项
- 部署前必须确认测试全部通过
- 如果测试失败，停止并报告错误，不要强行部署
```

**关键设计**：
- **Frontmatter**（`---` 之间）：结构化元数据，供系统解析
- **正文**：纯指令，Agent 按照步骤执行
- 不包含代码逻辑，只包含"做什么"和"怎么做"

---

## 三、架构设计

```
用户输入 "/deploy" 或 "部署应用"
    │
    ▼
SkillRegistry (发现 + 加载)
    │
    ├── 扫描 .nexus/skills/ (项目级)
    ├── 扫描 ~/.nexus/skills/ (全局级)
    └── 建立 名称→Skill 的索引
    │
    ▼
SkillMatcher (匹配)
    │
    ├── 精确匹配: /deploy → deploy skill
    ├── 关键词匹配: "部署" → deploy skill
    └── LLM 语义匹配: 复杂意图 → 最相关 skill
    │
    ▼
SkillExecutor (执行)
    │
    ├── 将 skill 指令注入到 Agent 的上下文
    ├── 作为系统提示的一部分传给 LLM
    └── LLM 按步骤调用工具执行
```

---

## 四、代码设计

### 4.1 Skill 数据模型

```python
# nexusagent/skills/models.py
class Skill(BaseModel):
    name: str                    # skill 名称（文件名）
    description: str             # 简要描述
    version: str = "1.0"
    content: str                 # Markdown 正文（不含 frontmatter）
    source: Path                 # 文件来源路径
    scope: str = "project"       # "project" 或 "global"

    @classmethod
    def from_file(cls, path: Path) -> "Skill":
        """解析 Markdown 文件，分离 frontmatter 和正文。"""
        content = path.read_text(encoding="utf-8")
        name = path.stem
        description = ""

        if content.startswith("---"):
            parts = content.split("---", 2)
            frontmatter = parts[1].strip()
            body = parts[2].strip() if len(parts) > 2 else ""

            for line in frontmatter.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip().lower()
                    val = val.strip().strip('"')
                    if key == "description":
                        description = val
                    elif key == "version":
                        # ...
            content = body
        else:
            content = content

        return cls(
            name=name,
            description=description,
            content=content,
            source=path,
        )
```

### 4.2 Skill 注册表

```python
# nexusagent/skills/registry.py
class SkillRegistry:
    """
    Skill 发现和管理中心。
    - 启动时扫描所有 skill 目录
    - 维护 name → Skill 的索引
    - 支持热加载（新增/修改 skill 文件后重新扫描）
    """

    def __init__(self):
        self.skills: dict[str, Skill] = {}
        self.directories: list[Path] = []

    def add_directory(self, path: Path) -> None:
        """注册一个 skill 搜索目录。"""
        self.directories.append(path)

    def scan(self) -> None:
        """扫描所有注册的目录，加载 .md 文件为 skill。"""
        self.skills.clear()
        for directory in self.directories:
            if not directory.exists():
                continue
            for md_file in directory.glob("*.md"):
                try:
                    skill = Skill.from_file(md_file)
                    self.skills[skill.name] = skill
                except Exception as e:
                    print(f"Warning: Failed to load skill from {md_file}: {e}")

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def list_skills(self) -> list[Skill]:
        return list(self.skills.values())

    def reload(self) -> None:
        """热加载：重新扫描所有目录。"""
        self.scan()
```

### 4.3 Skill 匹配器

```python
# nexusagent/skills/matcher.py
class SkillMatcher:
    """
    匹配用户输入到最相关的 skill。

    三级匹配：
        1. 精确匹配: /deploy → 查找 "deploy" skill
        2. 关键词匹配: 输入包含 skill name 或 description 中的关键词
        3. 语义匹配（可选）: 用 LLM 判断输入意图
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def match(self, user_input: str) -> Skill | None:
        # 1. Slash command: /deploy
        if user_input.startswith("/"):
            cmd = user_input[1:].split()[0].lower()
            return self.registry.get(cmd)

        # 2. Keyword: "使用 deploy skill" / "deploy the app"
        input_lower = user_input.lower()
        for name, skill in self.registry.skills.items():
            if name.lower() in input_lower:
                return skill

        # 3. Description keyword match
        for skill in self.registry.skills.values():
            if skill.description and any(
                kw in input_lower for kw in skill.description.lower().split()
                if len(kw) > 3
            ):
                return skill

        return None
```

### 4.4 Skill 执行器（接入主循环）

```python
# nexusagent/skills/executor.py
class SkillExecutor:
    """
    将匹配的 skill 指令注入到 Agent 上下文中。

    执行方式：
        1. 将 skill 的 content 作为系统提示的附加部分
        2. Agent 按 skill 中的步骤调用工具执行
    """

    def __init__(self, registry: SkillRegistry, matcher: SkillMatcher):
        self.registry = registry
        self.matcher = matcher
        self.active_skill: Skill | None = None

    def process_input(self, user_input: str) -> tuple[str, Skill | None]:
        """
        处理用户输入，如果匹配到 skill则返回注入后的提示和skill对象。

        返回: (修改后的用户输入, 匹配的skill) 或 (原始输入, None)
        """
        skill = self.matcher.match(user_input)
        if skill:
            self.active_skill = skill
            # 将 skill 指令附加到用户输入前
            enhanced_input = (
                f"Please follow the '{skill.name}' skill instructions:\n\n"
                f"{skill.content}\n\n"
                f"User request: {user_input}"
            )
            return enhanced_input, skill
        return user_input, None
```

---

## 五、接入 MasterAgent

在 `main.py` 中初始化 skill 系统：

```python
# main.py 新增部分
from nexusagent.skills.registry import SkillRegistry
from nexusagent.skills.matcher import SkillMatcher
from nexusagent.skills.executor import SkillExecutor

# 创建 skill 注册表
skill_registry = SkillRegistry()
skill_registry.add_directory(workdir / ".nexus" / "skills")   # 项目级
skill_registry.add_directory(Path.home() / ".nexus" / "skills")  # 全局级
skill_registry.scan()

# 创建 skill 执行器
skill_matcher = SkillMatcher(skill_registry)
skill_executor = SkillExecutor(skill_registry, skill_matcher)

# 在 REPL 中处理输入
async def start_repl_with_skills(agent, skill_executor, tui):
    while True:
        user_input = await get_input()

        # Skill 匹配和注入
        enhanced_input, matched_skill = skill_executor.process_input(user_input)
        if matched_skill:
            tui.console.print(f"[cyan]Activating skill: {matched_skill.name}[/cyan]")

        # 运行 agent（使用增强后的输入）
        await agent.run(enhanced_input)
```

同时把 skill 列表注册为 slash 命令：

```python
# 为每个 skill 注册 slash 命令
for skill in skill_registry.list_skills():
    async def skill_handler(args, agent, _skill=skill):
        enhanced = (
            f"Please follow the '{_skill.name}' skill instructions:\n\n"
            f"{_skill.content}\n\n"
            f"Additional context: {args}"
        )
        await agent.run(enhanced)

    tui.register_command(skill.name, skill_handler, skill.description)
```

---

## 六、项目结构变更

```
src/nexusagent/
├── skills/                      ← 新增
│   ├── __init__.py
│   ├── models.py                # Skill 数据模型 + Markdown 解析
│   ├── registry.py              # 发现 + 加载
│   ├── matcher.py               # 三级匹配
│   └── executor.py              # 指令注入

.nexus/
├── skills/                      ← skill 文件目录
│   ├── deploy.md                # 示例: 部署 skill
│   ├── code-review.md           # 示例: 代码审查 skill
│   └── database-migration.md    # 示例: 数据库迁移 skill
├── memory/
├── sessions/
└── history
```

---

## 七、示例 Skill 文件

### deploy.md
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
8. 确认返回 200

## 回滚
- 如果健康检查失败，立即执行回滚命令
```

### code-review.md
```markdown
---
name: code-review
description: "审查最近的 git 变更，检查代码质量"
version: "1.0"
---

# Code Review

## 步骤

1. 运行 `git diff HEAD~1` 获取最近一次提交的变化
2. 检查:
   - 是否有明显的 bug
   - 命名是否清晰
   - 错误处理是否充分
   - 是否有不必要的复杂度
3. 运行 `git diff --stat` 查看变更范围
4. 如果变更涉及测试文件，检查测试是否充分
5. 输出审查报告
```

---

## 八、与现有系统的关系

| 现有系统 | Skill 的关系 |
|----------|-------------|
| **Tool 系统** | Skill 教 Agent 用什么工具、怎么用。Tool 是"能力"，Skill 是"方法论" |
| **Hooks 系统** | Skill 执行前后可以触发 hook。例如部署 skill 执行后触发 post_deploy hook |
| **Memory 系统** | Skill 的执行结果可以写入 memory。例如 code-review 的结论写入 project memory |
| **Slash Commands** | 2026 年 Anthropic 已合并：每个 skill 自动成为一个 slash command |
| **Sub-Agent** | Skill 可以指定由子 Agent 执行。例如 deploy skill 由专门的 "ops" 子 Agent 处理 |

---

## 九、面试讲述要点

> "我在 NexusAgent 中实现了和 Claude Code 一致的 Skill 系统。一个 Skill 就是一个 Markdown 文件，定义了 Agent 执行某个任务的步骤。放在 `.nexus/skills/` 目录下自动被发现，用户通过 `/skill-name` 调用。

> 技术架构分三层：
> 1. **SkillRegistry**：启动时扫描所有 skill 目录，解析 frontmatter 和正文，建立索引
> 2. **SkillMatcher**：三级匹配——精确 slash 匹配 → 关键词匹配 → 描述关键词匹配
> 3. **SkillExecutor**：将 skill 的指令内容注入到 Agent 的系统提示中，让 LLM 按照 skill 定义的步骤调用工具

> 这个设计的核心思想是 **Context Engineering**：Skill 本质上是一种结构化的上下文注入方式。它不是写死在代码里的逻辑，而是用自然语言教 Agent 如何做一件事。这和 Claude Code 2026 年的设计完全一致——Anthropic 在 2026 年 1 月把 slash commands 合并进了 Skills 系统，因为两者的本质相同：都是通过指令文件扩展 Agent 能力。"

---

## 十、与 Claude Code 的对比

| 特性 | Claude Code | NexusAgent |
|------|-------------|------------|
| Skill 文件格式 | Markdown | Markdown（一致） |
| 存放目录 | `.claude/commands/` | `.nexus/skills/` |
| 发现方式 | 自动扫描 | 自动扫描 |
| 调用方式 | `/skill-name` | `/skill-name` |
| 两级作用域 | 全局 + 项目级 | 全局 + 项目级 |
| Frontmatter 解析 | ✅ | ✅ |
| 三级匹配 | 隐式 | 显式实现 |
| 热加载 | 支持 | 支持 |
| 与 Hooks 联动 | 支持 | 支持 |
| 与 Sub-Agent 联动 | 支持 | 支持 |

Sources:
- [Claude Code Skills explained step by step](https://medium.com/@dan.avila7/claude-code-skills-explained-step-by-step-ee3dbb925b49)
- [Extend Claude with skills - Claude Code Docs](https://code.claude.com/docs/en/skills)
- [Inside Claude Code Skills: Structure, prompts, invocation](https://mikhail.io/2025/10/claude-code-skills/)
- [Why did Anthropic merge slash commands into skills?](https://blog.devgenius.io/why-did-anthropic-merge-slash-commands-into-skills-4bf6464c96ca)
- [Claude Code Skills 2.0: The Workflow Upgrade](https://levelup.gitconnected.com/claude-code-skills-2-0-the-workflow-upgrade-that-made-claude-click-for-me-b41fc9a2b467)
