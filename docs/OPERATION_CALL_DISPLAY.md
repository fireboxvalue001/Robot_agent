# 元操作重复调用的展示约定

## 身份与说明分开

C2元操作的operation_id、version、name描述能力身份；C3节点的id描述本次调用。重复调用同一能力不创建新能力ID。每次调用可以有不同的输入绑定、用途标题和参数展示标签。

`display`仅是调用层展示信息，不能改变能力身份、输入值、输出、前置条件或执行策略。不能因为标题写了“加热”就把触屏操作变成加热能力。没有display的旧场景、手动拖入的操作继续使用原能力名及原参数展示。

## 通用JSON

下面只说明格式；operation_id须替换成实际C2中已有的ID，不能将此示例当成新增能力。

```json
{
  "id": "step_unique_id",
  "operation_id": "robot.meta.operate_touchscreen",
  "input_bindings": {
    "target_control": {"value": "vd10.menu.enter_quality"},
    "expected_page": {"value": "quality_menu"}
  },
  "display": {
    "title": "进入质量菜单",
    "fields": [
      {"argument": "target_control", "label": "目标控件"},
      {"argument": "expected_page", "label": "预期页面"}
    ]
  }
}
```

也支持标题模板，例如`将{{object_id}}送到{{target_location_id}}`。占位符只读取本节点同名输入绑定，不访问任意对象路径，不执行代码。参数引用从已绑定参数中解析；无值显示待补充；资源或反馈引用显示待绑定或前序反馈，不伪装成测量值。字段可附unit作展示后缀，不进行单位换算。

配置校验拒绝标题或fields引用不存在的input_bindings。标题、参数及对象文字按文本转义，长标题换行，不用省略号丢失对象信息。建议模板尽量简洁，并通过fields展示更长的对象与参数信息。

## 一致显示与归档

前端`operation-display.js`提供共用的调用说明解析。顶部流程图展示本次用途，另起一行标明引用能力；详情展示调用参数。下方仍使用原有可拖曳操作卡片，物理确认卡片使用相同调用标题。

步骤归档保留调用display、参数绑定、节点ID和C2能力身份，方便区分相同能力的不同调用。修改标题不自动通过逻辑或物理校验，也不会自动启用设备。

VD10示例：两个节点都调用robot.meta.operate_touchscreen，分别显示进入质量菜单、打开质量状态；目标分别绑定vd10.menu.enter_quality、vd10.quality.open_status。标题从原C2内部节点名称取得，能力本身不更名、不复制。
