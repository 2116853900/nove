# Nove AI 小说创作平台：总体设计

> 文档状态：Draft 1.0  
> 更新日期：2026-07-15  
> 关联文档：[技术栈](./01-TECH-STACK.md) · [产品需求文档](./03-PRD.md) · [UI 设计](./04-UI-DESIGN.md)

## 1. 设计目标

系统要解决的核心问题不是单章生成，而是长篇小说在数十万字后仍能保持：

- 剧情与时间线连续。
- 人物性格、动机、知识边界和状态一致。
- 地点、势力、物品和世界规则可追踪。
- 大纲能够约束章节，但允许作者手动偏离并重新规划。
- 伏笔、亮点和转折点可以种下、跟踪和回收。
- AI 输出经过独立审计，低分自动修改或重写。
- Skill 能被受控调用，而不是获得无限制系统权限。

## 2. 架构原则

1. 结构化事实优先于语义记忆。
2. 用户确认优先于 AI 推断。
3. 写作、审计、记忆提取职责分离。
4. 大纲是约束，不是不可修改的脚本。
5. 每次生成都必须可解释、可恢复、可停止。
6. 每次模型和 Skill 调用都可追踪。
7. 低分重写必须保护大纲必达事件和已确认事实。

## 3. 系统上下文

    ┌──────────────┐
    │ 小说作者     │
    └──────┬───────┘
           │ 浏览器
    ┌──────▼─────────────────────────┐
    │ Nove Web 创作工作台             │
    └──────┬─────────────────────────┘
           │ REST + SSE
    ┌──────▼─────────────────────────┐
    │ FastAPI 应用                    │
    │ 业务服务 / 工作流 / AgentScope  │
    └───┬──────────┬──────────┬──────┘
        │          │          │
    ┌───▼───┐  ┌───▼────┐  ┌──▼───────────┐
    │Postgres│  │pgvector│  │模型与 Skill   │
    └────────┘  └────────┘  └──────────────┘

## 4. 领域模块

### 4.1 Project

管理小说项目、题材、主题、目标字数、叙事视角、时态、文风和禁止规则。

### 4.2 Outline

大纲是树结构：

    Novel
    └─ Volume
       └─ Arc
          └─ Chapter
             └─ Scene

每个章节节点至少包含：

- 章节目标。
- 核心冲突。
- 必须发生的事件。
- 禁止发生的事件。
- 出场人物与地点。
- 亮点。
- 转折。
- 结尾钩子。
- 与前后章节的依赖。

### 4.3 Manuscript

负责章节正文、编辑器内容、自动保存、版本、确认状态、导入导出和字数统计。

章节状态：

    PLANNED
      -> GENERATING
      -> DRAFT
      -> AUDITING
      -> REVISING / REWRITING
      -> REVIEW_REQUIRED
      -> CONFIRMED
      -> OUTDATED

OUTDATED 表示前置章节或设定发生变化，需要重新检查但不会自动覆盖现有正文。

### 4.4 Story Bible

故事圣经包含：

- 人物。
- 地点。
- 势力。
- 物品。
- 世界规则。
- 历史事件。
- 术语表。
- 人物关系。

每个实体都要区分固定画像和章节状态。例如人物的出身是画像，当前位置、伤势和已知信息是状态。

### 4.5 Timeline

时间线保存故事内时间，而非数据库创建时间。事件至少包含：

    story_time
    sequence
    chapter_id
    scene_id
    subjects
    action
    location
    consequences

当故事时间模糊时，可以保存相对顺序和可信度，避免 AI 强行生成不存在的准确日期。

### 4.6 Plot Threads

剧情线索统一建模为 PlotThread：

- foreshadowing：伏笔。
- mystery：谜团。
- promise：对读者的叙事承诺。
- conflict：未解决冲突。
- relationship：人物关系变化线。

状态：

    PLANTED -> DEVELOPING -> READY_FOR_PAYOFF -> PAID_OFF
            -> ABANDONED

### 4.7 Audit

负责审计配置、评分规则、问题证据、章节版本、自动修改和自动重写。

## 5. Agent 设计

| Agent | 输入 | 输出 | 可否写正式数据 |
|---|---|---|---|
| Outline Agent | 小说设定、已有大纲 | 结构化大纲节点 | 否 |
| Plot Agent | 当前大纲、剧情线 | 亮点、转折、伏笔计划 | 否 |
| Writer Agent | 组装上下文、章节任务 | 章节正文 | 否 |
| Continuity Agent | 正文、权威事实 | 连续性问题 | 否 |
| Auditor Agent | 正文、评分表、问题 | 分数、证据、修改要求 | 否 |
| Style Agent | 正文、作者文风 | 润色正文 | 否 |
| Memory Agent | 已确认正文、已有事实 | 事实增量候选 | 否 |

正式数据只能由应用服务在验证后写入。Agent 不能直接持有数据库写权限。

## 6. 上下文组装

### 6.1 六层上下文

生成章节时按优先级组装：

1. 小说永久规则。
2. 当前卷、剧情弧、章节和场景任务。
3. 本章人物画像与进入本章前的状态。
4. 地点、物品、势力和世界规则。
5. 最近章节原文、摘要和未解决剧情线。
6. 向量检索得到的相关历史片段。

### 6.2 Token 预算

建议默认分配：

| 内容 | 比例 |
|---|---:|
| 系统规则和输出约束 | 10% |
| 当前大纲 | 15% |
| 人物、地点和硬事实 | 20% |
| 最近章节 | 25% |
| 向量检索内容 | 15% |
| 模型输出预留 | 15% |

上下文超过预算时，优先裁剪低相似度向量片段，不裁剪禁止规则、人物知识边界和当前章节必达事件。

### 6.3 检索查询

检索查询由以下字段构造：

- 当前章节目标和冲突。
- 出场人物及其别名。
- 当前地点及上级区域。
- 涉及的物品、势力和剧情线。
- 需要回收的伏笔。

查询必须限制 novel_id，并排除当前章节之后的内容，防止未来剧情泄漏。

## 7. 章节生成工作流

    读取章节大纲
          │
          ▼
    组装权威上下文
          │
          ▼
    Plot Agent 生成场景节拍
          │
          ▼
    Writer Agent 生成正文
          │
          ▼
    规则引擎检查硬事实
          │
          ▼
    Continuity Agent 检查连续性
          │
          ▼
    Auditor Agent 评分
       ┌──┴──────────────┐
       │                 │
    分数达标          分数未达标
       │                 │
       │          局部修改或整章重写
       │                 │
       └──────重新审计────┘
          │
          ▼
    用户审阅并确认
          │
          ▼
    Memory Agent 提取事实增量
          │
          ▼
    服务校验并提交事实、状态、向量

## 8. AI 审计与自动重写

### 8.1 默认评分

| 维度 | 分值 |
|---|---:|
| 上下文连续性 | 20 |
| 人物一致性 | 15 |
| 大纲完成度 | 15 |
| 剧情推进 | 10 |
| 冲突和张力 | 10 |
| 亮点与转折 | 10 |
| 文笔质量 | 10 |
| AI 痕迹控制 | 10 |

默认阈值：

- 85 至 100：通过。
- 70 至 84：根据问题局部修改。
- 0 至 69：整章重写。
- 存在致命问题：无论总分多少都重写。
- 最多自动处理 3 轮，仍不通过则进入人工审阅。

### 8.2 致命问题

- 死亡人物无解释出现。
- 人物知道尚未获知的信息。
- 关键物品同时出现在不可能的位置。
- 违反用户锁定的世界规则。
- 缺失章节必须事件。
- 提前揭示明确禁止的秘密。
- 重写删除了锁定段落或用户手写内容。

### 8.3 审计输出

审计输出必须通过结构校验，并包含：

    total_score
    decision
    dimension_scores
    fatal_issues
    issues[].type
    issues[].severity
    issues[].evidence
    issues[].reason
    issues[].revision_instruction
    strengths
    rewrite_requirements

每个扣分项必须引用正文证据。审计 Agent 不直接重写正文，Writer Agent 根据审计要求修改。

### 8.4 重写保护

重写请求分为：

    must_preserve
    must_improve
    must_not_include
    locked_ranges

系统在重写后再次检查 must_preserve 和 locked_ranges。若模型破坏保护项，该版本直接判定失败，不计算普通分数。

## 9. 事实和记忆提交

### 9.1 两阶段提交

第一阶段：Memory Agent 提取候选变化。

    new_entities
    entity_updates
    events
    relationship_changes
    plot_threads
    resolved_threads

第二阶段：应用服务校验。

- 实体是否存在。
- 状态变化是否与上一章冲突。
- 事件是否引用当前小说实体。
- 是否将推测错误标记为事实。
- 是否涉及用户锁定字段。

校验通过后，在同一个数据库事务中写入事实、状态和 outbox 事件。向量索引异步消费 outbox，失败时可以重试。

### 9.2 知识边界

人物状态中分别保存：

- character_known_facts：人物已经知道。
- character_beliefs：人物相信但未必真实。
- reader_known_facts：读者已经知道。
- hidden_truths：作者设定但角色和读者尚不知道。

写作上下文只向模型暴露本章需要的隐藏真相，并明确哪些内容不得在正文中揭示。

## 10. 修改旧章节

用户修改已确认章节后：

1. 创建新章节版本，不覆盖历史版本。
2. 重新提取该章事实增量。
3. 计算与旧增量的差异。
4. 标记受影响的人物状态、事件和剧情线。
5. 将后续相关章节标记为 OUTDATED。
6. 提供影响列表，由用户选择重新审计或重写。

影响分析根据实体引用、剧情线依赖、时间线和向量召回综合计算，不直接批量覆盖后续正文。

## 11. 核心数据模型

主要表：

| 表 | 作用 |
|---|---|
| workspaces | 数据隔离边界 |
| novels | 小说项目 |
| novel_rules | 世界和写作硬规则 |
| outline_nodes | 卷、剧情弧、章节、场景树 |
| chapters | 当前章节状态 |
| chapter_versions | 所有正文版本 |
| characters | 人物固定画像 |
| character_states | 人物章节状态 |
| character_relations | 人物关系及变化 |
| locations | 地点和空间规则 |
| factions | 势力 |
| items | 物品及归属 |
| story_events | 故事事件 |
| plot_threads | 伏笔、谜团和冲突 |
| story_beats | 亮点、转折、揭示和钩子 |
| memory_chunks | 向量内容和元数据 |
| model_configs | 模型供应商配置 |
| audit_configs | 小说级审计配置 |
| chapter_audits | 每次审计结果 |
| skills | Skill 清单 |
| skill_runs | Skill 执行记录 |
| generation_jobs | 长任务状态 |

所有业务表至少包含 workspace_id、created_at、updated_at。需要软删除的实体增加 deleted_at。

## 12. API 边界

### 小说与故事圣经

    POST   /api/novels
    GET    /api/novels/{novel_id}
    PATCH  /api/novels/{novel_id}
    GET    /api/novels/{novel_id}/characters
    GET    /api/novels/{novel_id}/locations
    GET    /api/novels/{novel_id}/timeline
    GET    /api/novels/{novel_id}/plot-threads

### 大纲与章节

    POST   /api/novels/{novel_id}/outline/generate
    PATCH  /api/outline-nodes/{node_id}
    POST   /api/chapters/{chapter_id}/generate
    POST   /api/chapters/{chapter_id}/continue
    POST   /api/chapters/{chapter_id}/rewrite
    POST   /api/chapters/{chapter_id}/confirm
    GET    /api/chapters/{chapter_id}/versions
    POST   /api/chapters/{chapter_id}/versions/{version_id}/restore

### 审计与配置

    POST   /api/chapters/{chapter_id}/audit
    POST   /api/chapters/{chapter_id}/audit-and-rewrite
    GET    /api/chapters/{chapter_id}/audits
    PATCH  /api/novels/{novel_id}/audit-config
    GET    /api/models
    POST   /api/models
    GET    /api/skills

### 任务

    GET    /api/jobs/{job_id}
    POST   /api/jobs/{job_id}/cancel
    GET    /api/jobs/{job_id}/events

## 13. 并发、幂等与错误恢复

- 章节生成以 chapter_id + base_version_id + operation 形成幂等键。
- 用户继续编辑后，旧生成任务不能覆盖新版本。
- 任务完成时比较 base_version_id；不一致则保存为候选版本。
- 审计失败可以重试，但同一正文版本和评分表版本可复用已有结果。
- 模型输出解析失败时最多进行一次结构修复，再失败则标记任务错误。
- 向量索引失败不阻止章节确认，但 UI 显示知识库待同步状态。

## 14. 安全设计

- API Key 使用应用级密钥加密。
- 模型调用日志默认只记录摘要、哈希、Token 和耗时。
- 导出和删除操作要求确认。
- 所有查询强制 workspace_id 过滤。
- Skill 采用白名单、超时和输入输出 Schema。
- 导入文件限制类型、大小并进行内容解析隔离。
- 用户可选择关闭云端模型，使用全本地模型和本地存储。

## 15. 可观测性

每次工作流生成 trace_id，关联：

- API 请求。
- 上下文构建。
- 向量查询。
- 每次模型调用。
- 每次 Skill 调用。
- 审计和重写轮次。
- 数据库提交与索引任务。

核心指标：

- 章节生成成功率。
- 首次审计通过率。
- 平均重写次数。
- 每千字 Token 和费用。
- 各模型平均延迟。
- 连续性致命问题数量。
- 用户接受 AI 版本的比例。

## 16. MVP 部署

    Browser
       │
       ▼
    Web Static Server
       │
       ▼
    FastAPI
       ├─ PostgreSQL + pgvector
       ├─ Redis optional
       ├─ Local storage
       └─ External or local model APIs

第一版保持模块化单体。只有当任务量、团队边界或独立扩缩容成为真实问题时，再拆分生成服务、索引服务和文件服务。

