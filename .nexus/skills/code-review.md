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
