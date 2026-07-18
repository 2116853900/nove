# Nove 全面检查报告：功能缺失、优化与性能建议

> 文档状态：Review 1.0
> 更新日期：2026-07-16
> 依据：代码实态检查（apps/api ~6960 行 Python，apps/web ~3000 行 TS）对照 [PRD](./03-PRD.md) · [技术栈](./01-TECH-STACK.md) · [实施计划](./05-IMPLEMENTATION-PLAN.md)

## 0. 结论速览

项目主路径已跑通，工程完成度高于多数 MVP：大纲、章节生成、审计重写循环、记忆检索、影响分析、版本 diff 都有真实实现且有 pytest 覆盖（约 52 个测试）。前端技术栈已按 01-TECH-STACK 落地——Tiptap、TanStack Query、Zustand、Radix、RHF、Zod 全部安装且实际使用，路由做了 `lazy` 代码分割。

真正的短板集中在三处：**安全（认证授权完全缺失）**、**部分 P1 功能只有骨架**、**性能未做规模化处理**。下面按严重度展开。

---

## 1. 严重问题（P0，建议优先修复）

### 1.1 认证与授权完全缺失 🔴
`routes.py` 所有端点只依赖 `Depends(get_session)`，没有任何 auth 依赖。`get_session` 内部通过 `_seed_default_workspace` 落到单一默认 workspace，`novel_id` / `chapter_id` 直接从路径参数取，不校验归属。

后果：
- 任何请求可读写任意小说，跨 workspace 隔离形同虚设（PRD FR-001「项目之间数据完全隔离」未真正满足）。
- 一旦部署到公网即为开放数据库。

建议：
- 引入最小可用鉴权（API Key / Session Token / JWT 三选一），加 `get_current_workspace` 依赖。
- 所有按 id 查询强制带 `workspace_id` 过滤，收敛到仓储层统一实现，避免逐处遗漏。

### 1.2 加密密钥使用硬编码默认值 🔴
`config.py:24` — `encryption_key` 默认值为 `"nove-local-development-key"`。`security.py` 用它派生 Fernet 密钥加密 API Key。若生产环境未显式设置 `ENCRYPTION_KEY`，所有密钥等同明文（密钥可从源码推出）。

建议：
- 生产环境 `ENCRYPTION_KEY` 缺失时**拒绝启动**，而非回退默认值。
- 同理检查 `SECRET_KEY`（技术栈 §10 列出但当前 Settings 未见）。

### 1.3 生成流程缺少事务边界与并发控制 🔴
章节生成是「生成 → 审计 → 写版本 → 写记忆」多步链路，跑在 FastAPI `BackgroundTasks` 里。当前未见：
- 统一事务或失败补偿——中途失败可能留下半确认状态。
- 任务并发上限 / 队列——SSE 生成可被并发请求打爆进程（技术栈 §8 提到 Redis 队列，MVP 尚未接）。
- 幂等键——重复提交同一生成请求可能产生重复版本。

建议：MVP 内可先加进程内信号量限流 + 生成任务幂等键；多用户阶段再迁 Redis 队列。

### 1.4 数据库文件被提交进仓库
`apps/api/data/nove.db` 在版本库内。应加入 `.gitignore` 并从历史移除，避免演示数据/潜在密钥泄漏。

---

## 2. 功能缺失与薄弱项（对照 PRD）

| FR | 功能 | 现状 | 缺口 |
|---|---|---|---|
| FR-003 | 人物状态 | 有 character_states 快照 | 「按章节查看历史状态」UI、同名/别名冲突合并逻辑薄弱 |
| FR-004 | 地点世界状态 | 有 location_states | 销毁/封锁状态未被连续性检查充分消费 |
| FR-008 | 连续性检查 | 并入 auditor 维度 | 缺**独立的结构化逐项检查**（位置/生死/知识边界/物品归属）；正文行内定位为 best-effort（`EditorPane` 的 `jumpToOffset` 仅 focus，未做真实位置映射） |
| FR-011 | 伏笔/转折 | 有模型与 CRUD | 「长期未回收高重要度伏笔」提醒、审计判断本章亮点是否完成——弱耦合 |
| FR-012 | Skill 管理 | runtime 有 schema 校验+权限+超时 | 调用日志（输入/输出摘要/耗时）持久化不完整；**前端无 Skill 管理页** |
| FR-013 | 模型配置 | 有 CRUD + `/models/{id}/test` 端点 | Token/费用/延迟/错误率统计缺失；前端设置页只做基础绑定 |
| FR-015 | 导入导出 | TXT/MD 导入导出 ✅ | **DOCX 未实现**；导出故事圣经/审计报告未见 |
| FR-016 | 时间线/关系图 | 有事件与关系数据 | **无聚合端点、无可视化页面** |
| FR-017 | 全书审计 | `/novels/{id}/audit-scan` ✅ | 重复情节/节奏/人物消失的规则深度待验证 |

前端页面层面缺失：**导入审阅页**（实体合并、章节切分纠正，PRD §7.2）、**记忆来源查看**（本次生成引用了哪些记忆，FR-007）、**时间线/关系图**、**Skill 管理页**。

---

## 3. 性能优化建议

| 项 | 现状/风险 | 建议 |
|---|---|---|
| 向量检索 | 内存 fallback 为线性扫描；pgvector 索引未确认 | 确认建 ivfflat/hnsw 索引；内存路径加维度校验与上限 |
| 大纲树 | PRD 要求 1000 节点流畅；未见虚拟滚动 | 后端支持懒加载子树；前端上 `@tanstack/react-virtual` |
| 生成上下文 | 每次生成重新检索+拼装 | 缓存故事圣经快照；技术栈 §15 提到的「相同版本审计缓存」尚未实现 |
| Embedding | 章节确认后切分向量化 | 确认为批量而非逐段调用 |
| 数据库索引 | 大量按 (workspace_id, novel_id, chapter_id) 查询 | 确认复合索引齐全，避免全表扫描 |
| 仓储层 | `repositories.py` 仅 35 行，services 直接遍历 ORM | 审查大纲树/版本列表是否 N+1，必要处用 `selectinload` |
| 自动保存 | textarea→Tiptap 已改善光标问题 | 补 localStorage 本地草稿兜底 + saving/saved/error/offline 状态机（FR-005 验收项） |

---

## 4. 工程与可观测性

- **Alembic**：有 baseline，但增量 revision 链未建，生产仍靠 `ensure_schema`（create_all）。建议补正式迁移链。
- **日志正文**：确认结构化日志默认不落完整正文/密钥/系统提示词（PRD §12、技术栈 §6）。
- **错误降级**：agent 调 LLM 失败的重试/降级策略需明确并测试。
- **测试盲区**：现有测试偏 happy path，缺并发、权限、大数据量、Agent 输出降级用例。
- **E2E**：Playwright 仍为「后置」，MVP 验收 §14 的端到端流程无自动化守护。

---

## 5. 建议执行顺序

**第一批（安全底线，做完才敢联网）**
1. ~~认证授权 + 仓储层强制 workspace 过滤（1.1）~~ ✅ 2026-07-16  
   - `X-API-Key` / Bearer；生产强制 `API_KEY`+`ENCRYPTION_KEY`+`SECRET_KEY`  
   - `SqlAlchemyRepository` 按 `workspace_id` 过滤  
2. ~~加密密钥/SECRET 生产强校验（1.2）~~ ✅  
3. ~~`nove.db` 出库 + `.gitignore`~~ ✅（`apps/api/data/` + `*.db` 已 ignore）  
4. ~~生成任务限流 + 幂等键（1.3 的 MVP 版）~~ ✅  
   - 进程内 `MAX_CONCURRENT_JOBS` 信号量；`create_job` 幂等键已存在  

**第一批补充（同日）**
- 审计硬规则并入结构化状态检查（死亡/毁坏地点）  
- 编辑器 `jumpToOffset` 映射到 ProseMirror selection + scroll  

**第二批（补齐 FR 验收）**
5. ~~正文行内审计装饰~~ ✅ Tiptap Highlight 按 severity 着色；jump 定位已增强。Continuity LLM 深化仍可选  
6. ~~模型用量统计（Token/费用/延迟）（FR-013）~~ ✅  
7. ~~导入审阅页 + 记忆来源查看~~ ✅  
8. ~~TXT 导出~~ ✅（DOCX 明确不做）

**第三批（体验与规模化）**
9. 大纲树虚拟滚动 + 懒加载子树
10. 审计缓存 + 故事圣经上下文缓存
11. 时间线/关系图可视化（FR-016）
12. Skill 管理页 + 调用日志持久化（FR-012）
13. Playwright E2E 覆盖 MVP §14 验收流程

---

## 附：本次检查的确认边界

已直接读代码确认：认证缺失、加密密钥默认值、前端依赖与实际使用、路由懒加载、`/models/test` 存在、audit-scan 存在、EditorPane 的 jumpToOffset 为 best-effort。

未逐行验证、建议二次核对：pgvector 索引 DDL、Embedding 是否批处理、N+1 的具体发生点、DOCX 是否真的完全没有、日志脱敏的实际覆盖面。这些在第 3/4 节标注为「需确认」。
