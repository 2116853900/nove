# Nove Web

Nove AI 小说创作平台的前端工程，实现了 `docs/04-UI-DESIGN.md` 定义的 17 个桌面界面。

## 技术栈

- React 18 + TypeScript + Vite
- Tailwind CSS（设计 token 见 `tailwind.config.ts` 与 `src/styles/index.css`）
- react-router-dom 路由
- lucide-react 图标
- Inter（UI）/ Noto Serif SC（正文）字体

## 运行

```bash
cd apps/web
npm install
npm run dev      # 开发服务器 http://localhost:5173
npm run build    # 类型检查 + 生产构建
npm test         # Vitest 冒烟
```

## 界面与路由

| 路由 | 界面 |
|---|---|
| `/` | 项目列表 |
| `/new/1` `/new/2` `/new/3` | 新建小说三步向导 |
| `/novel/:id/write` | 写作工作台（`?generating=1` 进入 AI 生成态） |
| `/novel/:id/outline` | 大纲 |
| `/novel/:id/bible/{characters,locations,factions,items,world-rules}` | 故事圣经 |
| `/novel/:id/plot` | 剧情（时间线 / 伏笔） |
| `/novel/:id/highlights` | 亮点与转折 |
| `/novel/:id/audit` | 审计中心 |
| `/novel/:id/versions` | 版本历史 |
| `/novel/:id/settings` | 项目设置（模型 / 角色 / 审计规则） |

## 后端连接

开发服务器把 `/api` 代理到 `http://127.0.0.1:8000`。也可以通过
`VITE_API_URL` 指向其他 API 地址。项目、章节、故事圣经、大纲、剧情、
  审计、模型配置与版本数据均来自 FastAPI；界面类型定义在 `src/lib/types.ts`。

写作工作台支持正文自动保存、版本冲突保护、SSE 生成阶段、独立审计、
章节确认和候选版本恢复。设计 token 已同时写入浅色与深色 CSS 变量，
当前界面启用浅色主题。
