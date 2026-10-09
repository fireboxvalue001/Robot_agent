# VD10 智能逻辑规划接口

## 定位

该模块根据受限场景知识和当前元操作能力库生成逻辑计划。它不执行机械臂、AGV或VD10，也不代替物理可执行确认。

原有规则入口 `POST /api/v1/planning/from-text` 保持不变。新增接口统一位于 `/api/planner`：

- `GET /api/planner/status`：查看知识包及模型配置状态。
- `GET /api/planner/knowledge`：查看当前场景、元操作和依赖规则。
- `POST /api/planner/plan`：生成受约束的逻辑计划。

## 项目虚拟环境依赖

在项目目录激活 `.venv` 后执行：

```powershell
python -m pip install -r backend\requirements.txt
```

这只会安装到当前项目的 `.venv`，不要在系统 Python 或 Conda `base` 环境中执行。

## 项目内 DeepSeek 配置

在 `backend/.env` 中增加：

```dotenv
DEEPSEEK_API_KEY=你的项目密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=60
```

`.env` 不应提交到 Git。模型输出只是候选计划，后端仍会检查操作集合、证据、参数合同和依赖顺序。

## 离线安全测试

`deterministic` 是显式测试模式，不会联网，也不会在 DeepSeek 失败时自动冒充模型结果：

```json
{
  "scenario_id": "vd10_single_sample_demo",
  "knowledge_mode": "demo",
  "model_mode": "deterministic",
  "workflow_id": "wf_planner_demo_001",
  "text": "将已交接样品送入VD10检测并读取结果",
  "parameters": {
    "sample_id": "sample-001",
    "handoff_confirmed": true,
    "operator": "tester"
  },
  "read_results": true,
  "measurement_repeats": 1
}
```

PowerShell 调用示例：

```powershell
$body = Get-Content .\examples\planner-request.sample.json -Raw
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8877/api/planner/plan `
  -ContentType 'application/json' `
  -Body $body
```

将 `model_mode` 改为 `deepseek` 后才会调用 DeepSeek API。

### 统一任务输入

本地 AI 智能编排可接收自然语言、ASR、委托单或通信历史来源的内容，并统一提交到同一个规划接口。实时 MQTT 协作链路仍按原协议运行。`text` 保留原始任务描述；可选的 `task_intent` 携带上游已经确认的结构化信息：

```json
"task_intent": {
  "source": "document",
  "requested_tests": ["运动黏度（GB/T 265）", "颗粒计数（GB/T 14095）", "FTIR（GB/T 37280）"],
  "sample_count": 1,
  "sample_volume_ml": 500,
  "target_device": null,
  "missing_fields": ["target_device"]
}
```

`source` 可为 `text`、`asr`、`document`、`history` 或 `semantic`。未提供 `task_intent` 时，后端只从明确写出的检测项目和已登记的名称作保守提取；无法确认目标时返回 `needs_input`，不会猜测为 VD10。结构化字段只用于规划判定，不改变现有 MQTT 消息格式。

## 可视化界面

“生成实验流程”按钮现已接入智能规划接口。本地文字输入可以选择：

- `关键词编排`：保留原有完整演示能力，适用于分装、预处理、运输等复合任务。
- `AI智能编排`：当前由 DeepSeek API 提供模型能力，只覆盖已交接的单样品VD10检测场景。
- `AI智能编排（离线状态）`：不联网，用于验证同一知识包和界面链路。

使用智能模式时，展开“智能规划选项”，明确勾选“样品交接已由人员或上游系统确认”。该确认不会由自然语言或模型自动推断。样品编号和操作员可写在原始任务中、来自上游语义字段，或后续补充；界面不要求预先填写专门的输入框。缺少样品编号时仍可调用模型形成候选操作链，但返回 `needs_input`，保留未绑定的样品参数与映射供核对，不生成可执行流程，也不会用虚构编号代替。

MQTT 返回的实时语义结果仍等待外部同事B的规划结果，本地智能规划不会抢占或替换团队通信链路。

## AI可验证推理链

智能规划响应包含 `reasoning_trace`，格式约束见 `schemas/reasoning-trace.schema.json`。该字段由后端根据请求、C2元操作能力库、参数绑定、依赖规则和模型候选结果生成。

先按委托检测项目建立用户目标，并逐项与当前登记的 VD10 检测能力核对。不支持的项目在模型调用前被拦截，不会因选出了五个固定内部步骤而显示任务已完成。随后独立校验场景操作链的参数、依赖、顺序和证据。

用户目标逐项标记状态：`capability_matched` 表示找到了 C2 候选能力，但整链尚未编排或校验；`covered` 表示目标已由通过校验的元操作组合覆盖；`scenario_blocked` 表示所需工作超出当前单样品智能场景；`needs_input` 表示目标或设备尚待确认；`unsupported` 表示当前 VD10 能力无法覆盖；`uncovered` 表示候选链未覆盖。界面分别展示用户目标、场景候选操作和操作链内部校验；候选操作匹配不等于任务可执行。

C3 首屏以 SVG 流程图呈现“任务输入 → 逐项目标判断 → 已校验的元操作链 → 整体逻辑判定”。每个目标都显示“匹配/不满足”分支；一个目标失败后仍继续检查其他目标。只有真实的映射步骤才会连成操作顺序，未编排时仅显示候选能力。事实来源、输入输出映射及程序校验保留在可展开的明细区。C1 的补充信息会附在当前任务后重新提交；若原要求与补充内容矛盾，应直接修正原文，系统不会静默覆盖已登记的检测项目。

界面按以下顺序显示：

1. 输入事实及其来源；
2. 任务目标以及对应的C2元操作；
3. 元操作输入参数、参数来源、声明输出、依赖和证据；
4. 元操作ID、参数、依赖、目标覆盖、顺序和证据六项程序校验；
5. 逻辑决策和物理执行状态。

只有六项校验全部通过时，`decision.logical_executable` 才为 `true`，状态为 `PHYSICAL_PENDING`。这只表示任务可以由当前C2元操作组合，仍需物理可执行确认后才能控制真实硬件。模型输出不能直接把状态设置为可执行。

主要决策状态：

- `PHYSICAL_PENDING`：C2组合及逻辑校验通过，等待物理确认；
- `EXECUTABLE`：逻辑校验和独立物理可执行确认均已通过；
- `PHYSICAL_BLOCKED`：逻辑校验通过，但物理条件不满足；
- `NEEDS_INPUT`：缺少参数或外部确认；
- `UNSUPPORTED`：目标超出当前C2场景；
- `LOGICAL_BLOCKED`：元操作、证据、依赖或顺序校验失败；
- `MODEL_ERROR`：模型调用或输出格式失败。

## 当前边界

- 当前知识场景只覆盖单样品、单次VD10检测和可选结果读取。
- 知识状态为 `draft`，因此必须显式使用 `knowledge_mode=demo`；`approved_only` 会拒绝草稿知识。
- 分装、预处理、空间转运和重复检测仍由关键词编排入口覆盖，尚未并入智能规划知识包。
- 成功结果固定包含 `execution_allowed=false` 和 `physical_status=not_evaluated`。
