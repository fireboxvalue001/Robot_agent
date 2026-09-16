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

## 可视化界面

“生成实验流程”按钮现已接入智能规划接口。本地文字输入可以选择：

- `原规则编排`：保留原有完整演示能力，适用于分装、预处理、运输等复合任务。
- `DeepSeek 智能规划`：调用 DeepSeek，当前只覆盖已交接的单样品VD10检测场景。
- `离线受限规划`：不联网，用于验证同一知识包和界面链路。

使用智能模式时，展开“智能规划参数”，填写样品编号，并明确勾选“样品交接已由人员或上游系统确认”。该确认不会由自然语言或模型自动推断。

MQTT 返回的实时语义结果仍等待外部同事B的规划结果，本地智能规划不会抢占或替换团队通信链路。

## 当前边界

- 当前知识场景只覆盖单样品、单次VD10检测和可选结果读取。
- 知识状态为 `draft`，因此必须显式使用 `knowledge_mode=demo`；`approved_only` 会拒绝草稿知识。
- 分装、预处理、空间转运和重复检测仍由原规则编排入口覆盖，尚未并入智能规划知识包。
- 成功结果固定包含 `execution_allowed=false` 和 `physical_status=not_evaluated`。
