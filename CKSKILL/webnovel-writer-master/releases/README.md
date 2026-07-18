# 发布说明维护规则

每次正式发版都必须在这里新增一份 `vX.Y.Z.md`，作为 GitHub Release 正文的唯一来源。

发布说明不是最后一次提交的摘要，而是从上一个正式 tag 到本次发布提交之间的完整用户可感知变化。写之前先运行：

```bash
git tag --list "v*" --sort=-v:refname
git log --oneline v上一版本..HEAD
git diff --stat v上一版本..HEAD
```

## 写作顺序

1. 先确定发版范围，例如 `v6.1.0..v6.2.0`。
2. 先写“给作者看的变化”，使用中文网文作者能理解的场景语言。
3. 再写“是否需要改旧项目”和“已知影响”。
4. 最后写“给维护者”，记录 CLI、schema、测试、CI、内部结构变化。
5. 运行 `validate_release_notes.py` 检查格式和范围。
6. 推送到 `master` 后由 `Plugin Release` 工作流自动创建 tag 和 GitHub Release；已存在的 tag 或 Release 不会重复创建。

## 固定模板

```md
# vX.Y.Z - 一句中文用户收益

## 发版范围

本次发布覆盖从 `vA.B.C` 到本发布提交的全部变化。

## 给作者看的变化

- ...

## 是否需要改旧项目

- ...

## 适合谁升级

- ...

## 已知影响

- ...

## 给维护者

- ...

## 验证

- ...
```

README 只保留一句短摘要；完整变化写在 `CHANGELOG.md` 和本目录的版本文件里。
