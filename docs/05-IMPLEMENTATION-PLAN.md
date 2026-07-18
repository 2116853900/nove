# Nove 实现计划

> 状态：Active  
> 更新日期：2026-07-16  
> 依据：[技术栈](./01-TECH-STACK.md) · [总体设计](./02-SYSTEM-DESIGN.md) · [PRD](./03-PRD.md)

按优先级逐项勾选推进。每完成一项把 `[ ]` 改为 `[x]`，并在「完成说明」补一行。

---

## 总览优先级

| 批次 | 主题 | 状态 |
|---|---|---|
| **A** | 记忆检索 | ✅ 完成 |
| **B** | 影响分析 | ✅ 完成 |
| **C** | 编辑器智能 | ✅ 完成 |
| **D** | 大纲 AI | ✅ 生成完成；拖拽/排序见 G |
| **E** | 状态深度 | ✅ 完成 |
| **F** | 工程化 | ✅ 轻量完成 |
| **G** | P0 收尾 | ✅ 完成 |
| **H** | P1 增强 | ✅ H1–H3 完成 |

---

## 批次 A–F（已完成摘要）

- [x] Embedding + 混合检索 + reindex / memory status  
- [x] 重确认 → impact → OUTDATED  
- [x] 选区改写 API + 前端候选接受/拒绝  
- [x] Outline generate + Style/Writer/Plot/Auditor/Memory Agents  
- [x] character_states / location_states + continuity 结构化检查  
- [x] ensure_schema + agent_call_logs + 圣经状态历史  
- [x] 一键启动 dev.ps1；pytest ~43  

详见历史完成说明（A–F 各节）。

---

## 批次 G — P0 收尾（当前冲刺）

对照文档剩余 P0 缺口，按用户价值排序。

### G1. 大纲排序与章节编号
- [x] `POST /api/outline-nodes/{id}/move`（up/down）
- [x] 同级 position 重排；chapter 同步 `chapter_index` 与「第 N 章」标题
- [x] 前端大纲页上移/下移接线
- [x] 锁定节点允许移动（不改 details）

### G2. 版本真 diff
- [x] `GET /api/chapters/{id}/versions/diff?left=&right=`
- [x] VersionHistoryPage 真实段落 diff
- [x] 章节选择器

### G3. 审计问题动作（最小可用）
- [x] 忽略一次 / 有意设定 → localStorage（按 audit id）
- [x] 定位正文 +「去改写」跳转证据

### G4. 上下文 Token 预算（轻量）
- [x] memory 层字符预算裁剪；规则/实体不裁

**完成说明：** 2026-07-16 — 批次 G 完成；45 tests green。

---

## 批次 H — P1 / 工程纯度

### H1. 导入导出
- [x] 导入 TXT/MD（章节切分）`POST /novels/import`
- [x] 导出 Markdown/TXT `GET /novels/{id}/export`
- [x] 向导「导入已有正文」+ 项目列表导出菜单

### H2. 关系与全书
- [x] 人物关系 JSON（entity.data.relations）+ API
- [x] 全书审计扫描 `POST /novels/{id}/audit-scan` + 审计中心入口

### H3. 技术栈纯度
- [x] Alembic 基线（`alembic/` + baseline revision；开发仍可用 ensure_schema）
- [x] pgvector 可选（Postgres `CREATE EXTENSION`；失败则 JSON 向量）
- [x] JSON 结构化日志 + `X-Trace-Id` 中间件
- [x] Vitest 冒烟（`cn`）；Playwright 后置

**完成说明：** 2026-07-16 — H1–H3 完成；API 52 tests + web vitest 2；build ok。

---

## 当前冲刺

**已完成：A–H + 安全底线（06-REVIEW 第一批）**  

- API Key 鉴权（生产强制）· workspace 仓储过滤 · 密钥启动校验  
- 生成并发信号量 · 幂等键 · 结构化连续性并入审计 · jump 定位增强  

**仍可后续：** Playwright · DOCX · 记忆来源页 · 模型用量 · 真 pgvector 索引  

**2026-07-17：** `outline-generate` Skill 接入 SkillRuntime；`OutlineService` 经 Skill 生成并记 SkillRun；pytest `test_outline_skill` 覆盖白名单/Schema/服务落库。  

**2026-07-17 B：** 大纲主流化 — preview/commit/master-preview API；`outline-coherence` Skill；大纲页「生成本卷细纲」+ 预览确认；总纲向导（`?wizard=1`）；写作页细纲完整提示。  

---

## 验收对照（MVP 文档 §14）

| # | 验收项 | 状态 |
|---|---|---|
| 1 | 创建小说并生成大纲 | ✅ |
| 2 | 人物地点世界规则 | 部分 |
| 3 | 连续 10 章确认 | 可人工 |
| 4 | 第 10 章检索第 1 章事实 | ✅ |
| 5 | 知识泄漏可检出 | ✅ |
| 6 | 低分自动重写 | ✅ |
| 7 | 三轮停止 | ✅ |
| 8 | 旧任务不覆盖新内容 | ✅ |
| 9 | 改旧章标记后续 | ✅ |
| 10 | 恢复任意版本 | ✅ + 真 diff |
| 11 | Skill 权限 Schema | ✅ |
| 12 | 全本地模型核心流程 | ✅ |
