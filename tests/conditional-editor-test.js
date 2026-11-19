"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");
const root = path.resolve(__dirname, "..");
const library = JSON.parse(fs.readFileSync(path.join(root, "data/meta-operations.json"), "utf8"));
const scene = JSON.parse(fs.readFileSync(path.join(root, "knowledge/planner_scenarios/vd10_screen_robot_quality.json"), "utf8"));
const byId = new Map(library.meta_operations.map(op => [op.id, op]));
const elements = new Map();
const get = id => {
  if (!elements.has(id)) elements.set(id, { value: "", innerHTML: "", textContent: "", classList: { toggle() {} } });
  return elements.get(id);
};
const context = vm.createContext({ document: { getElementById: get, querySelectorAll: () => [] },
  window: {}, library });
vm.runInContext(fs.readFileSync(path.join(root, "operation-display.js"), "utf8"), context);
vm.runInContext(fs.readFileSync(path.join(root, "app.js"), "utf8").replace(/initialize\(\);\s*$/, ""), context);
vm.runInContext("loadMetaOperationLibrary(library); renderAll = () => {}; showToast = () => {};", context);
context.renderLibrary();
assert.match(get("operation-library").innerHTML, /检测仪器元操作<\/span><span>35 项<\/span>/);
get("library-search").value = "索氏抽提器";
context.renderLibrary();
assert.match(get("operation-library").innerHTML, /索氏抽提器<\/span><span>6 项关联/);
assert.match(get("operation-library").innerHTML, /data-id="robot.meta.monitor_reflux"/);
get("library-search").value = "分析天平";
context.renderLibrary();
assert.match(get("operation-library").innerHTML, /空容器放上天平后将读数归零/);
assert.match(get("operation-library").innerHTML, /data-id="robot.meta.read_balance_mass"/);
get("library-search").value = "";
const importedId = "vd10.meta.manual_test";
context.importedLibrary = { ...library, meta_operations: [...library.meta_operations, {
  ...library.meta_operations.find(op => op.id === "vd10.meta.prepare_test"),
  id: importedId, name: "说明书新增测试动作", status: "pending_verification", execution_policy: "interface_only",
  extensions: { manual_import: { preview_enabled: false } }
}] };
vm.runInContext("loadMetaOperationLibrary(importedLibrary)", context);
get("library-search").value = "说明书新增测试动作";
context.renderLibrary();
assert.match(get("operation-library").innerHTML, /draggable="false" data-id="vd10.meta.manual_test"/);
assert.match(get("operation-library").innerHTML, /op-card-imported/);
assert.match(get("operation-library").innerHTML, /VD10自动蒸馏测定仪 <span class="op-new-mark"/);
assert.match(get("operation-library").innerHTML, /class="op-new-mark"[^>]*>新</);
assert.match(get("operation-library").innerHTML, /<details class="operation-details">\s*<summary>[^<]+<\/summary>\s*<p><b>状态：<\/b>已入库 · 未启用编排/);
assert(!get("operation-library").innerHTML.includes('class="op-add"'));
assert.strictEqual(context.appendMetaOperation(importedId), false);
get("library-search").value = "";
vm.runInContext("loadMetaOperationLibrary(library)", context);
context.newDeviceLibrary = { ...library, instruments: [...library.instruments,
  { id: "manual_device_test", name: "新增空设备", manual_device: true }] };
vm.runInContext("loadMetaOperationLibrary(newDeviceLibrary)", context);
get("library-search").value = "新增空设备";
context.renderLibrary();
assert.match(get("operation-library").innerHTML, /新增空设备 <span class="op-new-mark"[^>]*>新<\/span><\/span><span>0 项/);
get("library-search").value = "设备:新增空设备";
context.renderLibrary();
assert.match(get("operation-library").innerHTML, /新增空设备.*0 项/);
assert(!get("operation-library").innerHTML.includes("VD10自动蒸馏测定仪"));
get("library-search").value = "";
vm.runInContext("loadMetaOperationLibrary(library)", context);
const definition = { ...scene, parameters: {}, nodes: scene.nodes.map(node => ({ ...node,
  status: "covered", reason: "尚未执行", arguments: node.input_bindings || {},
  ...(node.operation_id ? { operation_version: byId.get(node.operation_id).version } : {}) })) };
const trace = { validation: {}, decision: { logical_executable: true } };
context.receivePlannerResult({ status: "success", workflow_definition: definition, reasoning_trace: trace });
assert.equal(JSON.parse(vm.runInContext("JSON.stringify(workflow.map(step => step.operation.meta_operation_id))", context)).length, 3);
context.renderFlow(context.validateWorkflow());
assert.equal((get("semantic-flow").innerHTML.match(/draggable="true"/g) || []).length, 3);
assert.equal((get("semantic-flow").innerHTML.match(/class="flow-remove"/g) || []).length, 3);
assert.equal((get("physical-flow").innerHTML.match(/data-step-id=/g) || []).length, 3);
assert(get("semantic-flow").innerHTML.includes("进入质量菜单"));
assert(get("semantic-flow").innerHTML.includes("打开质量状态"));
assert(get("semantic-flow").innerHTML.includes("使用能力：机械臂触摸屏操作"));
assert(get("physical-flow").innerHTML.includes("打开质量状态"));
assert.equal(context.getExecutionArchiveSnapshot().plan.editor_projection.steps[0].display.title, "进入质量菜单");
assert(!get("semantic-flow").innerHTML.includes("任务入口"));
assert(!get("semantic-flow").innerHTML.includes("核验能力反馈"));
assert(!get("semantic-flow").innerHTML.includes("data-configured-node"));
assert.equal(get("simulate-execution").disabled, true);
context.addMetaOperation("robot.meta.read_result_from_screen");
assert.equal(vm.runInContext("workflow.length", context), 4);
assert.equal(vm.runInContext("conditionalEditorDirty", context), true);
assert.equal(vm.runInContext("latestConditionalWorkflow !== null", context), true);
assert.equal(context.validateWorkflow().semanticReady, false);
assert.equal(context.validateWorkflow().physicalReady, false);
context.renderFlow(context.validateWorkflow());
assert(get("semantic-flow").innerHTML.includes("不需要因此补填设备参数"));
assert.equal(get("semantic-state").textContent, "待重新校验");
assert.equal(context.getExecutionArchiveSnapshot().plan.editor_projection.steps.length, 4);
assert.equal(context.getExecutionArchiveSnapshot().plan.editor_projection.execution_allowed, false);
context.receivePlannerResult({ status: "success", workflow_definition: definition, reasoning_trace: { validation: {}, decision: { logical_executable: true } } });
assert.equal(vm.runInContext("conditionalEditorDirty", context), false);
assert.equal(vm.runInContext("workflow.length", context), 3);
const invalid = structuredClone(definition);
invalid.nodes.find(node => node.operation_id).operation_id = "robot.meta.unknown";
assert(context.projectConditionalOperations(invalid).errors.length);
assert.equal(context.projectConditionalOperations(invalid).steps.length, 0);
const calculation = {scenario_id:"leather_fat_extraction", parameters:{}, clarifications:[{kind:"parameter",label:"实际干样质量md"}],
  nodes:[{id:"provided_mass",kind:"guard",check:{type:"provided_measurement"}},
    {id:"content",kind:"compute",label:"按实际干样质量计算含量"}]};
context.receivePlannerResult({status:"needs_input",workflow_definition:calculation,
  reasoning_trace:{validation:{},decision:{logical_executable:false}}});
context.renderFlow(context.validateWorkflow());
assert.equal(get("semantic-state").textContent,"待补数据");
assert(get("semantic-flow").innerHTML.includes("已生成 1 个软件计算步骤"));
assert(get("semantic-flow").innerHTML.includes("按实际干样质量计算含量"));
assert.equal(get("physical-state").textContent,"无需物理元操作");
assert(!get("semantic-flow").innerHTML.includes('draggable="true"'));
assert.equal(vm.runInContext("workflow.length",context),0);
calculation.clarifications=[];
context.receivePlannerResult({status:"logical_pass",workflow_definition:calculation,
  reasoning_trace:{validation:{},decision:{logical_executable:true}}});
context.renderFlow(context.validateWorkflow());
assert.equal(get("semantic-state").textContent,"计算流程已匹配");
assert.equal(context.validateWorkflow().semanticReady,true);
assert.equal(context.validateWorkflow().physicalReady,false);
assert(get("physical-flow").innerHTML.includes("不表示已经完成计算"));
assert.equal(get("simulate-execution").disabled,true);
calculation.nodes[0].check={type:"physical_device_guard"};
context.receivePlannerResult({status:"needs_input",workflow_definition:calculation,
  reasoning_trace:{validation:{},decision:{logical_executable:false}}});
assert.equal(context.isDataCalculationOnly(),false,"Unknown physical checks cannot be exempted");
const reviewDefinition = structuredClone(definition);
reviewDefinition.clarifications = [{kind:"method", label:"实际挥发流程已说明；原加热工位、通风与方法审核待确认",
  instruction:"无需重复说明方法。", questions:["原工位是否适用？"], configuration_notice:"维护者需审核方法。"}];
reviewDefinition.nodes[0].status = "needs_input";
reviewDefinition.nodes[0].reason = "方法已说明但仍待审核确认";
context.receivePlannerResult({status:"failed",workflow_definition:reviewDefinition,
  reasoning_trace:{validation:{},decision:{status:"NEEDS_REVIEW",logical_executable:false}}});
context.renderFlow(context.validateWorkflow());
assert.equal(get("semantic-state").textContent, "待补方法信息");
assert.equal(get("semantic-state").className, "check-state warn");
assert(!get("semantic-flow").innerHTML.includes("原工位是否适用？"));
assert(!get("semantic-flow").innerHTML.includes('class="flow-validation-notice"'));
assert.equal((get("semantic-flow").innerHTML.match(/draggable="true"/g)||[]).length, 3);
assert.equal(context.validateWorkflow().semanticReady,false);
assert.equal(context.validateWorkflow().physicalReady,false);
reviewDefinition.clarifications.unshift({kind:"parameter",label:"等待时长"});
context.receivePlannerResult({status:"failed",workflow_definition:reviewDefinition,
  reasoning_trace:{validation:{},decision:{status:"NEEDS_INPUT",logical_executable:false}}});
context.renderFlow(context.validateWorkflow());
assert.equal(get("semantic-state").textContent,"待补参数");
assert(!get("semantic-flow").innerHTML.includes('class="flow-validation-notice"'));
assert(!get("semantic-flow").innerHTML.includes("等待时长"));
assert.equal((get("semantic-flow").innerHTML.match(/draggable="true"/g)||[]).length, 3);
context.receivePlannerResult({status:"failed",workflow_definition:reviewDefinition,
  reasoning_trace:{validation:{},decision:{status:"MODEL_ERROR",logical_executable:false}}});
context.renderFlow(context.validateWorkflow());
assert.equal(get("semantic-state").textContent,"存在问题");
assert.equal(get("semantic-state").className,"check-state error");
const draftDefinition = structuredClone(definition);
draftDefinition.physical_requirements = [{label:"挥发去除",instruction:"执行前确认设备与通风",checks:["停止接口可用"],status:"pending"}];
draftDefinition.usage_prerequisites = [{label:"挥发去除",instruction:"实际使用前确认适用性"}];
context.receivePlannerResult({status:"success",workflow_definition:draftDefinition,
  reasoning_trace:{validation:{},decision:{status:"PHYSICAL_PENDING",logical_executable:true}}});
context.renderFlow(context.validateWorkflow());
assert.equal(get("semantic-state").textContent,"匹配通过");
assert(get("physical-flow").innerHTML.includes("停止接口可用"));
assert(!get("semantic-flow").innerHTML.includes("停止接口可用"));
assert.equal(get("physical-state").textContent,"待确认");
assert.equal(context.validateWorkflow().physicalReady,false);
assert.equal(get("simulate-execution").disabled,true);
console.log("Conditional editor: draggable cards, review versus errors, physical safety and dirty-state tests passed");
