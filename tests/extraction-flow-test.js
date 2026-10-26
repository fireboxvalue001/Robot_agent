"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const root = path.resolve(__dirname, "..");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(root, "extraction-flow.js"), "utf8"), context);
const scenario = JSON.parse(fs.readFileSync(path.join(root, "knowledge/planner_scenarios/leather_extraction.json"), "utf8"));
const resources = JSON.parse(fs.readFileSync(path.join(root, "data/leather-extraction-resources.json"), "utf8"));
const workflow = {name:scenario.name, phases:scenario.phases, nodes: scenario.nodes.map(node => ({...node, status: node.requires.length ? "needs_input" : "covered", reason: "定义已匹配，尚未执行"})), parameters: {}, resources: resources.resources};
const result = context.renderExtractionWorkflow(workflow);
assert(result.includes('<svg viewBox='));
assert(result.includes("称量瓶恒重"));
assert(result.includes("空抽提瓶恒重"));
assert(result.includes("抽提后恒重"));
assert(result.includes("达到上限 → 停止复核"));
assert(result.includes("否：再次干燥"));
assert(result.includes("数据") && result.includes("尚未执行"));
assert(!result.includes("元操作") && !result.includes("C2"));
for (const node of scenario.nodes.filter(item => item.kind === "loop_check")) {
  const target = scenario.nodes.find(item => item.id === node.on_pass);
  const edge = result.match(new RegExp(`<g data-phase-edge="${node.phase_id}:${target.phase_id}">([\\s\\S]*?)</g>`));
  assert(edge, "Constant-mass pass edge must exist");
  assert.strictEqual((edge[1].match(/>是<\/text>/g) || []).length, 1, "Each constant-mass pass branch must have exactly one yes label");
}
assert(!/<text x="410"[^>]*>是<\/text>/.test(result), "Decision labels must not be hard-coded a second time on the arrow center");
const sharedEdge = {name:"连线去重",phases:[{id:"a",label:"判断阶段"},{id:"b",label:"后续阶段"}],parameters:{},resources:[],nodes:[
  {id:"check",phase_id:"a",kind:"decision",label:"检查",status:"covered",reason:"",on_pass:"end",on_fail:"end"},
  {id:"prepare",phase_id:"a",kind:"action",label:"准备",status:"covered",reason:"",next:"end"},
  {id:"end",phase_id:"b",kind:"end",label:"完成",status:"covered",reason:""}
]};
const sharedSvg = context.renderConfiguredWorkflow(sharedEdge);
assert.strictEqual((sharedSvg.match(/data-phase-edge="a:b"/g)||[]).length, 1, "Shared phase edges must not overlap");
assert(sharedSvg.includes('>是 / 否</text>'), "Merged branches must retain both labels");
workflow.nodes[0].label = '<img src=x onerror="alert(1)">';
assert(!context.renderExtractionWorkflow(workflow).includes('<img src=x'));
assert(context.renderExtractionWorkflow(workflow).includes("&lt;img"));
workflow.clarifications = [
  {kind:"parameter",field:"extraction_hours",label:"抽提时长",unit:"h",minimum:7,maximum:8,related_steps:["索氏抽提"],format:"抽提时长：数值h"},
  {kind:"method",field:"solvent_removal_method",label:"方法尚未审核",related_steps:[],instruction:"需维护者审核"}
];
const checklist = context.renderExtractionClarifications(workflow);
assert(checklist.includes("1 项参数 · 1 项其他待处理"));
assert(checklist.includes('<details class="clarification-checklist-details">'));
assert(!checklist.includes('<details class="clarification-checklist-details" open'), "Checklist must be collapsed by default");
assert(checklist.includes('data-extraction-field="extraction_hours"'));
assert(checklist.includes("用于：索氏抽提") && checklist.includes("文字填写格式：抽提时长：数值h"));
assert(!checklist.includes('value="7"'), "No invented default value should fill the form");
assert(!checklist.includes('data-extraction-field="solvent_removal_method"'), "Method approval is not a numerical user input");
workflow.clarifications[0].label = '<img src=x onerror="alert(1)">';
assert(!context.renderExtractionClarifications(workflow).includes('<img src=x'));
const hold = JSON.parse(fs.readFileSync(path.join(root, "knowledge/planner_scenarios/sample_hold.json"), "utf8"));
const generic = {name:hold.name,phases:hold.phases,nodes:hold.nodes.map(node=>({...node,status:"needs_input",reason:"待补充"})),parameters:{},resources:[]};
const genericHtml = context.renderConfiguredWorkflow(generic);
assert(genericHtml.includes("1. 样品放置") && genericHtml.includes("2. 定时静置"));
assert(!genericHtml.includes("恒重") && !genericHtml.includes("回流") && !genericHtml.includes("蒸馏"));
generic.clarifications = [{kind:"parameter",field:"mode",type:"string",label:"存放方式",enum:["常规","遮光"],related_steps:[]}, {kind:"parameter",field:"confirmed",type:"boolean",label:"已核对",related_steps:[]}];
const genericForm = context.renderConfiguredClarifications(generic);
assert(genericForm.includes('<select') && genericForm.includes('value="遮光"') && genericForm.includes('value="是"'));
console.log("leather extraction flow rendering test passed");
