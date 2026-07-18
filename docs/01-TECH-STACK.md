# Nove AI 小说创作平台：技术栈

> 文档状态：Draft 1.0  
> 更新日期：2026-07-15  
> 关联文档：[总体设计](./02-SYSTEM-DESIGN.md) · [产品需求文档](./03-PRD.md) · [UI 设计](./04-UI-DESIGN.md)

## 1. 产品与工程假设

- 第一阶段面向中文长篇小说作者，优先支持桌面浏览器。
- MVP 以单用户工作区为主，但数据库保留 workspace_id，便于后续扩展团队协作。
- 同时支持云端大模型和本地模型，写作模型、审计模型、润色模型可以分别配置。
- 正式记忆只从用户确认的章节中提取，草稿、重写稿和审计稿保留版本但不污染正文事实。
- AgentScope 2.0 负责 Agent、模型、工具和工作流编排，业务事实仍由应用数据库管理。
- MVP 使用 PostgreSQL 与 pgvector，不在早期引入独立向量数据库。

## 2. 技术栈总览

| 层级 | 选型 | 用途 |
|---|---|---|
| 前端 | React、TypeScript、Vite | 桌面 Web 创作工作台 |
| UI | Tailwind CSS、shadcn/ui、Radix UI、Lucide | 主题、无障碍组件、图标系统 |
| 编辑器 | Tiptap / ProseMirror | 章节正文编辑、选区改写、批注、版本标记 |
| 状态管理 | Zustand | 当前小说、编辑器、面板等本地交互状态 |
| 服务端状态 | TanStack Query | API 缓存、重试、失效与后台刷新 |
| 表单与校验 | React Hook Form、Zod | 模型配置、人物卡、审计规则等表单 |
| 后端 | Python 3.11+、FastAPI | REST API、SSE、鉴权和业务服务 |
| Agent 框架 | AgentScope 2.0 | 写作、审计、记忆、连续性检查和 Skill 编排 |
| ORM | SQLAlchemy 2.x、Alembic | 异步数据访问与迁移 |
| 主数据库 | PostgreSQL 16+ | 小说、章节、人物、地点、事件、版本和审计记录 |
| 向量检索 | pgvector | 章节、场景、人物经历、设定和伏笔的语义检索 |
| 缓存与任务 | Redis | 生成任务状态、限流、短期缓存；MVP 可选 |
| 对象存储 | 本地文件系统；生产使用 S3 兼容存储 | 导入文档、导出文件、封面和备份 |
| 可观测性 | structlog、OpenTelemetry | 请求、Agent 调用、Token、延迟和异常追踪 |
| 测试 | pytest、Vitest、Playwright | 单元、集成和端到端测试 |
| 部署 | Docker Compose | 本地与单机生产环境 |

## 3. 前端选型

### 3.1 React + TypeScript + Vite

选择原因：

- 创作工作台存在大量局部状态、可折叠面板、树形大纲和异步生成任务，React 生态成熟。
- Vite 适合早期快速开发，后续如需 SSR 或官网再单独增加 Next.js，不让营销页面影响编辑器架构。
- TypeScript 用于约束 API 返回、审计结果、人物状态和章节版本结构。

### 3.2 Tiptap

编辑器必须支持：

- 长文本编辑和自动保存。
- 选中文字后续写、扩写、缩写、改写和对话优化。
- AI 生成内容以临时 diff 显示，用户接受后才覆盖正文。
- 对连续性问题和审计问题添加行内标记。
- 章节版本恢复时保留纯文本和结构化 JSON 两种表示。

不使用普通 textarea 作为正式编辑器，因为无法可靠实现选区操作、批注、diff 和结构化内容扩展。

### 3.3 UI 与状态

- shadcn/ui 和 Radix UI 提供 Dialog、Popover、Tabs、Tooltip、Dropdown Menu 等无障碍基础组件。
- Lucide 作为唯一的结构性图标来源，不使用 Emoji 充当功能图标。
- Zustand 只管理本地 UI 状态，不复制服务端业务实体。
- TanStack Query 管理小说、章节、审计和任务状态，生成期间通过 SSE 接收进度。

## 4. 后端选型

### 4.1 FastAPI

FastAPI 负责：

- 小说、人物、地点、大纲、章节和配置 CRUD。
- 创建写作、审计、重写、索引等长任务。
- 通过 Server-Sent Events 推送生成阶段和 Token 流。
- 对模型密钥、Skill 权限和工作区数据执行边界校验。

MVP 使用 REST + SSE，不优先引入 WebSocket。当前主要需求是服务端单向推送生成状态，SSE 更简单、可重连且便于调试。

### 4.2 AgentScope 2.0

AgentScope 2.0 用于：

- 统一封装不同模型供应商。
- 定义 Writer、Auditor、Memory、Continuity、Plot 等 Agent。
- 绑定允许调用的工具和 Skill 白名单。
- 执行确定性的章节生成工作流。
- 记录每次 Agent 调用的输入摘要、模型、耗时、Token 和输出。

约束：

- 不让多个 Agent 无限制自由讨论。
- 不把 Agent 内存当作小说正式记忆。
- 所有正式事实通过 Repository 和 Service 写入数据库。
- 具体 AgentScope API 在落地时以项目锁定的 2.x 小版本为准，避免文档绑定未确认的小版本接口名称。

## 5. 数据与检索

### 5.1 PostgreSQL

PostgreSQL 保存权威数据：

- 小说和写作规则。
- 大纲树、章节、场景和版本。
- 人物画像、背景、关系和章节状态。
- 地点、势力、物品、世界规则。
- 事件、时间线、伏笔、亮点和转折点。
- AI 模型配置、审计规则和审计记录。
- Skill 清单、版本、权限和执行记录。

### 5.2 pgvector

向量化对象：

- 已确认章节的场景分块。
- 章节摘要和事件摘要。
- 人物经历与关系变化。
- 地点描述和世界设定。
- 伏笔、线索、未解决冲突。

检索采用混合排序：

    final_score =
        semantic_similarity * 0.45 +
        entity_match * 0.20 +
        plotline_match * 0.15 +
        time_proximity * 0.10 +
        importance * 0.10

硬事实不依赖向量相似度。人物生死、位置、伤势、知识边界、物品归属和时间必须从结构化表读取。

### 5.3 Embedding 接口

定义统一 EmbeddingProvider：

    embed_documents(texts, model_config)
    embed_query(text, model_config)
    dimensions()

每条向量记录保存 embedding_model_id 和 embedding_version。更换向量模型时创建重建任务，不在查询时混用不同维度或版本。

## 6. 模型接入

模型角色独立配置：

| 角色 | 推荐特征 | 默认温度 |
|---|---|---:|
| 大纲模型 | 规划与结构化输出稳定 | 0.4 |
| 写作模型 | 中文文学表达和长上下文较好 | 0.7 |
| 审计模型 | 推理稳定、结构化输出可靠 | 0.1 |
| 连续性模型 | 事实比对能力强 | 0.1 |
| 润色模型 | 文体模仿和局部改写稳定 | 0.5 |
| 记忆提取模型 | JSON 抽取稳定 | 0.0 |

支持的适配目标：

- OpenAI 兼容接口。
- 通义、DeepSeek 等云端服务。
- Ollama、vLLM 等本地服务。
- 后续通过独立 Adapter 增加其他供应商。

API Key 加密保存，接口返回时只显示掩码。日志不得记录完整密钥、完整系统提示词或未脱敏的用户正文。

## 7. Skill 运行时

Skill 采用清单驱动：

    name
    version
    description
    input_schema
    output_schema
    allowed_agents
    timeout_seconds
    enabled

执行要求：

- 只允许 Agent 调用白名单 Skill。
- 输入和输出都进行 JSON Schema 校验。
- 设置超时、最大输出和失败策略。
- Skill 不直接修改正式记忆，返回建议或结构化变更，由业务服务校验后提交。
- 每次调用记录小说、章节、Agent、Skill 版本、耗时和结果摘要。

## 8. 后台任务与流式输出

任务类型：

- GENERATE_CHAPTER
- AUDIT_CHAPTER
- REVISE_CHAPTER
- REWRITE_CHAPTER
- EXTRACT_MEMORY
- REINDEX_NOVEL
- IMPACT_ANALYSIS

MVP 可先在 FastAPI 进程内使用受控异步任务；进入多用户部署后迁移到 Redis 队列。任务必须可取消、可查询、可重试，并通过幂等键避免重复写入。

## 9. 推荐目录

    nove/
    ├─ apps/
    │  ├─ web/
    │  └─ api/
    ├─ packages/
    │  └─ contracts/
    ├─ docs/
    ├─ infra/
    │  ├─ docker/
    │  └─ migrations/
    ├─ tests/
    ├─ docker-compose.yml
    └─ README.md

后端内部：

    apps/api/app/
    ├─ api/
    ├─ agents/
    ├─ workflows/
    ├─ domain/
    ├─ repositories/
    ├─ memory/
    ├─ skills/
    ├─ models/
    ├─ schemas/
    ├─ services/
    └─ main.py

## 10. 环境变量

    APP_ENV
    DATABASE_URL
    REDIS_URL
    SECRET_KEY
    ENCRYPTION_KEY
    STORAGE_PATH
    CORS_ORIGINS
    LOG_LEVEL
    DEFAULT_EMBEDDING_MODEL

供应商 Key 优先保存在加密数据库配置中，也可以通过环境变量提供系统级默认值。

## 11. 测试策略

| 测试层 | 重点 |
|---|---|
| 单元测试 | 评分计算、上下文预算、状态更新、Skill 校验 |
| 数据库测试 | 章节确认、事实增量、回滚、向量隔离 |
| Agent 契约测试 | JSON Schema、错误重试、模型输出降级 |
| 工作流测试 | 低分重写、致命问题拦截、最大重试次数 |
| E2E | 建书、建大纲、生成、审计、确认、恢复版本 |
| 质量基准 | 固定小说样例的连续性和人物一致性回归 |

## 12. 暂不采用

- 不在 MVP 使用 Kubernetes。
- 不在 MVP 拆分微服务。
- 不使用独立图数据库；人物关系先由 PostgreSQL 表表达。
- 不让向量数据库成为唯一记忆来源。
- 不默认自动确认 AI 生成章节。
- 不在第一版实现多人实时协同编辑。

