# 元操作能力库交接说明

## 交接目标

本能力库供任务编排模块读取和选择元操作。任务编排由下游模块负责，本项目只提供能力事实、输入输出、内部节点、状态和边界，不在交接文件中预先写死完整操作链。

## 必交文件

1. `data/meta-operations.json`：唯一能力库源文件，当前包含35项元操作。
2. `schemas/meta-operation-library.schema.json`：能力库格式校验规则。
3. `data/spatial-locations.json`：位置、楼层和电梯运输链路。
4. `schemas/spatial-location-library.schema.json`：空间数据格式校验规则。
5. `data/vd10_agent_only_operation_tree.json`：VD10说明书小操作节点和来源证据。
6. `docs/META_OPERATION_SPEC.md`：状态、边界和编排约定。

`docs/META_OPERATION_CATALOG.md` 供人工查阅，不应作为程序数据源。

## 下游读取流程

1. 加载能力库并使用JSON Schema校验。
2. 通过能力库中的当前 `id` 引用元操作，不使用数组位置或显示名称作为主键；不得继续发送旧分类下的历史 ID。
3. 根据任务目标筛选分类和候选能力。
4. 对 `instrument` 类先通过 `instrument_id` 选择具体仪器，再从该仪器的元操作中筛选。
5. 使用 `inputs.required` 检查任务是否提供必要参数。
6. 使用 `outputs` 与后续操作的 `inputs` 检查字段衔接。
7. 使用 `precondition_refs`、空间位置库和 `capability_boundary` 排除不可执行候选。
8. 使用 `status` 与 `execution_policy` 区分模拟、待核验和真实执行。
9. 输出操作链时保留元操作ID、版本、参数、缺失条件和阻断原因。

典型检测链按“机器人预处理 -> 环境空间转运 -> 仪器执行 -> 仪器打开结果页面 -> 机器人读取信息”组织。仪器内部的菜单进入和结果查询归属于对应仪器；屏幕识别、LIMS读取和结构化输出属于机器人替代人工的能力。

`extensions.planner_contract` 中的 `consumes` 和 `produces` 用于语义匹配提示。例如，样品交接确认接口产生 `sample_handoff`，样品接收与信息登记消费该状态并产生 `registered_sample`。最终是否可衔接仍以实际输入输出字段和前置条件为准。

## 执行边界

- `verified`：可以在所有运行条件也满足时进入真实执行候选。
- `draft`：只用于模拟和实机验证准备。
- `pending_verification`：依据说明书构建，等待设备界面验证。
- `interface_only`：表示外部设备、人员或软件接口，不允许Agent直接执行。
- 人员送样、领样和验收不属于Agent能力。`lab.meta.confirm_sample_handoff` 只接收并保存外部确认。
- 未登记检测项目统一通过 `instrument.meta.run_registered_project_test` 阻断，不能猜测设备、方法或结果。

## 版本更新

新增或修改元操作时同步更新元操作自身 `version`、能力库 `updated_at`、能力清单、测试和 `PACKAGE_INFO.json`。下游应记录实际使用的元操作ID与版本，避免能力库升级后无法追溯历史任务。
