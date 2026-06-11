# 概要设计 sequenceDiagram participant 证据映射

适用场景：`high-level-design.md` 包含 Mermaid `sequenceDiagram`，并运行 `skills/high-level-design/scripts/validate_output.py`。

## 必须生成的文件

在 high-level-design 阶段 artifact 中登记：

`participant-evidence-map.json`

## 推荐结构

```json
{
  "participants": [
    {
      "participant": "FranchiseeService",
      "display_name": "萤启服务商系统",
      "status": "confirmed",
      "repo_context": "operation/si-rrq-franchisemanagement-service 服务存在 FranchiseeListener 统一MQ监听器",
      "code_path": "operation/si-rrq-franchisemanagement-service/src/main/java/.../FranchiseeListener.java",
      "pom": "operation/si-rrq-franchisemanagement-service/pom.xml"
    }
  ]
}
```

## validator 识别规则

validator 会用以下字段匹配 participant：
- `participant`
- `alias`
- `service`
- `service_name`
- `name`
- `label`
- `display_name`
- `service_label`

validator 会用以下字段判断证据存在：
- `repo_context`
- `repo_context_ref`
- `code_path`
- `source_path`
- `module_path`
- `service_registry_ref`
- `evidence`
- `evidence_refs`
- `source_artifacts`
- `owner_module`
- `pom`
- `build_file`

validator 会拒绝以下状态：
- `unknown`
- `proposed`
- `assumed`
- `todo`
- `pending`
- `pending_confirmation`
- `unconfirmed`
- `missing`

安全状态：`confirmed`、`matched`、`verified`、`existing`。

## Pitfall

只写 `confirmation_status: confirmed` 不够；validator 不读取这个字段。要写 `status: confirmed` 或 `evidence_status: confirmed`，并提供 `repo_context/code_path/source_path` 等证据字段。

如果服务来自用户明确补充但没有代码证据，可用 `repo_context` 写明用户确认事实，并用 `source_path` 指向 PRD 或用户补充来源；不要把无证据 participant 直接写入正式图。