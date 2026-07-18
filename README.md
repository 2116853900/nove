# Nove

Nove 是面向长篇小说作者的 AI 创作工作台。仓库包含 React 前端与
FastAPI 模块化单体后端，核心写作流程使用版本、审计和候选稿保护作者正文。

项目已将 `CKSKILL/` 的初始化、规划、写前合同、章节生成、证据化审计、
Anti-AI 检查、确认后记忆与项目体检流程编译为内置规则集。运行契约、严格/
兼容模式和验收说明见 [docs/CKSKILL_INTEGRATION.md](docs/CKSKILL_INTEGRATION.md)。

## 本地运行

### 一键启动（推荐调试）

在仓库根目录双击 `dev.bat`，或执行：

```powershell
.\dev.ps1
```

会自动检查依赖，并分别打开 API / Web 两个终端窗口：

- Web: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`

常用参数：

```powershell
.\dev.ps1                   # 默认会释放 8000/5173 占用后启动
.\dev.ps1 -NoKill           # 端口占用时直接失败
.\dev.ps1 -SkipInstall      # 跳过依赖检查
.\dev.ps1 -ApiOnly          # 只启后端
.\dev.ps1 -WebOnly          # 只启前端
.\dev.ps1 -ApiPort 8001     # 自定义 API 端口
```

### 手动启动

后端默认使用 SQLite 保存业务数据，并在数据库旁使用持久化 Qdrant Local
Mode 保存 RAG 向量。首次启动自动建库（空工作区，无演示项目）：

```powershell
cd apps/api
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

另一个终端启动前端：

```powershell
cd apps/web
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。API 文档位于
`http://127.0.0.1:8000/docs`。

## 验证

```powershell
cd apps/api
python -m pytest -q

cd ../web
npm test -- --run
npm run build
```

## PostgreSQL 部署

根目录执行 `docker compose up --build`。Web 暴露在 5173，API 暴露在
8000，Qdrant Dashboard 仅绑定本机 6333。PostgreSQL 与 Qdrant 数据分别
保存在命名卷中。应用数据与向量 payload 始终按 `workspace_id` 和
`novel_id` 隔离。
