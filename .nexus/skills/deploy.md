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
