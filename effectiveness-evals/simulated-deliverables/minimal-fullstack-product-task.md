# Minimal Full-stack Product Task Simulation

## Product Goal
企业管理员可以在管理台维护顶部公告：编辑公告文案、启停公告、保存后看到更新时间和成功反馈。

## Backend Scope
- `GET /api/v1/admin/announcement` 返回 `enabled`、`message`、`updatedAt`。
- `PUT /api/v1/admin/announcement` 接收 `enabled`、`message`，启用时 `message` 必填。
- 极小范围：只允许公告配置读写，不扩展成通用设置平台、权限系统、事件总线或跨模块重构。

## Frontend Scope
- 页面：`AdminAnnouncementSettings`。
- 控件：公告文案 textarea、启停 switch、保存 button。
- 状态：loading、empty、validation_error、saving、saved、save_failed。
- 响应式验收：375px 与 1280px 宽度下表单、按钮、状态反馈不重叠。

## Simulated Integration Evidence
- 前后端字段统一为 `enabled`、`message`、`updatedAt`。
- 启用但文案为空时，前端阻止保存，后端也返回校验错误。
- 保存成功后前端展示后端返回的 `updatedAt`。

## Simulated Quality Evidence
- 后端单测：读取默认公告、保存启用公告、启用空文案失败。
- 前端组件测试：加载态、字段校验、保存中、保存成功、保存失败。
- 构建检查：前端 build 通过，未引入新依赖。

## Evaluation Outcome
三组 baseline 的模拟结果位于 `results/`。当前评测结论：`current_engineering_assistant` 优于自由 Codex，但弱于 curated existing tools，因此推荐后续把插件瘦身为控制面与评审层，并主动委派前端和代码上下文能力给优秀工具。
