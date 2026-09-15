# VD10 实验任务编排台

版本：`0.3.0`

这是用于验证 VD10 实验任务规划的本地可视化界面，现已接入腾讯云一句话识别、意图预处理、外部任务编排和物理可执行确认接口。当前不连接真实 VD10 或机械臂。

## 首次配置

项目运行时使用自己的 `.venv`。首次初始化时需要电脑上已有 Python 3.10 或更新版本，Windows 运行：

```powershell
cd D:\ResearchGroupProject\OCR_agent\robot_agent\VD10\vd10_visual_workflow_handoff_v0.3.0
.\setup-asr.bat
```

腾讯云密钥保存在 `backend/.env`，该文件已被 `.gitignore` 排除。新环境可复制 `backend/.env.example` 后填写：

```text
TENCENTCLOUD_SECRET_ID=你的SecretId
TENCENTCLOUD_SECRET_KEY=你的SecretKey
TENCENTCLOUD_APP_ID=你的腾讯云AppId
TENCENT_ASR_ENGINE=16k_zh
TENCENT_ASR_WORD_INFO=1
TENCENT_ASR_VAD_SILENCE_TIME=800
```

MQTT 默认使用上游示例 Broker。需要覆盖连接参数时，在同一个 `backend/.env` 中填写：

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

如果仍在原始项目目录中，也可以迁移已有腾讯云配置：

```powershell
.\migrate-asr-env.ps1
```

该脚本只适用于原始项目目录，只迁移腾讯云 ASR 设置，不复制 DeepSeek 和报告配置，也不会打印密钥。打包给其他人时不要发送该脚本，接收方应手动填写自己的 `backend/.env`。

## 交接打包

发送整个项目目录中的源码和配置模板即可，但不要发送：

- `.venv/`
- `backend/.env`
- `backend/__pycache__/`、`tests/__pycache__/`
- `data/mqtt_history/*.jsonl`

接收方解压后运行 `setup-asr.bat`，再复制 `backend/.env.example` 为 `backend/.env`，填写自己的腾讯云和 MQTT 配置，最后运行 `start-demo.bat`。

## 启动

双击 `start-demo.bat`，或运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.server:app --host 127.0.0.1 --port 8877
```

浏览器打开：<http://127.0.0.1:8877>

不要再使用 `python -m http.server`，静态服务器无法提供 ASR 接口。

## 语音输入

第一部分支持浏览器麦克风录音。配置 AppId 后，前端通过同源的 `/api/asr/realtime` WebSocket 将 16kHz 单声道 PCM 音频流发送给后端，由后端代理到腾讯云。点击开始只启动服务，腾讯 VAD 检测到人声后才记录句子开始时间；每次静音断句都会更新文字，并保留逐句、逐词的起止时间。点击停止后才结束整个会话。

未配置 AppId 时自动回退到 `/api/asr/transcribe` 一句话识别，最长录音30秒。两种模式下密钥都只由 Python 后端读取，不会返回浏览器；需要允许浏览器访问麦克风。

## MQTT语义处理

确认输入框文字后点击“发送语义处理”。后端严格按照上游规范发布 `autolab/ui/input`，并订阅 `autolab/semantic/params`。两条消息通过上游规定的 `workflowId` 关联，收到的语义结果保持原始 JSON；其中 `parameters`、缺失字段和澄清问题会同步显示在“预处理结果”区域。

可以直接输入自然语言并点击“生成实验流程”。界面调用同源的 `POST /api/v1/planning/from-text`，后端提取数量、体积、样品处理、目标设备和楼层等字段，并依据当前元操作能力库生成标准 `planner_result`。接口不可用时，界面才使用原有前端规则降级。已有实时 MQTT 预处理结果时仍等待同事 B 返回操作链，不会用本地编排覆盖外部流程。

自然语言编排接口最小请求：

```json
{
  "text": "将桌上的样品分成4份，每份25ml，送到VD10进行检测"
}
```

可选传入以 `wf_` 开头的 `workflowId`。成功响应直接使用现有 `planner_result` 字段和 `operationChain` 契约，并额外携带 `preprocessing` 供界面展示。缺少分装体积、加热温度或静置时长时返回 `status=failed` 和澄清问题；无法匹配能力时不会强制路由到设备。

时间参数支持中文单位“秒、分钟、小时”和常见缩写 `s`、`sec`、`min`、`h`。编排器会根据文字位置区分检测前处理与“检测完成后”的后处理。

当前已接收 `autolab/planner/result` 和 `autolab/physical/validation`。真实MQTT预处理结果不会再触发本地关键词编排：界面等待同事B返回带元操作ID的 `operationChain`，再等待物理校验模块返回逐步结论。详细契约见 `docs/MODULE_INTERFACE_HANDOFF.md`。

发送和接收记录会按日期追加到 `data/mqtt_history/*.jsonl`。服务重启后仍可通过界面的“查看通信历史”读取最近记录，也可以按 `workflowId` 调用只读历史接口查询。

“查看通信历史”会把语义回包整理成可选择的记录。点击“载入并生成流程”后，界面恢复历史 `originalText` 和 `parameters`，再使用当前版本的元操作能力库重新检查并编排；不会重放历史执行步骤。仍需澄清的成功记录可以载入查看，但补充完整并重新进行语义处理前不会生成流程。

## 界面结构

- 顶部：总体意图输入、语音转写和任务预处理。
- 左侧：绿色检测仪器、蓝色机器人、红色实验室环境元操作。
- 中间：意图到元操作和物理可执行确认。
- 右侧：执行状态与记录、结构化实验结果。

## 数据与边界

`data/vd10_agent_only_operation_tree.json` 提供 VD10 小操作节点，`data/meta-operations.json` 是界面、任务编排器和交接程序共同使用的唯一元操作能力库。能力库现包含 35 项能力，覆盖 VD10、样品采集、接收登记、恒温、摇匀、过滤、消泡、分装、运输、设备上下料、检测路由和结果读取。格式约束见 `schemas/meta-operation-library.schema.json`，交接说明见 `docs/META_OPERATION_SPEC.md`、`docs/META_OPERATION_CATALOG.md` 和 `docs/META_OPERATION_HANDOFF.md`。

`data/spatial-locations.json` 保存多楼层空间位置注册表，格式约束见 `schemas/spatial-location-library.schema.json`。坐标原点位于一楼墙角，统一使用米。用户提供的一楼送检工作台左下角坐标 `(1.025, 2.93, 0)`，长宽高为 `1.75 / 0.75 / 0.763 m`；VD10 位于三楼并由 `0.76 / 0.63 / 0.70 m` 的小桌支撑。

楼层高度暂按 `3.6 m`，VD10、小桌和电梯停靠点坐标均为可替换的临时值。空间库还登记了一楼至三楼的电梯运输链路，规划时通过稳定的位置 ID 和运输链路 ID 引用。上述临时数据只用于可视化和任务编排，现场标定完成并将状态改为 `verified` 前，物理执行仍会被阻止。

元操作仍分为绿色检测仪器、蓝色机器人和红色实验室环境三类。机械臂与 AGV 元操作来自 `机器人操作（机械臂部分）.docx`，不保存负责人信息；尚未完成实机验证的能力会显示“草案”或“待实机验证”。

语音只负责转成可编辑文字，不会自动执行设备。配置 `TENCENTCLOUD_APP_ID` 后使用腾讯云实时 ASR：点击开始只启动麦克风和实时识别服务，界面先显示“等待说话”；腾讯 VAD 检测到人声后才产生 `utteranceStartedAt`，静音断句后返回句级和词级时间戳。未配置 AppId 时自动使用原有30秒一句话识别兼容模式。通过语音转写发送 MQTT 时，`ui_input` 会携带可选的 `asrTiming`；原有摘要字段保持不变，实时模式额外携带 `serviceStartedAt`、`streamStartedAt` 和 `sentences`。手动输入或修改过的转写文字不携带该字段。修改已预处理的文字会使旧结果失效，再点击“生成实验流程”会改用当前文字重新进行本地预处理；也可以重新发送 MQTT 语义处理获得上游结果。模拟执行不会生成虚假的 VD10 测量值，真实数据接入前显示为等待回传。

## 测试

```powershell
node .\tests\meta-operation-library-test.js
node .\tests\smoke-test.js
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*backend.py" -v
.\.venv\Scripts\python.exe -m compileall -q backend
```
