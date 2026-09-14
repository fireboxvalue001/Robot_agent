# MQTT 模块接口接入说明

## 接入范围

本项目保持上游提供的 MQTT Topic 和基础消息字段兼容。目前接入：

- 发布：`autolab/ui/input`
- 订阅：`autolab/semantic/params`
- 订阅：`autolab/planner/result`
- 订阅：`autolab/physical/validation`

上游基础规范仍以 `robot_agent/mqtt通信说明以及例程/docs/topic-schema.md` 为依据。`planner/result` 在原字段上使用可选的 `operationChain` 承载可机器校验的元操作ID链。`physical/validation` 是物理确认模块的独立结果Topic。详细契约见 `MODULE_INTERFACE_HANDOFF.md`。

## 数据流

```text
语音或文字输入
  -> 用户确认文字
  -> 语音输入保留录音开始、结束和识别完成时间
  -> FastAPI 发布 autolab/ui/input
  -> 对方语义模块处理
  -> 对方发布 autolab/semantic/params
  -> FastAPI 按 workflowId 关联
  -> 界面显示原始语义结果 JSON 和预处理字段
  -> 同事B读取能力接口并生成有序元操作链
  -> FastAPI接收 autolab/planner/result
  -> 界面按元操作ID渲染任务链
  -> 物理校验模块返回 autolab/physical/validation
  -> 界面显示逐步检查和阻断原因
```

收到语义、编排或物理校验结果都不会自动执行仪器或机械臂。`parameters` 由上游动态返回，界面不会修改 MQTT 消息；已知字段使用中文名称显示，新增字段保留原键和值显示。

## ASR时间字段

语音转写生成的 `ui_input` 消息包含：

```json
{
  "text": "将样品送到VD10进行检测",
  "timestamp": 1789092005000,
  "asrTiming": {
    "utteranceStartedAt": 1789091998000,
    "utteranceEndedAt": 1789092001000,
    "recognitionCompletedAt": 1789092004800,
    "audioDurationMs": 3000,
    "timeUnit": "unix_ms"
  }
}
```

- `utteranceStartedAt`：浏览器开始采集本次录音的Unix毫秒时间。
- `utteranceEndedAt`：用户停止录音或达到最长录音时长的Unix毫秒时间。
- `recognitionCompletedAt`：浏览器收到腾讯云识别结果的Unix毫秒时间。
- `audioDurationMs`：`utteranceEndedAt - utteranceStartedAt`。
- 原有 `timestamp`：MQTT消息生成和发送时间，语义不变。

如果用户修改转写文字，前端会清除该次ASR时间信息，按手动文字发送，避免时间与文本错配。两台联调设备必须使用同一NTP时间源；Unix时间戳本身不会自动校准设备时钟。

## 历史记录

发送、接收、校验拒绝、重复消息和发布失败都会旁路追加到：

```text
data/mqtt_history/YYYY-MM-DD.jsonl
```

每行是一个独立 JSON 对象。`payload` 保持上游消息原样，外层仅记录方向、Topic、事件、接收时间和错误信息，不会改变实际 MQTT 消息。

历史文件在服务重启后仍然存在。界面“查看通信历史”默认读取最近 100 条，也可以调用：

```text
GET /api/mqtt/history?limit=100
GET /api/mqtt/history?workflowId=wf_xxx&limit=100
```

界面只为 `type=semantic_params` 且 `status=success`、包含有效 `originalText` 和 `parameters` 的记录开放载入按钮。载入时保存原 `workflowId`、`msgId` 和记录时间作为本地审计信息，并使用当前元操作库重新执行完整性与能力覆盖检查，不复用历史任务链和执行状态。

运行记录已加入 `.gitignore`，保存在本地项目中但不会作为代码提交。

## 项目配置

MQTT 配置保存在项目自己的 `backend/.env`。未填写时使用上游示例 Broker 默认值：

```text
MQTT_ENABLED=true
MQTT_HOST=cangqiong.sjtusc.cn
MQTT_PORT=1883
MQTT_KEEPALIVE=60
MQTT_QOS=0
MQTT_UI_AUTHOR=vd10_ui
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TLS=false
MQTT_HISTORY_DIR=
```

`MQTT_HISTORY_DIR` 留空时使用项目内的 `data/mqtt_history`。

如果上游调整连接参数，只更新连接配置，不修改 Topic 和消息字段。

## 界面使用

1. 运行 `start-demo.bat`。
2. 打开 `http://127.0.0.1:8877`。
3. 通过语音转写或手动输入文字；语音转写会保留 `asrTiming`。
4. 确认文字后点击“发送语义处理”。
5. 界面显示发送的 `ui/input` 消息。
6. 对方模块返回后，界面显示完整 `semantic/params` JSON，并在预处理区显示字段、缺失项和澄清问题。
7. 字段完整时点击“生成实验流程”；界面先检查能力覆盖，再按依赖顺序编排元操作。

界面也支持不发送 MQTT，直接从自然语言中提取已知字段并生成流程。若 `clarification.needed` 为 `true`、本地提取缺少必要字段，或能力库缺少任务所需能力，任务编排会被阻止。输入文字在 MQTT 预处理后被修改时不会沿用旧回包，而是基于新文字重新本地提取。元操作链能够生成只代表逻辑覆盖检查通过，真实硬件接口和物理环境仍由第二阶段单独校验。

整条外部处理链等待超过 90 秒会显示超时，但不会自动重发，避免同一任务被重复处理；已经收到的前序结果会继续保留在界面中。

## 对方模块联调要求

对方模块需要订阅 `autolab/ui/input`，兼容可选的 `asrTiming`，原样透传收到的 `workflowId`，将 `index` 加 1，并按上游规范生成新的 `msgId`、`history` 和 `timestamp`，最后发布到 `autolab/semantic/params`。

本端会拒绝缺少必填字段或类型错误的消息，并按 `msgId` 忽略重复回包。

## 当前联调结果

- 上游 Broker TCP 端口可访问，本项目已成功连接。
- `autolab/ui/input` 已成功发布。
- 双方已完成一次联调，本项目可以接收 `autolab/semantic/params` 并正确关联 `workflowId`。
- 实际回包中的 `parameters` 和 `clarification` 已接入预处理展示和流程生成前校验。
