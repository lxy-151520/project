---
name: commit-helper
description: 生成规范化的 Git commit message,符合 Conventional Commits 格式
---

# Commit Helper Skill

帮用户生成格式规范的 commit message。

## 格式

```
<type>(<scope>): <subject>

<body>
```

## Type 枚举

- `feat`: 新功能
- `fix`: bug 修复
- `docs`: 文档
- `style`: 格式调整(空格、分号等,不影响逻辑)
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试
- `chore`: 构建/工具/依赖变更

## 工作流

1. 用 `runCommand` 执行 `git diff --staged` 查看暂存区变更
2. 总结变更意图,选择合适的 type 和 scope
3. 生成 message,subject 行不超过 72 字符
4. 询问用户确认后建议执行 `git commit -m "<message>"`