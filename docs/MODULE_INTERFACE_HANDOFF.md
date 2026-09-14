# 模块接口与联调交接说明

## 1. 模块边界

- UI/ASR只产生经过用户确认的文字，不负责理解意图。
- 同事A订阅 `autolab/ui/input`，负责意图理解、参数提取、缺失/冲突判断和UI提示，发布 `autolab/semantic/params`。
- 同事B订阅 `autolab/semantic/params`，读取本项目提供的能力快照，选择元操作并发布 `autolab/planner/result`。
- 物理校验模块订阅 `autolab/planner/result`，检查位置、设备、资源和前置条件，发布 `autolab/physical/validation`。
- UI只校验和展示各模块结果，不推测未知元操作，也不替外部模块修正参数。

## 2. 能力查询接口

本项目启动后提供两个只读HTTP接口：

```text
GET http://<UI主机>:8877/api/v1/capabilities/meta-operations
GET http://<UI主机>:8877/api/v1/capabilities/spatial-locations
```

元操作响应包含 `libraryId`、`libraryVersion`、`checksum`、分类、仪器、前置条件和 `metaOperations`。空间响应包含统一坐标系、楼层、位置及运输链路。

同事B编排前保存这三个值：

```json
{
  "id": "autolab.vd10.meta_operations",
  "version": "1.3.0",
  "checksum": "sha256:..."
}
```

并原样写入 `operationChain.capabilityLibrary`。任意一项与UI当前能力库不一致，规划结果都会被拒绝，避免使用过期ID。

## 3. 同事A输入输出

输入Topic：`autolab/ui/input`。核心业务输入是 `text`，语音输入可能额外包含 `asrTiming`。

输出Topic：`autolab/semantic/params`，Schema为 `schemas/semantic-params.schema.json`。

同事A应输出：

- 原始文字 `originalText`。
- 动态提取字段 `parameters`。
- 实验类型 `experimentType`（可选）。
- `clarification.needed`、`missingFields`、`conflictingFields` 和 `questions`。
- 上游公共字段及累积的 `history`。

当信息不足或冲突时设置 `clarification.needed=true`。UI显示问题并阻止进入编排，不再使用前端关键词替同事A作决定。

## 4. 同事B输入输出

输入Topic：`autolab/semantic/params`。只对 `status=success` 且不需要澄清的消息编排。

输出Topic：`autolab/planner/result`，Schema为 `schemas/planner-result.schema.json`，完整示例为 `examples/planner-result.sample.json`。

保留上游已有的 `experimentName`、`steps`、`parameters` 和 `warnings`。成功消息必须额外包含 `operationChain`：

- `contractVersion`：当前固定为 `1.0.0`。
- `planId`：本次规划唯一ID，格式 `plan_<uuid>`。
- `capabilityLibrary`：编排实际使用的能力库ID、版本和SHA-256。
- `operations`：按元操作组成的任务链。
- `operations[].stepId`：计划内稳定步骤ID。
- `operations[].sequence`：展示顺序，从1开始。
- `operations[].metaOperationId`：必须来自能力快照。
- `operations[].metaOperationVersion`：必须与能力快照一致。
- `operations[].arguments`：该步骤自己的参数，不把所有参数混在顶层。
- `operations[].dependsOn`：依赖的步骤ID。

UI根据 `metaOperationId` 查本地能力库，生成名称、颜色、说明和内部操作树。B不发送HTML、颜色、卡片名称或坐标副本。

## 5. 物理校验输入输出

输入Topic：`autolab/planner/result`。

输出Topic：`autolab/physical/validation`，Schema为 `schemas/physical-validation.schema.json`，示例为 `examples/physical-validation.sample.json`。

返回内容包括：

- 与规划一致的 `workflowId` 和 `planId`。
- 总结论 `executable`、`blocked` 或 `requires_confirmation`。
- 每个步骤的 `stepId`、`executable`、`checks` 和 `blockers`。

物理校验只评价任务链，不调整顺序、不替换元操作。需要修改时应让B产生新的 `planId` 和规划结果。

## 6. MQTT同步规则

1. UI创建 `workflowId`，A、B和物理校验模块必须原样透传。
2. 每条新消息单独生成 `msgId`，不能复用上一模块ID。
3. `index` 正常按UI=0、A=1、B=2、物理校验=3递增。
4. 发布者把上一阶段摘要追加到 `history`，不要删除已有记录。
5. `timestamp` 使用同步系统时钟产生的Unix毫秒时间。
6. JSON使用UTF-8，Topic区分大小写，消息不设置retain。
7. 当前项目按 `msgId` 去重，按 `workflowId` 聚合，按 `planId`关联规划与物理校验。

## 7. 异常与注意事项

- 未知元操作ID、版本不一致、能力库摘要不一致：拒绝整条规划，不做名称模糊匹配。
- 重复 `stepId`、未知依赖、缺少逐步参数：拒绝规划。
- 同事A要求澄清：不得调用同事B或执行模块。
- `status=failed`：保留错误消息和历史，不自动重发。
- MQTT结果可能乱序到达，接收端必须使用三个ID关联，不能依赖到达时间。
- 能力库中的 `draft`、`pending_verification` 和 `interface_only` 不等于真实可执行；同事B可以用于模拟编排，但物理校验必须给出阻断或确认要求。
- 空间位置带 `placeholder=true` 或未验证时，只能用于模拟。
- 人工拖拽后的流程应保存为新修订，不覆盖同事B的原始规划证据。

## 8. 交接文件

```text
data/meta-operations.json
data/spatial-locations.json
schemas/meta-operation-library.schema.json
schemas/spatial-location-library.schema.json
schemas/semantic-params.schema.json
schemas/planner-result.schema.json
schemas/physical-validation.schema.json
examples/planner-result.sample.json
examples/physical-validation.sample.json
docs/MODULE_INTERFACE_HANDOFF.md
```
