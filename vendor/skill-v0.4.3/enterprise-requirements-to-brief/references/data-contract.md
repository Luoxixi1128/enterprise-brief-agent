# brief.json 数据约定

`brief.json` 是 Word、Excel、局部黄色确认表及第08汇总的唯一内容源。内部 `kr2_2` 与 `kr2_3` 键为兼容保留；生成文档分别显示 KR2 与 KR3，不显示旧的 KR2 子编号。

## 任务与来源

- `title` 为任务名；`taxonomy` 含 `industry_l1`、`industry_l2`、`role_l1`、`role_l2`。
- `scenario`、`purpose`、`objective` 各简短清楚。`sources` 为来源编号到文件和位置的映射。
- `task_fit` 含 `skill_task`、`autonomous_run`、`ai_trivial` 布尔值（如实记录，不为通过检查而改造原需求）、`private_data_required` 布尔值、`nontrivial_reason`、`data_strategy`、`conversion_note`。如实记录私有数据依赖，不强制写 false；`conversion_note` 默认空，只记录已获授权且实际发生的任务调整，不能填入尚未采用的建议。新增 `scope_change_authorized` 布尔值默认 false，`scope_change_applied` 布尔值默认 false；后者为 true 时，前者必须为 true，同时须有非空 `conversion_note` 和有效来源编号 `scope_change_source`（须在 `sources` 中可追溯到明确授权）。非空 conversion_note 表示已发生任务调整，生成第02任务调整确认并同步第08；其中范围收敛还必须满足上述授权字段。
- `runtime` 保留 `minimum_input`、`ambiguity_policy`、`human_role_after_run` 和 `interactive_required` 布尔值（按原需求如实填写），用于内部运行判断，不在第02输出运行方式。
- `scope_assessment` 含 `complex`、`long_chain`、`long_cycle`、`agent_like`、`enterprise_dependency` 五个布尔值，以及 `note`、`student_slice` 字符串。任一标记为真，必须写明判断原因和建议可收敛的一环，场景以括号红字呈现，并明确当前文档仍按原需求完整范围编写，待人判断是否收敛。`student_slice` 只保存建议，不代表已经采用，不自动触发任务调整确认。

## 输入与输出

- `inputs` 每项含 `id`、`owner`、`required`、`name`、`requirement`、`example`、`source`。`module` 不展示且非必填。
- `owner` 使用 `customer` 或 `customer_optional`；旧 `skill_research` 仅作兼容，可替代样例迁移成选填输入，纯处理步骤从输入中移出。不要为了通过校验添加无意义的自行准备项。
- `required` 为布尔值；`customer_optional` 必须为 false。至少有一个真实企业必填输入，无需选填项。
- `student_fallback` 为可选字符串，仅用于选填项，写明企业不提供时学生如何准备替代样例。
- `dependency_note` 为可选字符串，用于企业环境、账号、测试环境、材料数据依赖的括号红字。存在此字段时该行须是 `customer` 且必填，并将 `scope_assessment.enterprise_dependency` 标为 true。该标记为 true 时至少有一个相应依赖输入。
- `outputs` 每项含 `id`、`name`、`detail`、`example`、`source`，名称不重复。此数组是 KR1 检查项唯一来源，KR1 分数个数等于输出数乘3。
- `output_options` 为1—3个可行选项，每项至少含 `id`、`label`、`recommended`，恰好一个建议项；旧 `format`、`package`、`structure`、`why` 可保留内部参考，不展开到 Word 确认表。生成器另加“其他”。
- `selected_output` 可填已有选项ID；有值显示已勾选，无值保留空框，不能将推荐视为已选。

## 评分与样例

- `kr2_2` 每项含 `id`、`name`、`basis`、`basis_type`、`company_check`、`anchor_1`、`anchor_3`、`anchor_5`、`refs`。依据类型为 `enterprise_rule`、`role_common_practice`、`verified_standard`、`proposal`。依据保留内部，文档表格仅展示评价维度、评分、评分时看什么、1分、3分、5分。引用必须能追溯到输入或输出。
- `kr2_3` 固定四个键 `稳定性`、`可迁移性`、`安全性`、`效率`；每个值为包含 `check`、`anchor_1`、`anchor_3`、`anchor_5` 的对象。旧字符串必须先迁移，不自动编造评分标准。
- `sample` 含 `real` 布尔、`note` 字符串及 `count`（1—3，默认3）。真实样例必须记来源或位置；第03输入样例确认始终保留，已有样例时确认覆盖、不足则补充。
- `reviewer` 保存评分人信息；`rubric_approved` 为布尔值。未明确确认时不填成已批准。

## 黄色确认项同源

`validate_brief.confirmations(d)` 自动导出标准确认项：第02任务调整（已授权且实际调整时，无交付物确认）；第03输入样例；第04输出格式；第06评分人；第07评分规则、当前问题。第07两项在局部合为评分细则框，在第08分别列行。

`confirmations` 数组只用于附加事项，每项含唯一 `id`、`section`（01—07）、`topic`、`question`，可含 `answer` 和有效 `refs`。不得通过附加项恢复交付物确认（`C-DELIVERY` 不再展示）。不得覆盖保留ID `C-ADJUST`、`C-SAMPLE`、`C-FORMAT`、`C-REVIEWER`、`C-RUBRIC`、`C-ISSUE`。局部展示与第08汇总同时读取导出的 question、answer，避免遗漏和改写冲突。

所有输入、输出、格式和评分维度ID须唯一，来源须存在或明确标为 `proposal`／`public-practice`。不允许重复输出、缺失1／3／5分说明、KR3固定维度变化、用选填掩盖企业依赖、索取凭证。KR2与KR1的业务边界还需要人工语义检查，不能仅靠关键词判断。

`scope_assessment.enterprise_dependency` 判断当前文档实际范围是否依赖企业环境或材料。默认按原任务完整范围判断，不能因为建议学生环节不需要账号就省略原任务所需账号和环境。明确获准收敛并实际改写后，才按获准范围重算依赖。

可选 `scope_assessment.original_enterprise_dependency`（默认 false）记录原任务的企业账号或环境依赖；它触发场景红字和建议说明，不自动触发第02任务调整确认。第03依赖输入始终按当前文档实际范围列出。
