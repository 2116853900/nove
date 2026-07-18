# Plugin Best Practices Deep Review

审查对象：`webnovel-writer/` Claude Code 插件源目录  
审查日期：2026-06-03  
回滚校正：2026-06-04

## 当前结论

**最佳实践符合度：中高。**

插件的工程基础、目录结构、版本同步、测试覆盖和 source 包装都比较扎实；但按 Anthropic 官方 `plugin-dev` 的严格 agent/skill 元数据口径，仍保留一些非阻断差距。

本报告已按 2026-06-04 的回滚结果修正：此前 Codex 额外加入的 agent 英文触发描述、`When to invoke` 小节，以及 `deconstruction-agent` 的 `magenta` 颜色改动已经撤回。

## 已完成/已核实

- `.claude-plugin/plugin.json` 存在且 manifest 可读取。
- 版本同步检查通过：`Versions are in sync: 6.0.0`。
- prompt integrity 测试通过。
- 全量 pytest 通过。
- 插件 source 子目录已有 `README.md` 与 `LICENSE`。
- `webnovel-init` 的初始化采集模型已下沉到 `references/init-collection-schema.md`。
- `webnovel-plan` 的结构化节点示例已下沉到 `references/outlining/chapter-planning.md`。
- `webnovel-query/references/system-data-flow.md` 已标注 legacy，并修正旧 `/webnovel-resume` 与“6 个 Agent 并行”漂移描述。
- `docs/superpowers/` 已归档到 `docs/archive/superpowers/`，活跃入口链接已修正。
- `docs/architecture/` 的历史快照已归档到 `docs/archive/architecture/`，活跃入口链接已修正。

## 回滚说明

已撤回以下 Codex 额外改动：

- 4 个 agent 的英文 `Use this agent when...` 触发描述。
- 4 个 agent 正文顶部的 `## When to invoke` 场景小节。
- `deconstruction-agent` 的 `color: magenta`，已恢复为 `color: purple`。

当前 agent frontmatter 状态：

- `context-agent`: 短中文 description，`model: inherit`，`color: blue`
- `data-agent`: 短中文 description，`model: inherit`，`color: green`
- `deconstruction-agent`: 中文 description，`model: inherit`，`color: purple`
- `reviewer`: 中文 description，`model: inherit`，`color: yellow`

## 剩余最佳实践差距

### Agent metadata

官方 `agent-development` 文档建议 agent description 使用更明确的触发句式，并在正文提供触发场景。当前已按要求回滚到 Claude 原对话状态，因此仍存在：

- description 偏短或偏内部术语。
- 没有 `When to invoke` 场景。
- `deconstruction-agent` 的 `purple` 不是官方 `validate-agent.sh` 列出的颜色之一；官方脚本列出的颜色是 `blue`、`cyan`、`green`、`yellow`、`magenta`、`red`。

这不是运行时阻断项，但若以后要按官方 validator 严格过检，需要再单独确认是否接受这类 metadata 改动。

### Cross-platform shell assumptions

多个 SKILL.md 仍包含 Bash 风格片段，例如 `export`、`${VAR}`、`cat`、`for ch in $(seq ...)`。建议在 README 或 operations 文档中说明这些片段假设在 Claude Code Bash tool 或兼容 shell 中执行。

### 真机加载验证

文件级与测试级验证已通过，但尚未在干净目录中执行真实 Claude Code 插件 enable/load 流程。

## 验证记录

```powershell
python -X utf8 webnovel-writer\scripts\sync_plugin_version.py --check --expected-version 6.0.0
$env:PYTHONUTF8='1'; python -m pytest webnovel-writer\scripts\data_modules\tests\test_prompt_integrity.py -q --no-cov
$env:PYTHONUTF8='1'; python -m pytest -q --no-cov
```

结果：

- 版本同步：通过
- prompt integrity：通过
- 全量 pytest：通过

## Final Assessment

当前状态已经完成 Claude 原会话提出的 B/C 收尾主线，并保留了回滚后的 agent 元数据。若下一步目标是“严格官方 validator 过检”，需要用户明确同意再调整 agent description、触发场景和 `deconstruction-agent` 颜色。
