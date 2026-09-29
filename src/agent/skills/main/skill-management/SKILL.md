---
name: skill-management
description: 在沙箱创建、下载、测试和分配技能，持久化安装结果，并查询、更新或删除已分配技能。
---

# 技能管理

使用此技能管理沙箱 `/skills/` 下的技能。创建、下载和测试均在沙箱进行；分配工具成功后才会将校验过的文件持久化，供后续会话同步使用。

已安装技能必须包含 `SKILL.md` 和 `metadata.json`，两者的 `name`、`description` 必须一致。
外部技能下载时只要求 `SKILL.md` frontmatter；缺失的 `metadata.json` 由安装器自动生成。其他目录和说明文件只在技能实际需要时添加。

通过已注册的管理工具完成生命周期操作。沙箱运行环境需要 Python 3 和 PyYAML，管理工具负责传入可信运行脚本。

## 目录和隔离

```text
/skills/main/{skill}/
/skills/subagents/{subagent}/{skill}/
```

主 Agent 只发现 `/skills/main/`；子 Agent 只发现自己的 `/skills/subagents/{subagent}/`。安装目标为 `main` 时技能保留在主 Agent 目录；分配给子 Agent 后，技能会从主 Agent 目录移动走，不会互相继承。

## 操作流程

1. 用户直接提供 ZIP 链接或 GitHub `tree` 目录链接时，调用 `download_skill`。GitHub 链接会自动下载仓库 ZIP、定位 URL 指向的子目录、校验 `SKILL.md` 并生成元信息。
2. 用户只描述所需能力而没有链接时，先使用公共 `web_search` 工具搜索候选 Skill 链接，再让用户确认链接或选择明确的候选后调用 `download_skill`。
   用户要求编写技能时，使用 `execute` 在 `/skills/main/{skill}/` 创建 `SKILL.md` 及所需资源，并在沙箱测试。创建的技能与下载的技能使用相同分配流程。
3. 调用 `list_subagent_skills` 时，只根据返回的技能名称、标题和描述判断目标，不要求或读取子 Agent 技能正文。
4. 在沙箱检查并测试技能后调用 `assign_skill`：`subagent_name=main` 安装到主 Agent，填写子 Agent 名称则移动到该子 Agent。工具校验元信息、拒绝符号链接和超限文件树，再持久化完整技能目录。只有工具返回成功才报告安装完成；持久化失败会尝试恢复两端旧版本，回滚未确认时报告事务错误。
5. 用户明确要求移除子 Agent 技能时，调用 `delete_subagent_skill`；提供同名技能的新链接时，调用 `update_subagent_skill` 原子替换，失败保留旧版本。

不要把 `skill-management` 本身分配或删除；不要直接在子 Agent 技能目录创建或复制技能，必须通过分配工具完成转移。
