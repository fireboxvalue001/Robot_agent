"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");
const root = path.resolve(__dirname, "..");
const context = vm.createContext({});
for (const file of ["operation-display.js", "extraction-flow.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), context);
}
const present = context.OperationDisplay.describe;
const display = { title: "将{{object_id}}送到{{target}}", fields: [{ argument: "object_id", label: "样品" }, { argument: "target", label: "目标位置" }] };
const callA = { capabilityName: "通用搬运", display, bindings: { object_id: { value: "样品A" }, target: { parameter_ref: "location" } }, parameters: { location: { value: "位置1" } } };
const callB = { ...callA, bindings: { object_id: { value: "样品B" }, target: { value: "位置2" } } };
const original = JSON.stringify(callA);
assert.equal(present(callA).title, "将样品A送到位置1");
assert.equal(present(callB).title, "将样品B送到位置2");
assert.equal(present(callA).capabilityName, present(callB).capabilityName);
assert(present(callB).summary.includes("样品：样品B"));
assert.equal(JSON.stringify(callA), original, "presentation must not mutate parameters");
assert.equal(present({ capabilityName: "原能力" }).title, "原能力", "legacy cards retain their titles");
assert(present({ display: { title: "{{missing}}" } }).title.includes("待补充"));
const long = "很长但必须完整展示的对象名称".repeat(5);
assert.equal(context.OperationDisplay.wrap(long).join(""), long, "wrapping must never truncate text");
const definition = { name: "重复调用", entry: "a", parameters: {}, resources: [], phases: [{ id: "p1", label: "1. 原能力" }, { id: "p2", label: "2. 原能力" }], nodes: [
  { id: "a", kind: "action", operation_id: "robot.meta.same", operation_name: "机械臂触摸屏操作", label: "原能力", phase_id: "p1", display: { title: "进入质量菜单" }, arguments: {}, status: "covered", reason: "未执行", next: "b", requires: [] },
  { id: "b", kind: "action", operation_id: "robot.meta.same", operation_name: "机械臂触摸屏操作", label: "原能力", phase_id: "p2", display: { title: "打开质量状态" }, arguments: {}, status: "covered", reason: "未执行", requires: [] }
] };
let html = context.renderConfiguredWorkflow(definition);
assert(html.includes("1. 进入质量菜单"));
assert(html.includes("2. 打开质量状态"));
assert(html.includes("使用能力：机械臂触摸屏操作"));
assert(html.includes("1次能力调用 · 0项检查"));
assert(!html.includes("个单步及检查"));
definition.nodes[0].display.title = "<script>alert(1)</script>";
html = context.renderConfiguredWorkflow(definition);
assert(!html.includes("<script>"));
assert(html.includes("&lt;script&gt;"));
console.log("Reusable call display: distinct objects/parameters, stable capability, templates, wrapping and escaping passed");
