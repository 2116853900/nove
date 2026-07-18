# Embedding 本地下载与云端简易添加 — 设计规格

> 日期：2026-07-17  
> 状态：已批准  
> 范围：项目设置 → 模型分配 → Embedding 角色

## 1. 目标

在**模型分配**中为 Embedding 提供两条路径：

1. **下载本地模型**（进程内嵌，不依赖 Ollama）：精选三档，标明大小与适用条件，下载后自动分配。
2. **添加云端 Embedding**：简易表单（名称 / Base URL / API Key / 模型 ID），保存并分配。

未分配时继续使用本地哈希兜底（现有行为）。

## 2. 非目标

- 不集成 Ollama / TEI / 独立推理服务
- 不内嵌 Chat 大模型
- 不支持任意 HuggingFace 模型自由搜索（仅精选目录）
- 下载进度不做 SSE（轮询即可）

## 3. 架构

```
RolesTab · Embedding
  ├─ 下载本地 → POST /novels/{id}/embedding/local/download
  │              → data/embeddings/<key>/  (fastembed ONNX 缓存)
  │              → ModelConfig(provider="内嵌", roles=["Embedding"])
  └─ 添加云端 → POST /novels/{id}/embedding/cloud
                 → ModelConfig + OpenAICompatibleEmbedding

resolve_embedding()
  ├─ 内嵌且权重就绪 → LocalNeuralEmbedding
  ├─ 有 base_url     → OpenAICompatibleEmbedding
  └─ 否则            → LocalHashEmbedding
```

## 4. 本地方案：fastembed（ONNX）

- 依赖：`fastembed`（传递 `onnxruntime`），不引入 PyTorch
- 权重目录：`apps/api/data/embeddings/`（已在 `.gitignore` 的 `apps/api/data/` 下）
- 懒加载 + 进程内单例；首次 `embed_*` 时 load
- CPU 默认可跑；核显性价比档用 small

### 4.1 精选目录

| key | 档位 | modelId | 约大小 | 维度 | 适用条件 |
|-----|------|---------|--------|------|----------|
| `bge-small-zh` | 性价比 | `BAAI/bge-small-zh-v1.5` | ~90 MB | 512 | 核显/8GB 内存；推荐默认 |
| `jina-base-zh` | 中等 | `jinaai/jina-embeddings-v2-base-zh` | ~640 MB | 768 | 16GB 更稳；质量更好 |
| `e5-large-multi` | 较好 | `intfloat/multilingual-e5-large` | ~2.2 GB | 1024 | 内存 ≥16–24GB；长文本/多语 |

下载源默认 `https://hf-mirror.com`（`HF_ENDPOINT` / `EMBEDDING_HF_ENDPOINT` 可覆盖）。
档位仅包含当前 fastembed 已支持的 modelId。

## 5. API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/embedding/local-catalog` | 三档元数据 + 是否已下载 |
| POST | `/novels/{id}/embedding/local/download` | `{ catalogKey }` 启动下载并在完成后分配 |
| GET | `/novels/{id}/embedding/local/status` | `{ state, progress, message, catalogKey, modelId }` |
| POST | `/novels/{id}/embedding/cloud` | 简易云端创建并分配 Embedding |
| DELETE | `/novels/{id}/embedding/assignment` | 清除该小说 Embedding 角色分配 |

## 6. ModelConfig（内嵌）

```
provider: "内嵌"
model_id: "BAAI/bge-small-zh-v1.5"
base_url: ""
roles: ["Embedding"]  # 同一小说仅一个模型持有此角色
status: "connected" | "error" | "untested"
extra_body: {
  "runtime": "fastembed",
  "catalogKey": "bge-small-zh",
  "dimensions": 512
}
```

## 7. UI

- 其他角色保持现有下拉
- Embedding 行改为专用卡片：状态 +「下载本地模型」「添加云端模型」「清除分配」
- 本地面板：三张档位卡（大小、条件、下载进度、启用状态）
- 云端表单：名称、Base URL、API Key、模型 ID；预设 DashScope / OpenAI
- 换模型后若已有向量：提示「建议重建索引」（调用现有 reindex，不自动静默）

## 8. 错误与换模型

- 下载失败：`status=error`，可重试
- 推理失败：索引失败可观测；不静默混用错误模型
- 维度/模型变更：UI 提示 reindex；向量记录保留 `embedding_model_id`

## 9. 测试

- catalog 字段完整
- download（mock 权重就绪）创建 config 并独占 Embedding 角色
- `resolve_embedding` 优先内嵌
- 云端简易添加契约
- 前端 RolesTab Embedding 卡片可交互（手工或轻测）
