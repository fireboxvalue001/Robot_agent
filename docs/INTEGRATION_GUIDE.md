# VD10 可视化界面对接说明

## 1. 模块位置

本模块位于实验室仪器智能体链路的入口理解与计划表达阶段：

```text
自然语言 / 说明书步骤 / 操作员示范
                ↓
阿淦：操作意图、语义步骤、证据、候选能力、已知规则
                ↓
下游：真实页面识别、最终动作匹配、可达性判断、执行与结果
```

`candidate_capability` 只是对昌东能力树的候选匹配，不代表系统已经定位真实按钮、选择最终物理动作或完成执行。

## 2. 输入对接

界面启动时读取：

```text
data/vd10_agent_only_operation_tree.json
```

能力树由以下内容驱动界面：

- `capability_tree[].capabilities[]`：可加入流程的能力卡片。
- `reserved_interfaces_for_excluded_work[]`：可识别但不允许自动执行的受限能力。
- `entry_page`：步骤所需入口页面。
- `parameters`：可编辑参数及枚举范围。
- `machine_preconditions`：机器状态前置条件。
- `execution_policy`、`risk_level`：策略与风险展示。
- `success_criteria`、`failure_cases`：成功与失败依据。

接入其他仪器时，可以先沿用同一字段结构替换数据文件。若设备 ID 或页面状态集合发生变化，需要同步调整 `app.js` 中的页面名称和页面迁移规则。

## 3. 输出对接

点击“复制 JSON”或“导出交接文件”得到 handoff JSON。机器可读约束见：

```text
schemas/agan_vd10_handoff.schema.json
```

示例见：

```text
examples/agan_vd10_handoff.sample.json
```

关键字段：

| 字段 | 含义 | 下游使用方式 |
|---|---|---|
| `steps[].operation_intent` | 归一化后的操作意图 | 作为服务或动作匹配入口 |
| `steps[].evidence` | 原始表达和命中规则 | 审计、调试和冲突处理 |
| `steps[].candidate_capability` | 候选能力与规则约束 | 继续做真实可达性和执行判断 |
| `steps[].params` | 从表达提取或人工编辑的参数 | 填入后续服务调用或 UI 操作 |
| `steps[].plan_validation` | 页面顺序和已知状态检查 | 阻止明显错误的 plan 进入执行层 |
| `steps[].downstream_handoff` | 未完成的执行责任 | 防止把候选匹配误当成执行结果 |

输出中不包含 `confidence`。昌东原始操作树中 `vd10.state.current_page` 的 `confidence` 属于页面识别接口定义，不会自动进入阿淦的 handoff JSON。

## 4. 三种常见对接方式

### A. 对接昌东的新能力树

1. 保持文件名不变，替换 `data/vd10_agent_only_operation_tree.json`。
2. 检查每项能力是否有唯一 `capability_id`。
3. 检查 `entry_page` 和成功后的页面状态是否能形成连续流程。
4. 重新启动页面，确认左侧能力数量和分类正确。

### B. 对接楚涵或其他下游模块

1. 在界面中生成并校验流程。
2. 导出 handoff JSON。
3. 下游读取 `operation_intent`、`candidate_capability`、`params` 和 `evidence`。
4. 下游自行确认最终物理动作、真实 UI 目标、机器状态可达性和执行结果。

### C. 接入真实意图模型

当前自然语言映射是演示用规则 baseline，入口在 `app.js` 的 `parseIntent()`。后续模型只需要输出与 `createWorkflowStep()` 相同的步骤结构，即可继续使用现有卡片、校验和 JSON 导出界面。

## 5. 验收场景

- 样品登记：四步流程校验通过，最终页面为测试界面。
- 结果查询：三步流程校验通过，最终页面为结果详情。
- 顺序错误：把“填写样品 ID”移动到“进入测试界面”之前，应出现页面顺序错误。
- 测试运行中：需要停机状态的操作应被阻止。
- 开始测试：应返回 `CAPABILITY_NOT_IN_AGENT_ONLY_SCOPE`，且不得进入执行。

## 6. 当前限制

- 自然语言解析是规则 baseline，不是已训练的大模型服务。
- 页面状态由界面控件模拟，没有接入真实 OCR、UI tree 或传感器。
- 导出文件由浏览器在本地生成，没有自动发送给外部服务。
- 卡片编排负责计划表达与规则检查，不负责真实仪器控制。
