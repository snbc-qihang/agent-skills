---
name: code-review
description: 针对固定 diff、阶段状态或自动门禁，分别依据仓库规范和原始需求进行评审，并交付正式走查报告。适用于分支、Pull Request、阶段审计、blocker 判断或开发中的变更；仅在明确请求设计评审或设计到实现追踪时启用设计源与评审包门禁。
---

# 代码评审

先冻结比较点，再沿仓库规范和预期行为两个独立轴进行评审。

## 操作流程

1. 确认 base、head、merge-base、diff 范围、需求说明、测试证据和用户明确给出的范围限制；插件采集参考值不限制评审继续进行。普通代码走查不得把 `requirement_id`、设计源或设计评审包当作前置条件。
2. 使用一次最聚焦的索引或 diff 查询定位风险面，再检查规范和确定性工具失败；不要用全仓库扫描重复同一发现，也不要重复抄写工具输出。
3. 根据需求说明检查行为、边界情况、数据和失败路径。
4. 独立执行代码异味走查，至少覆盖职责与复杂度、隐藏状态、异常和空值语义、重复事实源、死代码、魔法值和隐式状态机、命名与注释噪声、跨层或跨服务契约复制、无界读取或重试。优先使用仓库规范；规范缺失或未覆盖某类异味时读取 [references/smell-baseline.md](references/smell-baseline.md) 并把补充判断标为启发式。没有发现时也要在报告中记录已检查范围和证据，不得只写 `pass`。
5. 对正确性、复杂度、冗余、性能、架构和测试质量逐项形成证据判断，特别检查无调用方层级、复制逻辑、过度读取和重复计算。
6. 只报告可执行的问题，并包含证据、影响、级别和位置。
7. 仅在用户明确请求设计评审或设计到实现追踪、当前 persisted node 明确需要设计评审包/设计源快照，或任务已提供任一设计追踪输入时，激活设计追踪。激活后读取 [references/design-review-package.md](references/design-review-package.md)，校验需求条目到设计章节、代码目标和测试用例的追踪闭环，并按目标 `base_digest` 重查外部源；输入不全时把设计追踪标为 `waiting_for_input`，仍完成代码走查报告。未激活时标为 `not_applicable`，不得追问或阻断普通代码走查。
8. 把两个评审轴合并为六维质量门禁；告警、失败、未评估或未关闭修复项不得通过。只有当前存在可执行的 active persisted quality node 时才提交 Runtime `QualitySnapshot`，否则只在报告中合并六维判断，不构造或反复校验形式化 flow 产物。
9. 每次走查都读取 [references/code-review-report.md](references/code-review-report.md)，把正式 Markdown 报告写入目标项目 `.run-artifacts/engineering-assistant/code-reviews/<REVIEW-ID>/code-review-report.md`，并在最终答复中链接该文件。除该报告和 Runtime 明确要求的结构化证据外，不得修改被评审源码。报告无法写入时必须标记 `waiting_for_input` 并内联同等内容，不得宣称走查已完整交付。

默认只打开能支持或推翻一个具体结论的最小证据集。索引已经返回的源码不得重复读取；除非被评审对象就是插件，否则不得扫描插件实现、validator、memory 或历史 rollout。用户明确限制导致证据不足时标记未评估；仅超过插件采集参考值时继续补齐关键证据并记录原因。

进入本 skill 表示平台已完成当前原语的能力选择，内联评审不得为了确认 skill 再次调用 `engineering_assistant_route`；这不等同于已启动 Runtime flow 或持久化状态，只有评审确实需要 Runtime 门禁或超出本原语范围时才进入 Runtime 路由。目标仓库说明引用当前发布包不存在的旧插件路径时，把它记录为旧插件路径说明并使用已选 skill、已有路由结果和当前公开 Runtime；不得扫描插件目录猜测替代路径，也不得读取 catalog 重建路由。

索引不可用或返回未初始化时只记录一次能力边界，然后用已知路径或平台文件索引定向定位。先按符号、命中行或用户点名资产定位，再读取能证明结论的精确区间；不得输出大目录清单、整个插件树、整份大文件或宽泛历史记录来寻找线索。必要证据尚缺时继续定向补齐，证据充分后立即停止，不得为复述结论重复读取。

索引或其他评审工具不可用只表示覆盖不足或 `not_evaluated`，不是产品 blocker。没有读取到 Controller、DTO、持久化或下游校验时，只能报告相应证据链未闭合；除非当前已读调用链证明该能力确实不存在，不得把“未见”升级为实现缺陷。detached HEAD 和未跟踪的 `.run-artifacts/` 是审计事实，只有发布契约明确要求分支形态或洁净范围时才能定级为发布 blocker。

Blocker 必须由当前已读证据闭合触发条件、确定失败行为和阶段影响。决定性证据仍包含“可能”“未评估”“未读取”或依赖尚未检查的下游保护时，不得定级为已证实 blocker；先标为 major 或 `not_evaluated`，再给出能证实或推翻它的最小读取、复现或测试。风险很高不等于证据已经闭合，自动评审不得用高影响替代高置信度。

索引失败后不得用跨模块 `rg -n -C`、宽泛 `git ls-files`、全目录 `find`、完整 `git show` 或一次拼接多份整文件输出作为补偿。先从用户点名资产、固定 diff 的 `--name-only/--stat`、已知符号或 `rg -l` 获得精确路径，再在单个相关文件上用带行号命中和窄行区间读取；一个区间不足就继续读取下一个相关区间，不得为了减少调用次数扩大单次输出。平台已经注入本 skill 时，不得再用 shell 读取自己的 `SKILL.md`、插件目录或 catalog。

当前源码、配置和运行结果与历史报告冲突时，以当前事实为准并把报告标为陈旧。安全评审必须追踪秘密或授权数据的全部扇出路径，包括主表、outbox、通知 payload、URL、日志、审计和错误信息；“主表只存摘要”不能证明其他旁路没有持久化原文。最终答复只能声明实际执行过的文件数、工具和验证，不得把计划或采集参考值写成已完成事实。

安全评审先闭合 `产生 -> URL/消息 -> payload -> outbox/持久化 -> dispatcher/provider/log` 链路，再检查 UI 或一般配置。索引只返回符号但未返回关键持久化、dispatcher 或测试源码时，必须按精确符号或路径读取该文件；不得把可由当前源码确认的事实降级成“可能”，也不得在秘密链尚未闭合时优先调查非关键界面。

需要校验 Runtime 结构化产物时，当前运行时暴露 `engineering_assistant_artifact_validate` 就把已读取的 JSON 对象作为 `artifact` 参数直接调用该只读工具；MCP 工具不得接受或读取模型指定的本地路径。只有开发者 CLI 环境没有 MCP 工具时才使用 `<plugin-root>/engineering-assistant/bin/ea artifact-validate --kind <kind> --input <path>`。若历史 StageRunResult 不属于当前支持的 `step-result` 等 kind，记录校验失败、明确标记版本不兼容并停止，不得扫描插件目录寻找 validator。

历史阶段产物与当前 Runtime schema 不兼容默认属于证据兼容性缺口，不是产品实现 blocker；只有仓库合同明确要求该产物必须符合当前 schema 时才可作为门禁失败。自动技术评审可以替代“工具不可用所以等待人工”的陈旧理由，但不能自行删除产物或合同明确要求的最终人工批准。状态必须使用仓库或 schema 已注册 enum；需要表达安全和证据阻断时使用已有 `blocked` 及结构化 reason/blocker，不得创造 `blocked_by_*` 等状态。

阶段审计同时存在技术问题和人工批准时，分别输出 `technical_status` 与 `human_review_status`，不得用技术 `blocked` 覆盖待人工批准，也不得把人工门禁伪装成技术缺陷。技术问题关闭后仍恢复到原人工门禁，直到仓库要求的批准被明确记录；若当前状态模型只有一个主状态，把另一维放入结构化 blocker、required approval 或 next state，不得丢失。

阶段审计未给出限制时，一次索引查询、八个证据文件和六个 shell 命令只是采集参考值。先读取用户明确点名的阶段结果、自测、代码评审和运行证据，再核对当前源码；用户要求“综合”多个点名证据时，每一类都必须独立读取，不能只读取 StageRunResult 后转述其中的摘要或链接。索引查询必须包含 diff 中的秘密、鉴权、持久化和外部动作高风险符号。一个命令批量输出多个文件仍按实际文件数计数；超过参考值不会阻断任务，应继续补齐关键证据并记录超出原因。

行为触及身份或授权状态、认证或秘密解析、编码归一化、审计或持久化 adapter 合同时，才读取 [references/security-seams.md](references/security-seams.md)。只有仓库规范缺失或不完整时才读取 [references/smell-baseline.md](references/smell-baseline.md)。

未检查固定 diff 前，不得仅凭摘要批准。
