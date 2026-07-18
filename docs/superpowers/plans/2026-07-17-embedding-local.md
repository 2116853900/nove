# Embedding 本地下载与云端简易添加 — 实现计划

> **面向 AI 代理的工作者：** 逐任务实现；步骤使用复选框跟踪。

**目标：** 在模型分配中支持内嵌本地下载（fastembed）三档 + 云端 Embedding 简易添加。

**架构：** 后端新增 catalog/runtime 与 `LocalNeuralEmbedding`；路由暴露下载/状态/云端 API；前端 RolesTab 专用 Embedding 卡片。

**技术栈：** FastAPI、fastembed/ONNX、React、现有 ModelConfig 与 EmbeddingProvider 协议。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `apps/api/app/memory/local_catalog.py` | 三档元数据 |
| `apps/api/app/memory/local_runtime.py` | 下载任务、进度、磁盘检测、模型单例 |
| `apps/api/app/memory/embeddings.py` | `LocalNeuralEmbedding` + resolve 分支 |
| `apps/api/app/schemas.py` | 请求体 schema |
| `apps/api/app/routes.py` | 新 API + probe 支持内嵌 |
| `apps/api/requirements.txt` | 增加 fastembed |
| `apps/api/tests/test_embedding_local.py` | 后端测试 |
| `apps/web/src/pages/ProjectSettingsPage.tsx` | RolesTab Embedding UI |

### 任务 1：Catalog + Runtime + LocalNeuralEmbedding

- [x] 实现 catalog / runtime / embeddings 扩展
- [x] 单测（mock 下载与 embed）
- [x] 依赖写入 requirements

### 任务 2：API 路由

- [x] catalog / download / status / cloud / clear assignment
- [x] 契约测试

### 任务 3：前端 RolesTab

- [x] Embedding 专用卡片：本地下载三档 + 云端简易表单

### 任务 4：验证

- [x] pytest 相关用例通过（`test_embedding_local` + `test_memory_retrieval`）
- [x] 前端类型检查无新增错误（`tsc --noEmit`）
