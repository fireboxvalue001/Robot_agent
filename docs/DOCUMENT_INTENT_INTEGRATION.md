# 委托单意图识别接入说明

## 作用与边界

本模块参考 `robot_agent/意图识别模块_本地测试包` 的文档提取思路，在当前 VD10 项目内实现了独立适配层。原测试包未被修改。

模块负责读取 PDF/TXT 委托单，提取样品、检测项目、标准、报告要求、约束和待确认项，并转换成现有 `semantic_params` 消息。它不生成元操作链、不进行物理可执行确认，也不直接控制设备。

只有全部检测项目与 VD10 已登记能力匹配时，输出才会包含 `target_device=VD10`。运动黏度、水分、酸值等不属于当前 VD10 能力范围的项目会进入 `needs_routing`，不会自动分配给 VD10。

## 接口

- `GET /api/intent/document/status`：查看模型配置、PDF 解析器和支持格式。
- `POST /api/intent/document`：上传 `document` 文件，可选表单字段 `workflowId`。
- `GET /api/health`：`documentIntent` 字段显示模块状态。

成功响应包含：

- `intent`：稳定的文档意图结构，遵循 `schemas/document-intent.schema.json`。
- `semanticParams`：供现有界面、MQTT 语义层或编排模块使用的标准预处理结构。

界面中的“识别委托单”按钮会调用该接口，并把 `semanticParams` 载入第一部分。存在待确认字段时不会直接生成流程。

## 本地配置

PDF 读取依赖项目虚拟环境中的 `pypdf`：

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
```

模型密钥只写在 `backend/.env`。优先级为：

1. `DOCUMENT_INTENT_API_KEY`，配合 `DOCUMENT_INTENT_BASE_URL` 和 `DOCUMENT_INTENT_MODEL`。
2. `DASHSCOPE_API_KEY`，默认使用阿里云 Token Plan 兼容地址和 `qwen3.7-plus`。
3. 已有 `DEEPSEEK_API_KEY`，默认复用 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`。

不需要把密钥配置到 Windows 全局环境变量。

## 限制

- 文件最大 10 MB；PDF 最多 100 页；提取文字最多 100,000 字符。
- 仅处理带文字层的 PDF。扫描件需要先经过 OCR，再以 TXT 或可搜索 PDF 输入。
- 文档结构提取依赖模型，因此结果必须经过 JSON Schema、能力边界和待确认项校验。
- 当前 VD10 匹配规则位于 `knowledge/document_intent/vd10_capability.json`。扩展仪器时应增加独立能力描述与路由器，不应把所有检测项目写入 VD10。

## 快速验证

启动项目后，界面上传 `examples/document-intent.sample.txt`。也可以调用：

```powershell
curl.exe -X POST http://127.0.0.1:8877/api/intent/document -F "document=@examples/document-intent.sample.txt"
```

同事提供的空白委托单和 6 份 PDF 测试样例已复制到 `examples/document-intent-documents/`，可直接从界面选择上传。样例用于验证字段提取与能力边界，不表示其中所有检测项目都属于 VD10。
