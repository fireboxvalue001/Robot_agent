"use strict";

const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const indexHtml = fs.readFileSync(path.join(root, "index.html"), "utf8");
const elements = new Map();
const windowListeners = new Map();

function makeElement(id) {
  return {
    id,
    value: id === "intent-input"
      ? "将桌上的样品分成4份，每份25ml，分别送到四个仪器中进行检测"
      : "",
    innerHTML: "",
    textContent: "",
    hidden: false,
    dataset: {},
    listeners: {},
    className: "",
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(type, listener) { this.listeners[type] = listener; }
  };
}

[
  "parse-intent", "intent-input", "clear-flow", "library-search", "simulate-execution",
  "operation-count", "operation-library", "semantic-flow", "physical-flow",
  "semantic-state", "physical-state", "intent-summary", "intent-state",
  "tab-status", "tab-results", "toast", "spatial-location-count", "spatial-location-list"
].forEach((id) => elements.set(id, makeElement(id)));

global.document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  },
  querySelectorAll() { return []; }
};

global.window = {
  addEventListener(type, listener) {
    const listeners = windowListeners.get(type) || [];
    listeners.push(listener);
    windowListeners.set(type, listeners);
  },
  dispatchEvent(event) {
    (windowListeners.get(event.type) || []).forEach((listener) => listener(event));
  }
};
global.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};

global.fetch = async (resource) => ({
  ok: true,
  json: async () => JSON.parse(fs.readFileSync(path.join(
    root,
    "data",
    String(resource).includes("meta-operations")
      ? "meta-operations.json"
      : (String(resource).includes("spatial-locations")
        ? "spatial-locations.json"
        : "vd10_agent_only_operation_tree.json")
  ), "utf8"))
});

require(path.join(root, "app.js"));

function dispatchSemantic(originalText, parameters, clarification = {}) {
  window.dispatchEvent(new CustomEvent("autolab:semantic-params", {
    detail: {
      type: "semantic_params",
      status: "success",
      originalText,
      parameters,
      clarification: {
        needed: false,
        missingFields: [],
        questions: [],
        ...clarification
      }
    }
  }));
}

function setIntent(text) {
  const input = elements.get("intent-input");
  input.value = text;
  if (input.listeners.input) input.listeners.input();
}

setTimeout(() => {
  const semantic = elements.get("semantic-flow");
  const parseButton = elements.get("parse-intent");
  const defaultText = elements.get("intent-input").value;

  assert(elements.get("operation-count").textContent === "35 项", "the interface should show all 35 meta operations");
  assert(elements.get("operation-library").innerHTML.includes("样品定时加热"), "heating operation should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("样品摇匀混合"), "mixing operation should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("样品定时静置"), "holding operation should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("机械臂物体点到点搬运"), "physical transfer should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("样品接收与信息登记"), "sample registration should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("样品水浴恒温"), "water-bath conditioning should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("样品过滤除杂"), "sample filtering should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("规范取样与采样记录"), "sample collection should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("样品外观视觉初检"), "sample visual inspection should be visible in the library");
  assert(elements.get("operation-library").innerHTML.includes("检测任务科室与设备路由"), "test routing should be visible in the library");
  assert(!elements.get("operation-library").innerHTML.includes("新增基础能力"), "new capabilities must remain in the three standard categories");
  assert(
    elements.get("operation-library").innerHTML.indexOf("VD10自动蒸馏测定仪") <
      elements.get("operation-library").innerHTML.indexOf("VD10测试信息准备"),
    "VD10 operations should be nested under the VD10 instrument menu"
  );
  assert(elements.get("operation-library").innerHTML.includes("通用/待绑定检测仪器"), "generic instrument menu should be visible");
  assert(
    elements.get("operation-library").innerHTML.indexOf("VD10自动蒸馏测定仪") <
      elements.get("operation-library").innerHTML.indexOf("VD10检测结果查询"),
    "VD10 result query should be nested under the VD10 instrument menu"
  );
  assert(!elements.get("operation-library").innerHTML.includes('class="op-group instrument" open'), "instrument category should be collapsed by default");
  assert(!elements.get("operation-library").innerHTML.includes('class="op-group robot" open'), "robot category should be collapsed by default");
  assert(!elements.get("operation-library").innerHTML.includes('class="op-group lab" open'), "laboratory category should be collapsed by default");
  assert(!indexHtml.includes('class="spatial-location-panel" open'), "spatial information should be collapsed by default");
  assert(
    elements.get("operation-library").innerHTML.indexOf("机械臂物体点到点搬运") <
      elements.get("operation-library").innerHTML.indexOf("试管识别与位置标定"),
    "physical transfer should appear first in the robot category"
  );
  assert(elements.get("spatial-location-list").innerHTML.includes("VD10检测工位"), "VD10 location should be visible");
  assert(elements.get("spatial-location-list").innerHTML.includes("送检样品检录工作台"), "check-in location should be visible");
  assert(elements.get("spatial-location-count").textContent === "5 项", "the interface should show all five spatial locations");
  assert(elements.get("spatial-location-list").innerHTML.includes("3层建筑"), "building floor count should be visible");
  assert(elements.get("spatial-location-list").innerHTML.includes("层高 3.6 m"), "temporary floor height should be visible");
  assert(elements.get("spatial-location-list").innerHTML.includes("VD10支撑桌"), "VD10 support table should be visible");
  assert(elements.get("spatial-location-list").innerHTML.includes("一楼电梯候梯与进梯点"), "floor-1 elevator stop should be visible");
  assert(elements.get("spatial-location-list").innerHTML.includes("三楼电梯出梯点"), "floor-3 elevator stop should be visible");
  assert(elements.get("spatial-location-list").innerHTML.includes("小车一楼至三楼电梯运输"), "elevator route should be visible");
  assert(!semantic.innerHTML.includes("样品定量分装"), "workflow must wait for MQTT preprocessing");
  parseButton.listeners.click();
  assert(elements.get("intent-state").textContent.includes("需要补充信息"), "incomplete direct input must request required fields");

  const directText = "请将桌上的样品分成4份，每份25 mL；样品保持静置，无需摇匀；使用试管盛装，并分别送到4台VD10仪器中进行检测。";
  setIntent(directText);
  parseButton.listeners.click();
  assert(elements.get("intent-summary").innerHTML.includes("来源：自然语言本地提取"), "direct input should show local preprocessing source");
  assert(semantic.innerHTML.includes("样品定量分装"), "complete direct natural language should generate workflow");
  assert(semantic.innerHTML.includes("VD10样品检测"), "direct input should select VD10 testing");
  assert(semantic.innerHTML.includes("VD10检测结果查询"), "testing should automatically open the VD10 result view");
  assert(semantic.innerHTML.includes("非联网仪器屏幕数据读取"), "testing should append robot result acquisition");
  assert(semantic.innerHTML.includes("实验室跨区域转运"), "VD10 delivery should include floor-1 to floor-3 transport");
  assert(semantic.innerHTML.includes("lab.transport.elevator_floor1_to_floor3"), "VD10 delivery should reference the elevator route");
  assert(semantic.innerHTML.indexOf("样品定量分装") < semantic.innerHTML.indexOf("实验室跨区域转运"), "sample preprocessing must precede spatial transport");
  assert(semantic.innerHTML.indexOf("实验室跨区域转运") < semantic.innerHTML.indexOf("VD10样品检测"), "spatial transport must precede instrument execution");
  assert(semantic.innerHTML.indexOf("VD10样品检测") < semantic.innerHTML.indexOf("VD10检测结果查询"), "VD10 result query must follow instrument execution");
  assert(semantic.innerHTML.indexOf("VD10检测结果查询") < semantic.innerHTML.indexOf("非联网仪器屏幕数据读取"), "robot information acquisition must follow the VD10 result query");

  setIntent(defaultText);

  dispatchSemantic(defaultText, {
    test_item_description: { type: "string", value: "样品分装送检" },
    sample_volume_requirement: { type: "number", value: 25, unit: "mL" }
  }, {
    needed: true,
    missingFields: ["instrument_requirement"],
    questions: ["请问需要配套哪些仪器？"]
  });
  assert(elements.get("intent-summary").innerHTML.includes("最低样品体积：25 mL"), "preprocessing fields should be visible");
  assert(elements.get("intent-summary").innerHTML.includes("缺少字段：instrument_requirement"), "missing fields should be visible");
  parseButton.listeners.click();
  assert(!semantic.innerHTML.includes("样品定量分装"), "incomplete preprocessing must not produce workflow");

  dispatchSemantic(defaultText, {
    test_item_description: { type: "string", value: "样品分装并送到仪器检测" },
    mixing_requirement: { type: "string", value: "静置" },
    sample_volume_requirement: { type: "number", value: 25, unit: "mL" },
    instrument_requirement: { type: "string", value: "试管" }
  });
  parseButton.listeners.click();
  assert(semantic.innerHTML.includes("样品定量分装"), "complete result should select sample aliquoting");
  assert(semantic.innerHTML.includes("试管装载至AGV"), "complete result should load tubes onto AGV");
  assert(semantic.innerHTML.includes("AGV工位间样品运输"), "complete result should select AGV transport");
  assert(semantic.innerHTML.includes("检测仪器送样准备与装载"), "complete result should select instrument loading");
  assert(semantic.innerHTML.includes("VD10样品检测"), "complete result should select test operation");
  assert(semantic.innerHTML.indexOf("VD10样品检测") < semantic.innerHTML.indexOf("VD10检测结果查询"), "result acquisition must follow instrument testing");
  assert(semantic.innerHTML.includes("4份"), "workflow should retain count from the processed intent");
  assert(semantic.innerHTML.includes("25mL"), "workflow should use the semantic volume field");

  const historyText = "将桌上的样品分成3份，每份20ml，送到仪器进行检测";
  window.dispatchEvent(new CustomEvent("autolab:semantic-history-selected", {
    detail: {
      message: {
        type: "semantic_params",
        status: "success",
        workflowId: "wf_history-test",
        msgId: "msg_history-test",
        originalText: historyText,
        parameters: {
          test_item_description: { type: "string", value: "样品分装送检" },
          mixing_requirement: { type: "string", value: "静置" },
          sample_volume_requirement: { type: "number", value: 20, unit: "mL" },
          instrument_requirement: { type: "string", value: "试管" }
        },
        clarification: { needed: false, missingFields: [], questions: [] }
      },
      history: {
        workflowId: "wf_history-test",
        msgId: "msg_history-test",
        recorded_at: "2026-09-07T20:39:58.659+08:00"
      }
    }
  }));
  assert(elements.get("intent-input").value === historyText, "history loading should restore original text");
  assert(elements.get("intent-summary").innerHTML.includes("来源：历史语义记录"), "history source should be visible");
  assert(semantic.innerHTML.includes("样品定量分装"), "history loading should regenerate with the current library");
  assert(semantic.innerHTML.includes("3份"), "history planning should restore historical task parameters");

  const floorText = "将桌上的样品分成4份，每份25ml，分别送到四个仪器中进行检测，最后送到2楼";
  setIntent(floorText);
  dispatchSemantic(floorText, {
    test_item_description: { type: "string", value: "四份样品送检后转运" },
    mixing_requirement: { type: "string", value: "静置" },
    sample_volume_requirement: { type: "number", value: 25, unit: "mL" },
    instrument_requirement: { type: "string", value: "试管" },
    destination_floor: { type: "string", value: "2楼" }
  });
  parseButton.listeners.click();
  assert(semantic.innerHTML.indexOf("非联网仪器屏幕数据读取") < semantic.innerHTML.indexOf("实验室跨区域转运"), "final transfer must occur after result acquisition");
  assert(semantic.innerHTML.includes("执行时序：检测后"), "post-test timing should be visible");

  setIntent(`${floorText}，请尽快`);
  parseButton.listeners.click();
  assert(elements.get("intent-state").textContent.includes("需要补充信息"), "edited text should be preprocessed again and request missing fields");
  assert(elements.get("intent-summary").innerHTML.includes("来源：自然语言本地提取"), "edited text should not reuse stale MQTT fields");
  assert(!semantic.innerHTML.includes("VD10样品检测"), "incomplete local preprocessing must not produce workflow");

  const heatingText = "帮我做一个温度为50度，持续60分钟的加热实验";
  setIntent(heatingText);
  dispatchSemantic(heatingText, {
    test_item_description: { type: "string", value: "50度持续60分钟加热" },
    mixing_requirement: { type: "string", value: "静置" },
    sample_volume_requirement: { type: "number", value: 50, unit: "mL" },
    instrument_requirement: { type: "string", value: "试管" }
  });
  parseButton.listeners.click();
  assert(semantic.innerHTML.includes("样品定时加热"), "heating should select the basic heating operation");
  assert(semantic.innerHTML.includes("目标温度：50"), "heating should preserve target temperature");
  assert(semantic.innerHTML.includes("持续时间：3600"), "heating should convert minutes to seconds");
  assert(!semantic.innerHTML.includes("VD10样品检测"), "a heating experiment must not be mistaken for VD10 testing");

  const mixingText = "将样品使用试管盛装，以300 rpm摇匀2分钟，每份最低25 mL";
  setIntent(mixingText);
  parseButton.listeners.click();
  assert(semantic.innerHTML.includes("样品摇匀混合"), "mixing intent should select the mixing operation");
  assert(semantic.innerHTML.includes("持续时间：120"), "mixing duration should be normalized to seconds");
  assert(semantic.innerHTML.includes("转速：300"), "mixing speed should be preserved");

  const combinedText = "请将这个润滑油样品充分摇匀后取50ml送检，用微波炉加热到100°。";
  setIntent(combinedText);
  dispatchSemantic(combinedText, {
    mixing_requirement: { type: "string", value: "充分摇匀" },
    sample_volume_requirement: { type: "number", value: 50, unit: "mL" },
    instrument_requirement: { type: "string", value: "微波炉" },
    test_item_description: { type: "string", value: "加热到100°" }
  });
  parseButton.listeners.click();
  assert(semantic.innerHTML.includes("样品摇匀混合"), "combined task should include mixing without a fixed duration");
  assert(semantic.innerHTML.includes("样品定时加热"), "combined task should include heating with a degree symbol");
  assert(semantic.innerHTML.includes("目标温度：100"), "bare degree symbol should preserve temperature");
  assert(semantic.innerHTML.includes("completion_condition：sensor_or_human_confirmation"), "unspecified mixing duration should remain a confirmation boundary");
  assert(semantic.innerHTML.indexOf("样品摇匀混合") < semantic.innerHTML.indexOf("样品定时加热"), "processing operations should follow natural-language order");

  const holdingText = "将25 mL样品使用试管盛装，在检录台静置10分钟";
  setIntent(holdingText);
  parseButton.listeners.click();
  assert(semantic.innerHTML.includes("样品定时静置"), "timed holding intent should select the holding operation");
  assert(semantic.innerHTML.includes("持续时间：600"), "holding duration should be normalized to seconds");
  assert(elements.get("physical-flow").innerHTML.includes("仍为占位坐标"), "placeholder locations must block physical readiness");

  const transferText = "请让机械臂将物体从检录台搬运到VD10工位";
  setIntent(transferText);
  parseButton.listeners.click();
  assert(semantic.innerHTML.includes("机械臂物体点到点搬运"), "robot transfer intent should select physical displacement");
  assert(semantic.innerHTML.includes("lab.location.sample_checkin_station"), "transfer should use the check-in location id");
  assert(semantic.innerHTML.includes("lab.location.vd10_station"), "transfer should use the VD10 location id");

  const externalText = "将样品分成2份送到VD10检测";
  setIntent(externalText);
  window.dispatchEvent(new CustomEvent("autolab:semantic-params", {
    detail: {
      msgId: "msg_external-semantic", type: "semantic_params", author: "intent_preprocessor",
      workflowId: "wf_external", index: 1, status: "success", history: [],
      originalText: externalText,
      parameters: { sample_count: { type: "number", value: 2, unit: "份" } },
      clarification: { needed: false, missingFields: [], conflictingFields: [], questions: [] },
      timestamp: Date.now()
    }
  }));
  parseButton.listeners.click();
  assert(elements.get("intent-state").textContent.includes("等待同事B"), "MQTT semantic input must wait for the external planner");
  assert(!semantic.innerHTML.includes("样品定量分装"), "MQTT semantic input must not fall back to local keyword planning");

  window.dispatchEvent(new CustomEvent("autolab:planner-result", {
    detail: {
      msgId: "msg_external-planner", type: "planner_result", author: "planner",
      workflowId: "wf_external", index: 2, status: "success", history: [],
      experimentName: "VD10检测", steps: [], parameters: {}, timestamp: Date.now(),
      operationChain: {
        contractVersion: "1.0.0", planId: "plan_external",
        capabilityLibrary: { id: "autolab.vd10.meta_operations", version: "1.3.0", checksum: "sha256:test" },
        operations: [
          {
            stepId: "external_001", sequence: 1, metaOperationId: "robot.meta.aliquot_sample",
            metaOperationVersion: "1.0.0", arguments: { target_count: 2 }, dependsOn: []
          },
          {
            stepId: "external_002", sequence: 2, metaOperationId: "vd10.meta.sample_test",
            metaOperationVersion: "1.0.0", arguments: { target_device: "vd10" }, dependsOn: ["external_001"]
          }
        ]
      }
    }
  }));
  assert(semantic.innerHTML.includes("样品定量分装"), "external planner operation ids should render local operation cards");
  assert(semantic.innerHTML.indexOf("样品定量分装") < semantic.innerHTML.indexOf("VD10样品检测"), "external planner sequence should be preserved");

  window.dispatchEvent(new CustomEvent("autolab:physical-validation", {
    detail: {
      msgId: "msg_external-physical", type: "physical_validation", author: "physical_validator",
      workflowId: "wf_external", index: 3, status: "success", history: [],
      planId: "plan_external", result: "blocked", timestamp: Date.now(),
      stepResults: [
        { stepId: "external_001", executable: true, checks: ["分装能力已登记"], blockers: [] },
        { stepId: "external_002", executable: false, checks: [], blockers: ["VD10状态未确认"] }
      ]
    }
  }));
  assert(elements.get("physical-flow").innerHTML.includes("VD10状态未确认"), "external physical blockers should be displayed on the matching step");

  console.log("v0.3.0 MQTT preprocessing and planning smoke test passed");
}, 50);

function assert(condition, message) {
  if (!condition) {
    console.error(`FAILED: ${message}`);
    process.exit(1);
  }
}
