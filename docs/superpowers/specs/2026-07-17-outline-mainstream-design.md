# 大纲主流化（方案 B）— 设计规格

> 日期：2026-07-17  
> 状态：已批准，实现中

## 目标

1. 生成本卷 N 章细纲（主路径）
2. 预览确认再落库
3. Prompt 增强（人物/规则/已有章）
4. 总纲向导（从零规划）
5. 连贯检查 Skill `outline-coherence`
6. 写作页细纲状态轻衔接

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/novels/{id}/outline/preview` | 生成预览，不写库 |
| POST | `/novels/{id}/outline/commit` | 确认写入选中节点 |
| DELETE | `/novels/{id}/outline/preview/{previewId}` | 丢弃预览 |
| POST | `/novels/{id}/outline/master-preview` | 总纲：卷+弧+N 章预览 |

## 预览存储

进程内 dict + TTL 30 分钟；key=`previewId`，含 novel_id、nodes、source、coherence。

## Skills

- `outline-generate`：增强上下文
- `outline-coherence`：批节点连贯问题列表
