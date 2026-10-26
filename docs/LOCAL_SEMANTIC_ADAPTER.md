# 本地解析结果与明确自然语言

当前支持单个 `add_to` 意图：从指定来源容器取出指定体积的液体，加入目标容器。
输入保持同事的 `semantic_params` JSON，适配层输出 `resolved_intent` 和明确自然语言；不读取能力库，不选择操作，也不返回操作链。
浏览器将明确文字填入C1，再通过 `/api/planner/plan` 按当前模式调用本地确定性模板或AI智能编排。能力选择、参数绑定、流程校验和后续物理确认归规划模块处理。
不需要 MQTT 公共字段，也不会发布 MQTT 消息。

## 直接在 Python 模块间调用

从项目根目录运行，传入已经读取的 JSON 对象：

```python
import json
from backend.local_semantic_adapter import resolve_local_semantic

with open("examples/local-semantic-add.sample.json", encoding="utf-8") as file:
    parsed = json.load(file)
result = resolve_local_semantic(parsed)
print(result["resolvedText"])
```

函数只处理 JSON 对象并返回结果，不写文件、不调用模型、不执行设备。

## 本地 HTTP 接口

```text
POST http://127.0.0.1:8877/api/v1/intent/from-semantic
Content-Type: application/json
```

请求体直接是同事的解析结果，无需包裹额外的 `payload` 或 `message`。
完整输入见 `examples/local-semantic-add.sample.json`。
调用示例：

```powershell
$json = Get-Content .\examples\local-semantic-add.sample.json -Raw -Encoding UTF8
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8877/api/v1/intent/from-semantic -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($json))
```

业务字段不足时返回 HTTP 200、`status=failed` 和 `preprocessing.clarification`，不返回操作链。
无效的 `workflowId` 返回 HTTP 422。没有传入 `workflowId` 时自动生成；如传入则必须以 `wf_` 开头。
原函数名 `plan_local_semantic` 和 `/api/v1/planning/from-semantic` 保留为兼容别名，返回内容同样改为 `resolved_intent`，调用方不应再从这一步读取 `operationChain`。

## 界面接入

C1点击“导入解析结果 JSON”，选择同事输出的JSON文件。系统显示明确文字与预处理字段，再按用户当前选择的模式编排：本地规则模式使用确定性移液模板，AI模式调用模型。不会因导入JSON自动切换AI。
在页面中的其他本地 JS 模块也可以调用：

```javascript
const result = await window.autolabLocalSemantic.plan(parsedJson);
```

该方法先调用指代解析接口，更新输入框，再按当前模式调用规划接口。直接从Python调用指代解析接口只返回JSON，不会向已经打开的浏览器推送。
成功解析后，“生成实验流程”直接使用当前明确文字编排，不再重复JSON适配。缺少体积时可在“补充任务信息”中补充，例如“体积为10mL”，确认完整后才提交规划。
成功后可以修改输入框里的明确参数并重新编排；容器编号仍需明确。

## 参数与来源

注册操作：`robot.meta.transfer_liquid`，属于机器人类，名称“容器间定量移液”。

| 本地解析字段 | 操作参数 |
| --- | --- |
| `arguments.sourceObject.objectId` | `source_object_id` |
| `arguments.targetObject.objectId` | `target_object_id` |
| `arguments.sourceObject.objectName` | `source_object_name` |
| `arguments.targetObject.objectName` | `target_object_name` |
| 结构化 `arguments.volume` 或唯一的原文体积 | `volume_ml` |

可选结构化体积：`"volume": {"value": 10, "unit": "mL"}`。原来的 JSON 无此字段时，只有原文包含一个明确、正数的 mL/毫升体积才会补取。
多个体积、非正数、未知单位，或结构化体积与原文不一致时要求确认。`operationDescription` 不用于恢复缺失数量。
`op_001` 保留在 `adapterMetadata.sourceOperationId`，不作为能力库 ID。
`adapterMetadata.parameterSources` 记录字段来源，`sourceSemantic` 保留原始解析结果。置信度保留在原始结果中，不替代参数完整性检查。

成功后 `resolvedText` 为：

```text
从瓶子1（容器编号：bottle_1）中吸取10mL液体，加入瓶子2（容器编号：bottle_2）中。
```

AI 接口独立接受这段文字，不需要原 JSON。当前移液场景输入示例：

```json
{
  "scenario_id": "liquid_transfer_demo",
  "knowledge_mode": "demo",
  "model_mode": "deepseek",
  "text": "从瓶子1（容器编号：bottle_1）中吸取10mL液体，加入瓶子2（容器编号：bottle_2）中。",
  "read_results": false
}
```

## 执行边界

内部步骤为容器确认、工具准备、定量吸取、注入目标容器、完成核验。
容器的实际位置、开盖状态、余量、液体兼容性及工具量程需由物理确认模块检查。
AI 编排仍返回 `execution_allowed=false`、`physical_status=not_evaluated`。模型调用失败时保留明确文字，显示失败结果，不自动切换到离线或原 JSON 编排。
当前能力库为 `1.7.1`，调用方应重新查询能力快照。
