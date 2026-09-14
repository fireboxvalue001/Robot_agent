# 元操作 JSON 规范

## 1. 用途

本规范用于统一描述实验室系统中的元操作。元操作是可被任务编排器独立选择的完整能力，内部由电子说明书、机器人示教或软件接口提供的小操作节点组成。

格式约束位于 `schemas/meta-operation-library.schema.json`，当前能力实例位于 `data/meta-operations.json`。

`data/meta-operations.json` 是唯一能力库源文件。界面、任务编排器和交接程序都应直接读取该文件，不维护内容重复的第二份能力清单。

## 2. 三类元操作

- `instrument`：由具体检测仪器自身执行的测试、控制和安全退出能力，界面使用绿色。
- `robot`：机器人完成的样品预处理、上下料、界面操作和结果信息读取，界面使用蓝色。
- `lab`：样品在工位、区域和楼层之间的空间转运，以及门禁和通道能力，界面使用红色。

仪器元操作必须填写 `instrument_id`，并引用根级 `instruments` 中登记的仪器。界面和下游程序按“仪器类别 -> 具体仪器 -> 元操作”两级关系组织能力。元操作 ID 的命名空间必须与实际 `category` 一致：机器人能力使用 `robot.meta.*`，环境能力使用 `lab.meta.*`，具体仪器能力使用设备命名空间（例如 `vd10.meta.*`）。

语言、肢体和眼神属于总体意图输入，不进入元操作能力库。试管已经贴装二维码属于前置条件，不作为元操作。

## 3. 必填结构

每个元操作必须包含：

- 稳定且唯一的 `id` 和语义化 `version`。
- `category`、`status` 和 `execution_policy`。
- 仪器类元操作必须具有有效的 `instrument_id`。
- 可机器校验的 `inputs` 与 `outputs`。
- 可追溯的 `source`。
- 由小操作节点组成的 `operation_tree`。
- `physical_requirements`、`capability_boundary` 和 `failure_policy`。

小操作节点必须使用 `node_ref` 引用能力节点，并声明来源：

- `electronic_manual`：检测仪器电子说明书节点。
- `robot_teaching`：机械臂或 AGV 示教节点。
- `software_interface`：视觉、数据库或程序接口。
- `reserved_interface`：尚未接入、不可直接执行的保留接口。

## 4. 状态与执行策略

状态：

- `draft`：已定义，尚未验证。
- `pending_verification`：依据说明书建立，等待真实环境验证。
- `verified`：已完成测试和核验。
- `interface_only`：只保留接口，不能直接执行。
- `disabled`：停止使用。

执行策略决定 Agent 是否可以调用。`interface_only` 和包含受限节点的元操作只能进入任务草案，不能进入真实执行。

## 5. 新增流程

1. 确认该能力具有独立输入、输出和业务结果。
2. 选择三类中的一个分类。
3. 建立小操作节点引用及依赖顺序。
4. 写清前置条件、允许范围、禁止范围和失败策略。
5. 使用 JSON Schema 校验文件。
6. 完成模拟测试和真实环境核验后，再将状态改为 `verified`。

## 6. 空间位置引用

涉及机械臂或 AGV 位移的元操作使用稳定的 `location_id`，具体坐标保存在 `data/spatial-locations.json`，格式约束位于 `schemas/spatial-location-library.schema.json`。任务参数只传位置 ID，不把坐标复制到每条任务中。

`placeholder=true` 或 `status` 不是 `verified` 的位置只能参与模拟编排。现场坐标替换、坐标系对齐、接近位姿和容差核验完成前，物理执行必须被阻止。

## 7. 编排器使用约定

编排器先按 `status` 和 `execution_policy` 过滤候选项，再根据 `inputs`、`outputs`、`precondition_refs` 和 `capability_boundary` 判断能否衔接。`extensions.planner_contract.consumes` 与 `produces` 是面向自动编排的语义提示，不能替代字段校验。

- `verified` 才能作为真实执行候选。
- `draft` 和 `pending_verification` 只能进入模拟或待核验流程。
- `interface_only` 可以保留在操作链中表示外部依赖，但必须阻断自动执行。
- 找不到唯一设备、方法、位置或样品身份时，应输出缺失条件，不能根据名称猜测。
- 人员交接由 `external_confirmation` 输入，Agent只能记录，不能生成该确认。

样品检测任务的推荐阶段顺序为：机器人样品预处理 -> 实验室环境空间转运 -> 具体仪器执行 -> 机器人读取并结构化仪器输出。每个阶段仍应根据实际意图和前置条件按需选择，不把整条流程写死为单个元操作。
