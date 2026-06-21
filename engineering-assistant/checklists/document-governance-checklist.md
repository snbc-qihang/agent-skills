# document-governance-checklist

- [ ] DG1 document_number 符合 <PREFIX>-<DOMAIN>-<YYYYMMDD>-<SEQ>
- [ ] DG2 文档类型与编号前缀匹配
- [ ] DG3 document_status 和 retention_policy 已声明
- [ ] DG4 approved/final + persist 才进入正式文档目录
- [ ] DG5 中间过程文档、任务过程摘要、缺失输入清单、blocked 摘要不作为正式文档沉淀
- [ ] DG6 draft/reviewing/blocked/waiting_for_input 只作为 transient 或 keep_until_run_end
- [ ] DG7 superseded/archived 文档记录替代关系
- [ ] DG8 run artifact 与正式文档目录边界清晰
- [ ] DG9 正式文档包含 owner、来源、门禁、风险、审批和生命周期
- [ ] DG10 章节编号由模板统一生成
- [ ] DG23 document_class 区分 formal_*、run_evidence、agent_workspace、process_trace 和 HTML 类产物
- [ ] DG24 最终项目留存集合只包含 approved/final + persist + final_project_record 的 formal_* 文档
- [ ] DG25 artifacts、artifacts/_control、docs/human-review、docs/human-readable 不进入正式留存源集合
- [ ] DG26 canonical_path 指向 docs/00-index、docs/architecture、docs/design、docs/decisions 或 docs/release
- [ ] DG27 release/交付收尾生成 retained-vs-transient 清单
