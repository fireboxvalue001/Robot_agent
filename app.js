"use strict";

const DATA_PATH = "data/vd10_agent_only_operation_tree.json";
const META_OPERATION_PATH = "data/meta-operations.json";
const SPATIAL_LOCATION_PATH = "data/spatial-locations.json";
const DEFAULT_CHECKIN_LOCATION = "lab.location.sample_checkin_station";
const DEFAULT_VD10_LOCATION = "lab.location.vd10_station";
const FOUNDATION_OPERATION_IDS = new Set([
  "robot.meta.heat_sample",
  "robot.meta.mix_sample",
  "robot.meta.hold_sample",
  "robot.meta.transfer_object"
]);

const CATEGORY_INFO = {
  instrument: { title: "检测仪器元操作", className: "instrument" },
  robot: { title: "机器人元操作", className: "robot" },
  lab: { title: "实验室环境元操作", className: "lab" }
};

const RESERVED_ATOMS = {
  "vd10.test.start": "开始蒸馏测试（受限接口）",
  "vd10.report.export": "导出测试报告（受限接口）",
  "vd10.calibration": "执行仪器校准（受限接口）"
};

let sourceTree = null;
let atomicIndex = new Map();
let metaOperations = [];
let metaIndex = new Map();
let instrumentDefinitions = [];
let metaOperationLibraryInfo = null;
let spatialLocationLibrary = null;
let spatialLocations = [];
let spatialIndex = new Map();
let workflow = [];
let taskId = createId("task");
let lastAnalysis = null;
let latestSemanticMessage = null;
let latestPlannerMessage = null;
let latestPhysicalValidation = null;
let activeExternalPlanId = null;
let latestSemanticSource = { type: "live" };
let semanticResultStale = false;
let localPlanningInProgress = false;
let executionRecords = [];
let executionRun = {
  status: "not_started",
  started_at: null,
  finished_at: null
};

const $ = (id) => document.getElementById(id);

function createId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function initialize() {
  bindStaticEvents();
  try {
    const [treeResponse, metaResponse, spatialResponse] = await Promise.all([
      fetch(DATA_PATH),
      fetch(META_OPERATION_PATH),
      fetch(SPATIAL_LOCATION_PATH)
    ]);
    if (!treeResponse.ok) throw new Error(`能力树读取失败：HTTP ${treeResponse.status}`);
    if (!metaResponse.ok) throw new Error(`元操作库读取失败：HTTP ${metaResponse.status}`);
    if (!spatialResponse.ok) throw new Error(`空间位置库读取失败：HTTP ${spatialResponse.status}`);
    sourceTree = await treeResponse.json();
    const metaOperationLibrary = await metaResponse.json();
    const spatialLocationLibrary = await spatialResponse.json();
    buildAtomicIndex();
    loadMetaOperationLibrary(metaOperationLibrary);
    loadSpatialLocationLibrary(spatialLocationLibrary);
    renderSpatialLocations();
    renderLibrary();
    renderAll();
  } catch (error) {
    $("operation-library").innerHTML =
      `<div class="empty">能力树读取失败，请通过本目录的启动脚本打开。<br>${escapeHtml(error.message)}</div>`;
  }
}

function loadSpatialLocationLibrary(library) {
  spatialLocationLibrary = library;
  spatialLocations = library.locations || [];
  spatialIndex = new Map(spatialLocations.map((location) => [location.id, location]));
}

function renderSpatialLocations() {
  $("spatial-location-count").textContent = `${spatialLocations.length} 项`;
  const building = spatialLocationLibrary?.building || {};
  const coordinateFrame = spatialLocationLibrary?.coordinate_frame || {};
  const buildingSummary = `
    <article class="spatial-building-summary">
      <strong>建筑坐标系</strong>
      <p>${escapeHtml(coordinateFrame.origin_description || "尚未定义原点")}</p>
      <div><span>${escapeHtml(`${building.floor_count || "--"}层建筑`)}</span><span>层高 ${escapeHtml(building.floor_height_m ?? "--")} m · ${building.floor_height_status === "verified" ? "已核验" : "暂定"}</span></div>
    </article>`;
  const locationCards = spatialLocations.map((location) => {
    const pose = location.pose || {};
    const geometry = location.geometry || {};
    const dimensions = [geometry.length_m, geometry.width_m, geometry.height_m]
      .every((value) => value !== undefined)
      ? `尺寸：${geometry.length_m} × ${geometry.width_m} × ${geometry.height_m} m`
      : "";
    const status = location.placeholder ? "暂定位置" :
      (location.status === "verified" ? "已标定" : "用户数据·待标定");
    return `
      <article class="spatial-location-card ${location.placeholder ? "placeholder" : (location.status === "verified" ? "verified" : "pending")}">
        <div class="spatial-location-head"><strong>${escapeHtml(location.name)}</strong><span>${status}</span></div>
        <code>${escapeHtml(location.id)}</code>
        <p>${escapeHtml(`${location.floor} · ${location.room}`)}</p>
        <p>${escapeHtml(location.pose_reference || "位置参考点")}：X ${escapeHtml(pose.x)} / Y ${escapeHtml(pose.y)} / Z ${escapeHtml(pose.z)} m</p>
        ${dimensions ? `<p>${escapeHtml(dimensions)}</p>` : ""}
        <p>姿态：R ${escapeHtml(pose.roll)}° / P ${escapeHtml(pose.pitch)}° / Y ${escapeHtml(pose.yaw)}°</p>
      </article>`;
  }).join("") || '<div class="empty compact-empty">尚未登记空间位置</div>';
  const transportLinks = spatialLocationLibrary?.transport_links || [];
  const transportSummary = transportLinks.map((link) => `
    <article class="spatial-transport-card">
      <div class="spatial-location-head"><strong>${escapeHtml(link.name)}</strong><span>${link.status === "verified" ? "已验证" : "暂定路线"}</span></div>
      <code>${escapeHtml(link.id)}</code>
      <p>${escapeHtml(`${link.from_location_id} → ${link.to_location_id}`)}</p>
      <p>小车经电梯：1楼 → 3楼 · ${escapeHtml(link.execution_policy)}</p>
    </article>`).join("");
  $("spatial-location-list").innerHTML = buildingSummary + locationCards + transportSummary;
}

function loadMetaOperationLibrary(library) {
  metaOperationLibraryInfo = {
    id: library.library_id,
    version: library.schema_version
  };
  instrumentDefinitions = library.instruments || [];
  metaOperations = (library.meta_operations || []).map((operation) => ({
    meta_operation_id: operation.id,
    version: operation.version,
    name: operation.name,
    category: operation.category,
    instrument_id: operation.instrument_id || null,
    description: operation.description,
    status: operation.status,
    inputs: operation.inputs || {},
    outputs: operation.outputs || {},
    precondition_refs: operation.precondition_refs || [],
    input_hint: operation.input_hint || summarizeSchema(operation.inputs),
    output_hint: operation.output_hint || summarizeSchema(operation.outputs),
    execution_policy: operation.execution_policy,
    internal_operations: (operation.operation_tree?.children || []).map((node) => ({
      capability_id: node.node_ref,
      name: node.name,
      execution_policy: node.execution_policy,
      source_type: node.source_type
    })),
    physical_requirements: operation.physical_requirements || [],
    capability_boundary: operation.capability_boundary || {},
    source: operation.source || {}
  }));
  metaIndex = new Map(metaOperations.map((operation) => [operation.meta_operation_id, operation]));
  $("operation-count").textContent = `${metaOperations.length} 项`;
}

function summarizeSchema(schema) {
  return Object.keys(schema?.properties || {}).join("、") || "无额外参数";
}

function buildAtomicIndex() {
  (sourceTree.capability_tree || []).forEach((category) => {
    (category.capabilities || []).forEach((capability) => {
      atomicIndex.set(capability.capability_id, capability);
    });
  });
  Object.entries(RESERVED_ATOMS).forEach(([id, name]) => {
    atomicIndex.set(id, {
      capability_id: id,
      name,
      execution_policy: "interface_only",
      risk_level: "restricted"
    });
  });
}

function atom(id, fallbackName) {
  const source = atomicIndex.get(id);
  return {
    capability_id: id,
    name: source?.name || fallbackName || id,
    execution_policy: source?.execution_policy || "demo_only",
    risk_level: source?.risk_level || "unknown"
  };
}

function buildLegacyMetaOperationLibrary() {
  metaOperations = [
    {
      meta_operation_id: "vd10.meta.sample_test",
      name: "VD10 样品检测",
      category: "instrument",
      description: "完成一次 VD10 样品检测所需的完整仪器操作。",
      input_hint: "待检测样品、样品编号、操作员",
      output_hint: "VD10 检测任务与检测结果",
      execution_policy: "requires_physical_confirmation",
      internal_operations: [
        atom("vd10.menu.enter_test"),
        atom("vd10.test.fill_sample_id"),
        atom("vd10.test.select_operator"),
        atom("vd10.test.read_form_state"),
        atom("vd10.test.start")
      ],
      physical_requirements: ["样品已放置到仪器", "仪器处于可检测状态", "开始测试需下游确认"]
    },
    {
      meta_operation_id: "vd10.meta.query_test_results",
      name: "VD10 检测结果查询",
      category: "instrument",
      description: "进入结果数据库，检索并打开目标检测结果。",
      input_hint: "检索条件或样品编号",
      output_hint: "结构化检测结果",
      execution_policy: "agent_allowed_with_precheck",
      internal_operations: [
        atom("vd10.menu.enter_database"),
        atom("vd10.database.search"),
        atom("vd10.database.open_result"),
        atom("vd10.database.switch_result_view")
      ],
      physical_requirements: []
    },
    {
      meta_operation_id: "vd10.meta.inspect_quality_status",
      name: "VD10 质量状态检查",
      category: "instrument",
      description: "进入质量状态页面并读取当前质量控制状态。",
      input_hint: "VD10 当前页面与运行状态",
      output_hint: "质量状态信息",
      execution_policy: "agent_allowed_with_precheck",
      internal_operations: [
        atom("vd10.menu.enter_quality"),
        atom("vd10.quality.open_status"),
        atom("vd10.quality.read_status")
      ],
      physical_requirements: []
    },
    {
      meta_operation_id: "vd10.meta.safe_exit",
      name: "VD10 安全退出",
      category: "instrument",
      description: "确认测试未运行后安全退出 VD10 应用。",
      input_hint: "测试运行状态",
      output_hint: "VD10 应用已退出",
      execution_policy: "agent_allowed_with_precheck",
      internal_operations: [atom("vd10.app.exit")],
      physical_requirements: []
    },
    {
      meta_operation_id: "robot.meta.split_and_deliver",
      name: "样品分装并送样",
      category: "robot",
      description: "识别样品，按要求分装并搬运到一个或多个仪器位置。",
      input_hint: "样品位置、分装数量、单份体积、目标仪器",
      output_hint: "样品按要求放置到目标仪器",
      execution_policy: "requires_physical_confirmation",
      internal_operations: [
        atom("robot.atom.identify_sample", "识别并定位样品"),
        atom("robot.atom.pick_sample", "抓取样品"),
        atom("robot.atom.split_sample", "按体积分装样品"),
        atom("robot.atom.transfer_sample", "规划路径并搬运样品"),
        atom("robot.atom.place_sample", "将样品放置到仪器工位")
      ],
      physical_requirements: ["确认样品容器和夹具", "确认分装位置", "确认目标仪器工位与运动路径"]
    },
    {
      meta_operation_id: "robot.meta.prepare_sample_batch",
      name: "样品定量分装",
      category: "robot",
      description: "识别样品并按照指定数量和体积完成批量分装。",
      input_hint: "样品位置、分装数量、单份体积",
      output_hint: "多个已定量分装的样品",
      execution_policy: "requires_physical_confirmation",
      internal_operations: [
        atom("robot.atom.identify_sample", "识别并定位样品"),
        atom("robot.atom.pick_sample", "抓取样品"),
        atom("robot.atom.split_sample", "按体积分装样品"),
        atom("robot.atom.place_containers", "将分装样品放入周转容器")
      ],
      physical_requirements: ["确认样品容器和夹具", "确认分装位置与周转容器"]
    },
    {
      meta_operation_id: "robot.meta.transfer_sample",
      name: "样品批量搬运",
      category: "robot",
      description: "将指定样品从起始位置搬运到目标位置。",
      input_hint: "一组样品、起始位置、目标仪器位置",
      output_hint: "各样品到达对应仪器工位",
      execution_policy: "requires_physical_confirmation",
      internal_operations: [
        atom("robot.atom.locate_sample", "定位样品"),
        atom("robot.atom.pick_sample", "抓取样品"),
        atom("robot.atom.move_to_target", "移动到目标位置"),
        atom("robot.atom.place_sample", "放置样品")
      ],
      physical_requirements: ["确认抓取姿态", "确认目标位置和运动路径"]
    },
    {
      meta_operation_id: "robot.meta.shake_sample",
      name: "样品震荡处理",
      category: "robot",
      description: "按照实验要求完成样品震荡和复位。",
      input_hint: "样品、震荡强度、持续时间",
      output_hint: "完成震荡处理的样品",
      execution_policy: "requires_physical_confirmation",
      internal_operations: [
        atom("robot.atom.load_shaker", "将样品放入震荡装置"),
        atom("robot.atom.set_shaking", "设置震荡参数"),
        atom("robot.atom.unload_shaker", "取出并复位样品")
      ],
      physical_requirements: ["确认样品固定状态", "确认震荡装置可用"]
    },
    {
      meta_operation_id: "lab.meta.cross_zone_transport",
      name: "实验室跨区域转运",
      category: "lab",
      description: "完成门禁联动和实验室区域之间的样品转运。",
      input_hint: "起始区域、目标区域、门禁权限",
      output_hint: "样品或机器人到达目标区域",
      execution_policy: "requires_environment_confirmation",
      internal_operations: [
        atom("lab.atom.request_access", "请求门禁权限"),
        atom("lab.atom.open_door", "打开门禁"),
        atom("lab.atom.move_between_zones", "跨区域移动"),
        atom("lab.atom.close_door", "关闭门禁")
      ],
      physical_requirements: ["确认门禁状态", "确认通道可用", "确认区域权限"]
    }
  ];
  metaIndex = new Map(metaOperations.map((operation) => [operation.meta_operation_id, operation]));
  $("operation-count").textContent = `${metaOperations.length} 项`;
}

function bindStaticEvents() {
  $("parse-intent").addEventListener("click", generateWorkflowFromPreprocessing);
  $("intent-input").addEventListener("input", () => {
    if (!latestSemanticMessage) return;
    semanticResultStale = $("intent-input").value.trim() !==
      String(latestSemanticMessage.originalText || "").trim();
    if (semanticResultStale) {
      workflow = [];
      lastAnalysis = null;
      resetExecutionState();
    }
    renderAll();
  });
  $("intent-input").addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter") generateWorkflowFromPreprocessing();
  });
  $("clear-flow").addEventListener("click", () => {
    workflow = [];
    taskId = createId("task");
    lastAnalysis = null;
    resetExecutionState();
    renderAll();
  });
  $("simulate-execution").addEventListener("click", simulateExecution);
  $("library-search").addEventListener("input", renderLibrary);
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });
  ["semantic-flow", "physical-flow"].forEach((id) => {
    $(id).addEventListener("dragover", (event) => event.preventDefault());
    $(id).addEventListener("drop", (event) => {
      event.preventDefault();
      const metaId = event.dataTransfer.getData("text/meta-operation");
      if (metaIndex.has(metaId)) addMetaOperation(metaId, { source: "从元操作能力库拖入" });
    });
  });
  window.addEventListener("autolab:semantic-params", (event) => {
    receiveSemanticParameters(event.detail, { type: "live" });
  });
  window.addEventListener("autolab:planner-result", (event) => {
    receivePlannerResult(event.detail, "同事B通过MQTT返回");
  });
  window.addEventListener("autolab:physical-validation", (event) => {
    receivePhysicalValidation(event.detail);
  });
  window.addEventListener("autolab:semantic-history-selected", (event) => {
    const detail = event.detail || {};
    if (!detail.message?.originalText) {
      showToast("历史语义记录缺少原始文字，无法载入");
      return;
    }
    $("intent-input").value = detail.message.originalText;
    receiveSemanticParameters(detail.message, {
      type: "history",
      workflow_id: detail.history?.workflowId || detail.message.workflowId || null,
      msg_id: detail.history?.msgId || detail.message.msgId || null,
      recorded_at: detail.history?.recorded_at || null
    });
    generateWorkflowFromPreprocessing();
  });
}

function receiveSemanticParameters(message, source = { type: "live" }) {
  latestSemanticMessage = message && typeof message === "object" ? message : null;
  latestSemanticSource = source;
  semanticResultStale = false;
  latestPlannerMessage = null;
  latestPhysicalValidation = null;
  activeExternalPlanId = null;
  workflow = [];
  taskId = createId("task");
  lastAnalysis = null;
  resetExecutionState();
  renderAll();

  if (!latestSemanticMessage) showToast("收到的语义预处理结果格式无效");
  else if (latestSemanticMessage.status === "failed") showToast("语义预处理失败，请查看 MQTT 返回结果");
  else if (latestSemanticMessage.clarification?.needed) showToast("预处理结果仍缺少必要字段，请补充后重新发送");
  else if (source.type === "local") showToast("已从自然语言提取本地预处理字段");
  else showToast("预处理字段已载入，可以生成实验流程");
}

function receivePlannerResult(message, sourceLabel = "外部任务编排接口返回") {
  latestPlannerMessage = message && typeof message === "object" ? message : null;
  latestPhysicalValidation = null;
  activeExternalPlanId = null;
  workflow = [];
  resetExecutionState();
  if (!latestPlannerMessage || latestPlannerMessage.status === "failed") {
    const warnings = Array.isArray(latestPlannerMessage?.warnings) ? latestPlannerMessage.warnings : [];
    lastAnalysis = { matched: false, message: warnings.join("；") || "任务编排失败。", factors: [] };
    renderAll();
    showToast(lastAnalysis.message);
    return;
  }

  const chain = latestPlannerMessage.operationChain;
  const operations = Array.isArray(chain?.operations)
    ? [...chain.operations].sort((left, right) => left.sequence - right.sequence)
    : [];
  const errors = [];
  if (latestSemanticMessage?.workflowId && latestPlannerMessage.workflowId !== latestSemanticMessage.workflowId) {
    errors.push("规划结果与当前预处理结果的 workflowId 不一致");
  }
  const knownStepIds = new Set(operations.map((operation) => operation.stepId));
  if (chain?.capabilityLibrary?.id !== metaOperationLibraryInfo?.id) {
    errors.push(`能力库ID不匹配：${chain?.capabilityLibrary?.id || "未提供"}`);
  }
  if (chain?.capabilityLibrary?.version !== metaOperationLibraryInfo?.version) {
    errors.push(`能力库版本不匹配：需要 ${metaOperationLibraryInfo?.version}，收到 ${chain?.capabilityLibrary?.version || "未提供"}`);
  }
  operations.forEach((planned) => {
    const operation = metaIndex.get(planned.metaOperationId);
    if (!operation) {
      errors.push(`未知元操作ID：${planned.metaOperationId}`);
      return;
    }
    if (operation.version !== planned.metaOperationVersion) {
      errors.push(`${planned.metaOperationId} 版本不匹配：需要 ${operation.version}，收到 ${planned.metaOperationVersion}`);
      return;
    }
    const unknownDependency = (planned.dependsOn || []).find((dependency) => !knownStepIds.has(dependency));
    if (unknownDependency) {
      errors.push(`${planned.stepId} 引用了未知依赖：${unknownDependency}`);
      return;
    }
    workflow.push({
      id: planned.stepId,
      operation,
      params: planned.arguments || {},
      source: sourceLabel,
      evidence: [`planId: ${chain.planId}`],
      dependsOn: planned.dependsOn || []
    });
  });

  if (errors.length || workflow.length !== operations.length || !workflow.length) {
    workflow = [];
    lastAnalysis = { matched: false, message: errors.join("；") || "外部操作链为空。", factors: [] };
    renderAll();
    showToast("外部任务链校验失败");
    return;
  }
  activeExternalPlanId = chain.planId;
  taskId = chain.planId;
  lastAnalysis = {
    matched: true,
    message: `已载入编排接口生成的 ${workflow.length} 个元操作。`,
    factors: [`计划：${chain.planId}`, `来源：${sourceLabel}`, `能力库版本：${chain.capabilityLibrary.version}`]
  };
  renderAll();
  showToast(lastAnalysis.message);
}

function receivePhysicalValidation(message) {
  if (!message || message.status === "failed") {
    latestPhysicalValidation = message || null;
    renderAll();
    showToast("外部物理可执行确认失败");
    return;
  }
  if (!activeExternalPlanId || message.planId !== activeExternalPlanId ||
      (latestPlannerMessage?.workflowId && message.workflowId !== latestPlannerMessage.workflowId)) {
    showToast("物理校验结果与当前计划不匹配，已忽略");
    return;
  }
  latestPhysicalValidation = message;
  renderAll();
  showToast(message.result === "executable" ? "物理可执行确认通过" : "已收到物理校验结论");
}

function buildLocalPreprocessing(text) {
  const parameters = {
    test_item_description: { type: "string", value: text }
  };
  const countMap = { 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
  const countMatch = text.match(/(\d+|一|二|两|三|四|五|六|七|八|九|十)\s*(?:份|个|台)/);
  if (countMatch) {
    parameters.sample_count = {
      type: "number",
      value: Number(countMatch[1]) || countMap[countMatch[1]],
      unit: "份"
    };
  }

  const volumeMatch = text.match(/(?:每份|最低(?:送检)?(?:体积)?|至少)?\s*(\d+(?:\.\d+)?)\s*(mL|ml|毫升)/i);
  if (volumeMatch) {
    parameters.sample_volume_requirement = {
      type: "number",
      value: Number(volumeMatch[1]),
      unit: "mL"
    };
  }

  if (/静置|无需(?:摇匀|混匀|震荡|振荡)|不需要(?:摇匀|混匀|震荡|振荡)/.test(text)) {
    parameters.mixing_requirement = { type: "string", value: "静置" };
  } else {
    const mixingMatch = text.match(/(摇匀|混匀|震荡|振荡)/);
    if (mixingMatch) parameters.mixing_requirement = { type: "string", value: mixingMatch[1] };
  }

  const instrumentMatch = text.match(/(?:使用|采用|携带|配套|装入|用|盛装(?:于|到)?)[^，。；]*(试管|烧杯|样品瓶|离心管|加热器|加热设备|摇床|混匀仪|微波炉)/);
  if (instrumentMatch) {
    parameters.instrument_requirement = { type: "string", value: instrumentMatch[1] };
  }
  if (/VD10/i.test(text)) parameters.target_device = { type: "string", value: "VD10" };

  const temperatureMatch = text.match(/(?:温度(?:为|设为|设置为|到|至)?|加热(?:到|至))\s*(\d+(?:\.\d+)?)\s*(?:°C|℃|度|°)/i);
  if (temperatureMatch) {
    parameters.temperature_c = { type: "number", value: Number(temperatureMatch[1]), unit: "°C" };
  }
  const processDurationMatch = text.match(/(?:持续|保持)\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时)/);
  if (processDurationMatch) {
    const seconds = durationToSeconds(processDurationMatch[1], processDurationMatch[2]);
    parameters.process_duration_seconds = { type: "number", value: seconds, unit: "s" };
  }
  const holdDurationMatch = text.match(/静置(?:时间为|持续|保持)?\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时)/);
  if (holdDurationMatch) {
    parameters.hold_duration_seconds = {
      type: "number",
      value: durationToSeconds(holdDurationMatch[1], holdDurationMatch[2]),
      unit: "s"
    };
  }
  const mixingDurationMatch = text.match(/(?:摇匀|混匀|震荡|振荡)(?:时间为|持续|保持)?\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时)/);
  if (mixingDurationMatch) {
    parameters.mixing_duration_seconds = {
      type: "number",
      value: durationToSeconds(mixingDurationMatch[1], mixingDurationMatch[2]),
      unit: "s"
    };
  }
  const speedMatch = text.match(/(\d+(?:\.\d+)?)\s*(?:rpm|转每分钟|转\/分)/i);
  if (speedMatch) parameters.mixing_speed_rpm = { type: "number", value: Number(speedMatch[1]), unit: "rpm" };

  const floorMatch = text.match(/(?:送到|送至|搬到|运到|前往|到)\s*(\d+|一|二|两|三|四|五|六|七|八|九|十)\s*(?:楼|层)/);
  if (floorMatch) {
    parameters.destination_floor = {
      type: "string",
      value: `${Number(floorMatch[1]) || countMap[floorMatch[1]] || floorMatch[1]}楼`
    };
  }

  const isSampleTask = /送检|检测|测试|分析/.test(text) &&
    !(/查询|查看|读取|检索/.test(text) && /结果|报告|数据/.test(text));
  const requiredFields = isSampleTask
    ? ["mixing_requirement", "sample_volume_requirement", "instrument_requirement"]
    : [];
  const missingFields = requiredFields.filter((key) => !parameters[key]);
  const questionMap = {
    mixing_requirement: "请补充样品需要静置、摇匀、混匀还是震荡。",
    sample_volume_requirement: "请补充每份或最低送检样品体积。",
    instrument_requirement: "请补充样品使用的容器或配套仪器，例如试管。"
  };
  return {
    type: "local_preprocessing",
    status: "success",
    originalText: text,
    parameters,
    clarification: {
      needed: missingFields.length > 0,
      missingFields,
      questions: missingFields.map((key) => questionMap[key])
    },
    timestamp: Date.now()
  };
}

function durationToSeconds(value, unit) {
  const multipliers = { 秒: 1, 分钟: 60, 小时: 3600 };
  return Math.round(Number(value) * (multipliers[unit] || 1));
}

function semanticValue(...keys) {
  const parameters = latestSemanticMessage?.parameters || {};
  for (const key of keys) {
    const field = parameters[key];
    if (field === undefined || field === null) continue;
    if (typeof field === "object" && Object.hasOwn(field, "value")) return field.value;
    return field;
  }
  return null;
}

function semanticFieldText(key, field) {
  const labels = {
    test_item_description: "检测项目",
    mixing_requirement: "样品处理要求",
    sample_volume_requirement: "最低样品体积",
    instrument_requirement: "配套仪器",
    sample_count: "样品数量",
    target_count: "目标数量",
    destination_floor: "目标楼层",
    target_device: "目标设备",
    temperature_c: "目标温度",
    process_duration_seconds: "处理时长",
    hold_duration_seconds: "静置时长",
    mixing_duration_seconds: "混匀时长",
    mixing_speed_rpm: "混匀转速"
  };
  const value = typeof field === "object" && field !== null && Object.hasOwn(field, "value")
    ? field.value
    : field;
  const unit = typeof field === "object" && field?.unit ? ` ${field.unit}` : "";
  return `${labels[key] || key}：${value ?? "--"}${unit}`;
}

function librarySupports(pattern) {
  return metaOperations.some((operation) => pattern.test(
    `${operation.name} ${operation.description} ${operation.meta_operation_id}`
  ));
}

function checkCapabilityCoverage(text) {
  const reasons = [];
  const description = String(semanticValue("test_item_description") || "");
  const mixing = String(semanticValue("mixing_requirement") || "");
  const planningText = `${text} ${description}`;

  if (/加热|升温|恒温|温度\s*(?:为|到|至)?\s*\d+/i.test(planningText) &&
      !librarySupports(/加热|升温|恒温|温控/)) {
    reasons.push("元操作能力库中没有加热或温控实验能力");
  }
  if (/摇匀|混匀|震荡|振荡/.test(mixing) && !librarySupports(/摇匀|混匀|震荡|振荡/)) {
    reasons.push(`元操作能力库无法满足样品处理要求：${mixing}`);
  }
  if (/加热|升温|恒温/.test(planningText)) {
    if (semanticValue("temperature_c") === null && !/\d+(?:\.\d+)?\s*(?:°C|℃|度|°)/i.test(planningText)) {
      reasons.push("加热操作缺少目标温度");
    }
  }
  const rawVolume = semanticValue("sample_volume_requirement", "sample_volume", "volume_each");
  const volume = Number(rawVolume);
  if (rawVolume !== null && Number.isFinite(volume) && volume <= 0) reasons.push("样品体积必须大于 0");
  return reasons;
}

async function generateWorkflowFromPreprocessing() {
  const text = $("intent-input").value.trim();
  if (!text) {
    lastAnalysis = { matched: false, message: "没有输入总体意图。", factors: [] };
    renderAll();
    showToast("请输入总体操作意图");
    return;
  }

  const isMqttSemanticResult = latestSemanticSource.type === "live" &&
    typeof latestSemanticMessage?.workflowId === "string" &&
    typeof latestSemanticMessage?.msgId === "string";
  if (isMqttSemanticResult) {
    if (latestPlannerMessage) {
      receivePlannerResult(latestPlannerMessage, "同事B通过MQTT返回");
    } else {
      lastAnalysis = { matched: false, message: "预处理已完成，正在等待同事B返回元操作链。", factors: [] };
      renderAll();
      showToast(lastAnalysis.message);
    }
    return;
  }
  if (localPlanningInProgress) return;

  localPlanningInProgress = true;
  $("parse-intent").disabled = true;
  lastAnalysis = { matched: false, message: "正在通过自然语言编排接口生成流程...", factors: [] };
  renderAll();
  try {
    const response = await fetch("/api/v1/planning/from-text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    if (result.preprocessing) {
      receiveSemanticParameters(result.preprocessing, { type: "local_api" });
    }
    receivePlannerResult(result, "本地自然语言编排接口");
  } catch (error) {
    showToast(`后端编排接口不可用，已切换到前端降级规则：${error.message || error}`);
    generateWorkflowLocally();
  } finally {
    localPlanningInProgress = false;
    $("parse-intent").disabled = false;
  }
}

function generateWorkflowLocally() {
  const text = $("intent-input").value.trim();
  workflow = [];
  resetExecutionState();

  if (!text) {
    lastAnalysis = { matched: false, message: "没有输入总体意图。", factors: [] };
    renderAll();
    showToast("请输入总体操作意图");
    return;
  }

  if (!latestSemanticMessage || semanticResultStale ||
      text !== String(latestSemanticMessage.originalText || "").trim()) {
    receiveSemanticParameters(buildLocalPreprocessing(text), { type: "local" });
  }
  if (latestSemanticMessage.status === "failed") {
    lastAnalysis = { matched: false, message: "上游语义预处理失败。", factors: [] };
    renderAll();
    showToast(lastAnalysis.message);
    return;
  }
  if (latestSemanticMessage.clarification?.needed) {
    const questions = latestSemanticMessage.clarification.questions || [];
    lastAnalysis = {
      matched: false,
      message: questions.length ? questions.join("；") : "预处理字段不完整，暂不能生成流程。",
      factors: []
    };
    renderAll();
    showToast("预处理字段不完整，请先补充信息");
    return;
  }

  const coverageIssues = checkCapabilityCoverage(text);
  if (coverageIssues.length) {
    lastAnalysis = { matched: false, message: coverageIssues.join("；"), factors: [] };
    renderAll();
    showToast(`任务不可编排：${coverageIssues[0]}`);
    return;
  }

  const parameterText = Object.values(latestSemanticMessage.parameters || {}).map((field) => {
    return typeof field === "object" && field !== null && Object.hasOwn(field, "value")
      ? `${field.value}${field.unit || ""}`
      : String(field ?? "");
  }).join(" ");
  parseIntent(`${text} ${parameterText}`, latestSemanticMessage);
}

function renderLibrary() {
  if (!metaOperations.length) return;
  const query = $("library-search").value.trim().toLowerCase();
  const categorySections = Object.entries(CATEGORY_INFO).map(([category, info]) => {
    const items = metaOperations.filter((operation) => {
      const text = `${operation.name} ${operation.meta_operation_id} ${operation.description}`.toLowerCase();
      return operation.category === category && (!query || text.includes(query));
    }).sort((left, right) => {
      const leftPriority = FOUNDATION_OPERATION_IDS.has(left.meta_operation_id) ? 0 : 1;
      const rightPriority = FOUNDATION_OPERATION_IDS.has(right.meta_operation_id) ? 0 : 1;
      return leftPriority - rightPriority;
    });
    if (!items.length) return "";
    const content = category === "instrument"
      ? renderInstrumentGroups(items, Boolean(query))
      : `<ul class="op-list">${items.map(renderMetaOperation).join("")}</ul>`;
    return `
      <details class="op-group ${info.className}" ${query ? "open" : ""}>
        <summary class="op-group-title"><span>${info.title}</span><span>${items.length} 项</span></summary>
        ${content}
      </details>`;
  }).join("");
  $("operation-library").innerHTML = categorySections || '<div class="empty">没有匹配的元操作</div>';

  document.querySelectorAll(".op-card").forEach((card) => {
    card.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/meta-operation", card.dataset.id);
    });
    card.querySelector(".op-add").addEventListener("click", () => addMetaOperation(card.dataset.id));
  });
}

function renderInstrumentGroups(items, expandMatches) {
  const knownInstrumentIds = new Set(instrumentDefinitions.map((instrument) => instrument.id));
  const groups = [...instrumentDefinitions];
  if (items.some((operation) => !knownInstrumentIds.has(operation.instrument_id))) {
    groups.push({ id: "unassigned", name: "待绑定仪器", description: "尚未指定所属仪器的元操作。" });
  }
  return `<div class="instrument-menu">${groups.map((instrument) => {
    const operations = items.filter((operation) =>
      operation.instrument_id === instrument.id ||
      (instrument.id === "unassigned" && !knownInstrumentIds.has(operation.instrument_id))
    );
    if (!operations.length) return "";
    return `
      <details class="instrument-group" ${expandMatches ? "open" : ""}>
        <summary><span>${escapeHtml(instrument.name)}</span><span>${operations.length} 项</span></summary>
        ${instrument.description ? `<p>${escapeHtml(instrument.description)}</p>` : ""}
        <ul class="op-list">${operations.map(renderMetaOperation).join("")}</ul>
      </details>`;
  }).join("")}</div>`;
}

function renderMetaOperation(operation) {
  const statusLabels = {
    verified: "已验证",
    pending_verification: "待实机验证",
    draft: "草案",
    interface_only: "仅保留接口",
    disabled: "已停用"
  };
  return `
    <li class="op-card" draggable="true" data-id="${escapeHtml(operation.meta_operation_id)}">
      <div class="op-info">
        <div class="op-name-row"><strong>${escapeHtml(operation.name)}</strong><span class="op-status status-${escapeHtml(operation.status)}">${escapeHtml(statusLabels[operation.status] || operation.status)}</span></div>
        <details class="operation-details">
          <summary>查看说明与内部操作树</summary>
          <p>${escapeHtml(operation.description)}</p>
          <p><b>输入：</b>${escapeHtml(operation.input_hint)}</p>
          <p><b>输出：</b>${escapeHtml(operation.output_hint)}</p>
          <div class="operation-tree">
            <span>内部操作树 · ${operation.internal_operations.length} 个小操作</span>
          <ol>${operation.internal_operations.map((step) =>
            `<li>${escapeHtml(step.name)}<code>${escapeHtml(step.capability_id)}</code></li>`
          ).join("")}</ol>
          </div>
        </details>
      </div>
      <button class="op-add" type="button" title="加入任务流程">+</button>
    </li>`;
}

function appendMetaOperation(metaId, options = {}) {
  const operation = metaIndex.get(metaId);
  if (!operation) return false;
  workflow.push({
    id: createId("step"),
    operation,
    params: options.params || {},
    source: options.source || "从元操作能力库加入",
    evidence: options.evidence || [operation.name]
  });
  return true;
}

function addMetaOperation(metaId, options = {}) {
  if (!appendMetaOperation(metaId, options)) return;
  resetExecutionState();
  renderAll();
}

function appendFloorTransport(destinationFloor, targetCount, timing) {
  appendMetaOperation("lab.meta.cross_zone_transport", {
    source: "总体意图匹配",
    evidence: [
      destinationFloor ? `识别到跨楼层目标：${destinationFloor}` : "识别到跨楼层转运要求",
      timing === "after_test" ? "识别到时序要求：检测完成后转运" : "识别到时序要求：检测前转运"
    ],
    params: {
      destination_floor: destinationFloor,
      sample_count: targetCount,
      timing,
      transport_link_id: destinationFloor === "3楼"
        ? "lab.transport.elevator_floor1_to_floor3"
        : null,
      source_location_id: destinationFloor === "3楼"
        ? "lab.location.elevator_lobby_floor1"
        : null,
      target_location_id: destinationFloor === "3楼"
        ? "lab.location.elevator_lobby_floor3"
        : null
    }
  });
}

function appendInstrumentDelivery(targetCount, destinationFloor) {
  appendMetaOperation("lab.meta.transfer_sample_by_agv", {
    source: "总体意图匹配",
    evidence: ["需要通过AGV将样品送到目标仪器工位"],
    params: {
      target_count: targetCount,
      destination_floor: destinationFloor,
      target_type: "instrument",
      source_station: DEFAULT_CHECKIN_LOCATION,
      target_station: DEFAULT_VD10_LOCATION
    }
  });
}

function parseIntent(rawText, semanticMessage = null) {
  const text = rawText.trim();
  workflow = [];
  taskId = createId("task");
  resetExecutionState();

  if (!text) {
    lastAnalysis = { matched: false, message: "没有输入总体意图。", factors: [] };
    renderAll();
    showToast("请输入总体操作意图");
    return;
  }

  const countMatch = text.match(/(\d+|一|二|两|三|四|五|六|七|八|九|十)\s*(?:份|个|台)/);
  const countMap = { 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
  const semanticCount = Number(semanticValue("sample_count", "target_count", "sampleCount", "targetCount"));
  const targetCount = Number.isFinite(semanticCount) && semanticCount > 0
    ? semanticCount
    : (countMatch ? (Number(countMatch[1]) || countMap[countMatch[1]] || 1) : 1);
  const volumeMatch = text.match(/(\d+(?:\.\d+)?)\s*(ml|毫升)/i);
  const semanticVolume = semanticValue(
    "volume_each", "sample_volume", "sample_volume_requirement", "sampleVolume"
  );
  const semanticVolumeField = semanticMessage?.parameters?.sample_volume_requirement ||
    semanticMessage?.parameters?.sample_volume || semanticMessage?.parameters?.volume_each;
  const semanticVolumeUnit = semanticVolumeField?.unit || "ml";
  const volumeEach = semanticVolume !== null
    ? `${semanticVolume}${semanticVolumeUnit}`
    : (volumeMatch ? `${volumeMatch[1]}ml` : null);
  const floorMatch = text.match(/(?:送到|送至|搬到|运到|前往|到)\s*(\d+|一|二|两|三|四|五|六|七|八|九|十)\s*(?:楼|层)/);
  const semanticFloor = semanticValue("destination_floor", "target_floor", "destinationFloor");
  const inferredVd10Floor = /VD10/i.test(text) && /送到|送入|搬运|转运|放到|放入|送检/.test(text)
    ? spatialIndex.get(DEFAULT_VD10_LOCATION)?.floor
    : null;
  const destinationFloor = semanticFloor
    ? String(semanticFloor).replace(/(?:楼|层)?$/, "楼")
    : (floorMatch
      ? `${Number(floorMatch[1]) || countMap[floorMatch[1]] || floorMatch[1]}楼`
      : (inferredVd10Floor || (/楼上/.test(text) ? "楼上" : (/楼下/.test(text) ? "楼下" : null))));
  const factors = [];

  const mentionsSample = /样品|试样|样本/.test(text) || semanticVolume !== null;
  const mentionsSplit = /分成|分为|分装|等分/.test(text);
  const mentionsDeliver = /送到|送入|搬运|转运|放到|放入/.test(text);
  const mentionsVD10 = /vd10/i.test(text);
  const mentionsTest = /检测|测试|分析/.test(text);
  const mentionsHeating = /加热|升温|恒温/.test(text);
  const mixingRequirement = String(semanticValue("mixing_requirement") || "");
  const mentionsMixing = /摇匀|混匀|震荡|振荡/.test(mixingRequirement);
  const holdDurationSeconds = Number(semanticValue("hold_duration_seconds"));
  const textDurationMatch = text.match(/(?:持续|保持)\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时)/);
  const semanticProcessDuration = semanticValue("process_duration_seconds", "heating_duration_seconds");
  const processDurationSeconds = semanticProcessDuration !== null
    ? Number(semanticProcessDuration)
    : (textDurationMatch ? durationToSeconds(textDurationMatch[1], textDurationMatch[2]) : NaN);
  const semanticMixingDuration = semanticValue("mixing_duration_seconds", "process_duration_seconds");
  const mixingDurationSeconds = semanticMixingDuration !== null
    ? Number(semanticMixingDuration)
    : processDurationSeconds;
  const textTemperatureMatch = text.match(/(?:温度(?:为|设为|设置为|到|至)?|加热(?:到|至))\s*(\d+(?:\.\d+)?)\s*(?:°C|℃|度|°)/i);
  const semanticTemperature = semanticValue("temperature_c");
  const temperatureC = semanticTemperature !== null
    ? Number(semanticTemperature)
    : (textTemperatureMatch ? Number(textTemperatureMatch[1]) : NaN);
  const mixingSpeedRpm = Number(semanticValue("mixing_speed_rpm", "speed_rpm"));
  const mentionsRobotTransfer = /机械臂[^，。；]*(?:搬运|移动|移送)|(?:搬运|移动|移送)[^，。；]*机械臂/.test(text);
  const mentionsFloorTransfer = Boolean(destinationFloor) || /跨楼层|上下楼/.test(text);
  const floorAfterTest = mentionsFloorTransfer && mentionsTest &&
    /(?:最后|最终)[^，。]*(?:楼|层)|(?:检测|测试|实验)(?:完成)?(?:后|之后|以后)[^，。]*(?:楼|层)/.test(text);
  const mentionsResult = /查询|查看|读取|检索/.test(text) && /结果|报告|数据/.test(text);
  const mentionsQuality = /质量状态|质量控制|质控/.test(text);
  const mentionsExit = /退出|关闭应用/.test(text);

  if (mentionsSample) factors.push("识别到样品对象");
  if (mentionsSplit) factors.push("识别到分装要求");
  if (mentionsDeliver) factors.push("识别到搬运或送样要求");
  if (mentionsTest) factors.push("识别到仪器检测目标");
  if (mentionsHeating) factors.push("识别到定时加热要求");
  if (mentionsMixing) factors.push(`识别到样品处理要求：${mixingRequirement}`);
  if (Number.isFinite(holdDurationSeconds) && holdDurationSeconds > 0) factors.push(`识别到静置时长：${holdDurationSeconds}秒`);
  if (mentionsRobotTransfer) factors.push("识别到机械臂点到点搬运要求");
  if (targetCount > 1) factors.push(`识别到数量：${targetCount}`);
  if (volumeEach) factors.push(`识别到单份体积：${volumeEach}`);
  if (destinationFloor) factors.push(`识别到目标楼层：${destinationFloor}`);
  if (floorAfterTest) factors.push("识别到时序：检测完成后转运");

  if (mentionsSample && mentionsSplit) {
    appendMetaOperation("robot.meta.aliquot_sample", {
      source: "总体意图匹配",
      evidence: factors.filter((item) => /样品|分装|数量|体积/.test(item)),
      params: {
        target_count: targetCount,
        volume_each: volumeEach,
        source_location_id: DEFAULT_CHECKIN_LOCATION
      }
    });
  }

  const processingStartIndex = workflow.length;

  if (mentionsHeating) {
    appendMetaOperation("robot.meta.heat_sample", {
      source: "机器人样品预处理匹配",
      evidence: factors.filter((item) => /加热|体积/.test(item)),
      params: {
        sample_id: "sample_pending_identification",
        temperature_c: Number.isFinite(temperatureC) ? temperatureC : null,
        duration_seconds: Number.isFinite(processDurationSeconds) ? processDurationSeconds : null,
        completion_condition: Number.isFinite(processDurationSeconds)
          ? "duration_elapsed"
          : "target_temperature_reached",
        heater_id: "heater_pending_binding",
        container_type: semanticValue("instrument_requirement")
      }
    });
  }

  if (mentionsMixing) {
    appendMetaOperation("robot.meta.mix_sample", {
      source: "机器人样品预处理匹配",
      evidence: [`样品处理要求：${mixingRequirement}`],
      params: {
        sample_id: "sample_pending_identification",
        method: /震荡|振荡/.test(mixingRequirement) ? "vortex" : (/混匀/.test(mixingRequirement) ? "mix" : "shake"),
        duration_seconds: Number.isFinite(mixingDurationSeconds) ? mixingDurationSeconds : null,
        completion_condition: Number.isFinite(mixingDurationSeconds)
          ? "duration_elapsed"
          : "sensor_or_human_confirmation",
        speed_rpm: Number.isFinite(mixingSpeedRpm) ? mixingSpeedRpm : null,
        mixer_id: "mixer_pending_binding"
      }
    });
  }

  if (Number.isFinite(holdDurationSeconds) && holdDurationSeconds > 0) {
    appendMetaOperation("robot.meta.hold_sample", {
      source: "机器人样品预处理匹配",
      evidence: [`静置时长：${holdDurationSeconds}秒`],
      params: {
        sample_id: "sample_pending_identification",
        duration_seconds: holdDurationSeconds,
        location_id: DEFAULT_CHECKIN_LOCATION
      }
    });
  }

  const processingPositions = {
    "robot.meta.heat_sample": text.search(/加热|升温|恒温/),
    "robot.meta.mix_sample": text.search(/摇匀|混匀|震荡|振荡/),
    "robot.meta.hold_sample": text.search(/静置/)
  };
  const processingSteps = workflow.splice(processingStartIndex);
  processingSteps.sort((left, right) => {
    const leftPosition = processingPositions[left.operation.meta_operation_id] ?? Number.MAX_SAFE_INTEGER;
    const rightPosition = processingPositions[right.operation.meta_operation_id] ?? Number.MAX_SAFE_INTEGER;
    return (leftPosition < 0 ? Number.MAX_SAFE_INTEGER : leftPosition) -
      (rightPosition < 0 ? Number.MAX_SAFE_INTEGER : rightPosition);
  });
  workflow.push(...processingSteps);

  if (mentionsRobotTransfer && !(mentionsSample && /送到|送入/.test(text))) {
    appendMetaOperation("robot.meta.transfer_object", {
      source: "物理位移要求匹配",
      evidence: ["识别到机械臂点到点搬运要求"],
      params: {
        source_location_id: DEFAULT_CHECKIN_LOCATION,
        target_location_id: mentionsVD10 ? DEFAULT_VD10_LOCATION : "target_location_pending",
        object_id: "sample_pending_identification"
      }
    });
  }

  if (mentionsSample && mentionsDeliver) {
    appendMetaOperation("robot.meta.load_tube_to_agv", {
      source: "总体意图匹配",
      evidence: ["需要将试管装载到AGV"],
      params: {
        target_count: targetCount,
        source_location_id: DEFAULT_CHECKIN_LOCATION
      }
    });
  }

  if (mentionsFloorTransfer && !floorAfterTest) {
    appendFloorTransport(destinationFloor, targetCount, "before_test");
  }
  if (mentionsSample && mentionsDeliver) {
    appendInstrumentDelivery(targetCount, floorAfterTest ? null : destinationFloor);
    appendMetaOperation("robot.meta.prepare_and_load_instrument", {
      source: "总体意图匹配",
      evidence: ["需要将样品送入目标检测仪器"],
      params: {
        target_count: targetCount,
        target_device: mentionsVD10 ? "vd10" : "instrument_pending_assignment",
        target_location_id: mentionsVD10 ? DEFAULT_VD10_LOCATION : "target_location_pending"
      }
    });
  }

  if (mentionsResult) {
    appendMetaOperation("vd10.meta.query_test_results", {
      source: "总体意图匹配",
      evidence: ["识别到检测结果查询要求"]
    });
    appendMetaOperation("robot.meta.read_result_from_screen", {
      source: "VD10结果页面读取",
      evidence: ["需要由机器人读取并结构化VD10页面信息"],
      params: { device_id: "vd10" }
    });
  } else if (mentionsQuality) {
    appendMetaOperation("vd10.meta.inspect_quality_status", {
      source: "总体意图匹配",
      evidence: ["识别到质量状态检查要求"]
    });
  } else if (mentionsExit) {
    appendMetaOperation("vd10.meta.safe_exit", {
      source: "总体意图匹配",
      evidence: ["识别到安全退出要求"]
    });
  } else if (mentionsTest) {
    appendMetaOperation("vd10.meta.sample_test", {
      source: "总体意图匹配",
      evidence: ["识别到 VD10 或仪器检测目标"],
      params: {
        target_count: targetCount,
        sample_volume: volumeEach,
        destination_floor: floorAfterTest ? null : destinationFloor,
        target_device: mentionsVD10 ? "vd10" : "instrument_pending_assignment",
        target_location_id: mentionsVD10 ? DEFAULT_VD10_LOCATION : "target_location_pending"
      }
    });
    appendMetaOperation("vd10.meta.query_test_results", {
      source: "检测完成后自动衔接",
      evidence: ["检测完成后需要打开VD10结果页面"],
      params: {
        sample_id: "sample_pending_identification",
        target_device: mentionsVD10 ? "vd10" : "instrument_pending_assignment"
      }
    });
    appendMetaOperation("robot.meta.read_result_from_screen", {
      source: "检测完成后自动衔接",
      evidence: ["由机器人读取并结构化VD10输出信息"],
      params: { device_id: mentionsVD10 ? "vd10" : "instrument_pending_assignment" }
    });
  }

  if (mentionsFloorTransfer && floorAfterTest) {
    appendFloorTransport(destinationFloor, targetCount, "after_test");
  }

  lastAnalysis = {
    matched: workflow.length > 0,
    message: workflow.length
      ? `能力覆盖检查通过，已从元操作库选择 ${workflow.length} 个元操作。`
      : "当前预处理字段无法匹配到可用元操作，流程未生成。",
    factors
  };
  renderAll();
  showToast(lastAnalysis.message);
}

function validateWorkflow() {
  const issues = [];
  let physicalReady = true;

  workflow.forEach((step) => {
    if (!step.operation.internal_operations.length) {
      issues.push({ id: step.id, message: "元操作没有内部操作树。" });
    }
    const restrictedAtoms = step.operation.internal_operations.filter(
      (operation) => operation.execution_policy === "interface_only"
    );
    if (restrictedAtoms.length) {
      physicalReady = false;
    }
    if (step.operation.physical_requirements.length) {
      physicalReady = false;
    }
    if (step.operation.meta_operation_id === "vd10.meta.sample_test" &&
        step.params.target_device === "instrument_pending_assignment") {
      issues.push({ id: step.id, warning: true, message: "目标仪器类型尚未明确，当前按 VD10 演示流程编排。" });
      physicalReady = false;
    }
  });

  if (activeExternalPlanId) {
    physicalReady = latestPhysicalValidation?.result === "executable";
    (latestPhysicalValidation?.stepResults || []).forEach((result) => {
      if (!result.executable || result.blockers?.length) {
        issues.push({
          id: result.stepId,
          physical: true,
          warning: true,
          message: (result.blockers || []).join("；") || "外部物理校验未通过"
        });
      }
    });
  }

  return {
    semanticReady: workflow.length > 0 && !issues.some((issue) => !issue.warning),
    physicalReady: workflow.length > 0 && physicalReady,
    issues
  };
}

function physicalMessage(step) {
  if (activeExternalPlanId) {
    if (!latestPhysicalValidation) return "等待外部物理可执行确认";
    const result = (latestPhysicalValidation.stepResults || []).find((item) => item.stepId === step.id);
    if (!result) return "外部校验结果未包含此步骤";
    if (result.blockers?.length) return `阻断：${result.blockers.join("；")}`;
    if (result.executable) return `通过：${(result.checks || []).join("；") || "外部物理校验通过"}`;
    return "待确认：外部物理校验未通过";
  }
  const locationKeys = [
    "source_location_id", "target_location_id", "location_id", "source_station", "target_station"
  ];
  const referencedLocations = locationKeys
    .map((key) => step.params?.[key])
    .filter(Boolean);
  const missingLocations = referencedLocations.filter((id) => !spatialIndex.has(id));
  if (missingLocations.length) {
    return `待确认：位置未登记（${missingLocations.join("、")}）`;
  }
  const placeholderLocations = referencedLocations
    .map((id) => spatialIndex.get(id))
    .filter((location) => location?.placeholder || location?.status !== "verified");
  if (placeholderLocations.length) {
    return `待确认：${placeholderLocations.map((location) => location.name).join("、")}仍为占位坐标，实机执行前必须标定`;
  }
  const restricted = step.operation.internal_operations.some(
    (operation) => operation.execution_policy === "interface_only"
  );
  if (restricted) return "待确认：内部包含受限小操作，不能直接自动执行";
  if (step.operation.physical_requirements.length) {
    return `待确认：${step.operation.physical_requirements.join("；")}`;
  }
  return "通过：当前元操作不需要额外物理动作确认";
}

function renderAll() {
  const validation = validateWorkflow();
  renderFlow(validation);
  renderIntentSummary();
  syncExecutionRecords();
  renderExecutionStatus(validation);
  renderStructuredResults(validation);
}

function renderFlow(validation) {
  $("semantic-flow").innerHTML = workflow.map((step, index) =>
    renderFlowCard(step, index, validation, false)
  ).join("");
  $("physical-flow").innerHTML = workflow.map((step, index) =>
    renderFlowCard(step, index, validation, true)
  ).join("");

  document.querySelectorAll(".flow-remove").forEach((button) => {
    button.addEventListener("click", () => {
      workflow = workflow.filter((step) => step.id !== button.dataset.id);
      resetExecutionState();
      renderAll();
    });
  });

  document.querySelectorAll("#semantic-flow .flow-card").forEach((card) => {
    card.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/workflow-step", card.dataset.stepId);
    });
    card.addEventListener("dragover", (event) => event.preventDefault());
    card.addEventListener("drop", (event) => {
      event.preventDefault();
      const sourceId = event.dataTransfer.getData("text/workflow-step");
      const sourceIndex = workflow.findIndex((step) => step.id === sourceId);
      const targetIndex = workflow.findIndex((step) => step.id === card.dataset.stepId);
      if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return;
      const [moved] = workflow.splice(sourceIndex, 1);
      workflow.splice(targetIndex, 0, moved);
      resetExecutionState();
      renderAll();
    });
  });

  $("semantic-state").textContent = workflow.length
    ? (validation.semanticReady ? "匹配通过" : "存在问题")
    : "待生成";
  $("semantic-state").className =
    `check-state ${workflow.length ? (validation.semanticReady ? "pass" : "error") : ""}`;
  $("physical-state").textContent = workflow.length
    ? (validation.physicalReady ? "校验通过" : "待确认")
    : "待校验";
  $("physical-state").className =
    `check-state ${workflow.length ? (validation.physicalReady ? "pass" : "warn") : ""}`;
}

function renderFlowCard(step, index, validation, physicalStage) {
  const issue = validation.issues.find((item) =>
    item.id === step.id && Boolean(item.physical) === physicalStage
  );
  const message = physicalStage
    ? physicalMessage(step)
    : (issue?.message || `元操作包含 ${step.operation.internal_operations.length} 个内部小操作`);
  const parameterSummary = formatParameterSummary(step.params);
  return `
    <li class="flow-card flow-${escapeHtml(step.operation.category)} ${issue ? "warn" : ""}" data-step-id="${escapeHtml(step.id)}"
        ${physicalStage ? "" : 'draggable="true"'}>
      <span class="flow-index">${index + 1}</span>
      <div class="flow-main">
        <strong>${escapeHtml(step.operation.name)}</strong>
        <code>${escapeHtml(step.operation.meta_operation_id)}</code>
        ${parameterSummary ? `<span class="flow-params">${escapeHtml(parameterSummary)}</span>` : ""}
        <span class="flow-meta">${escapeHtml(message)}</span>
      </div>
      ${physicalStage ? "" : `<button class="flow-remove" data-id="${escapeHtml(step.id)}" title="移除">×</button>`}
    </li>`;
}

function formatParameterSummary(params) {
  const labels = {
    target_count: "数量",
    sample_count: "样品数",
    volume_each: "单份体积",
    sample_volume: "样品体积",
    destination_floor: "目标楼层",
    timing: "执行时序",
    target_type: "目标类型",
    target_device: "目标设备",
    source_location_id: "起始位置",
    target_location_id: "目标位置",
    source_station: "起始工位",
    target_station: "目标工位",
    location_id: "操作位置",
    temperature_c: "目标温度",
    duration_seconds: "持续时间",
    speed_rpm: "转速",
    method: "处理方式",
    heater_id: "加热设备",
    mixer_id: "混匀设备",
    container_type: "容器",
    transport_link_id: "运输链路"
  };
  const values = Object.entries(params || {}).filter(([, value]) => {
    return value !== null && value !== undefined && value !== "" &&
      (!Array.isArray(value) || value.length > 0);
  });
  return values.map(([key, value]) => {
    let display = Array.isArray(value) ? value.join("、") : String(value);
    if ((key === "target_count" || key === "sample_count") && /^\d+$/.test(display)) {
      display = `${display}份`;
    }
    if (key === "target_type" && display === "instrument") display = "仪器";
    if (key === "target_device" && display === "instrument_pending_assignment") display = "仪器待分配";
    if (key === "timing" && display === "before_test") display = "检测前";
    if (key === "timing" && display === "after_test") display = "检测后";
    return `${labels[key] || key}：${display}`;
  }).join(" · ");
}

function renderIntentSummary() {
  const parameters = latestSemanticMessage?.parameters || {};
  const sourceLabels = {
    history: "历史语义记录",
    local: "自然语言本地提取",
    local_api: "自然语言编排接口",
    live: "实时 MQTT 回包"
  };
  const sourceChips = latestSemanticMessage
    ? [`<span class="chip">来源：${sourceLabels[latestSemanticSource.type] || latestSemanticSource.type}</span>`]
    : [];
  const parameterChips = Object.entries(parameters).map(([key, field]) =>
    `<span class="chip">${escapeHtml(semanticFieldText(key, field))}</span>`
  );
  const clarification = latestSemanticMessage?.clarification || {};
  const missingChips = (clarification.missingFields || []).map((field) =>
    `<span class="chip chip-warning">缺少字段：${escapeHtml(field)}</span>`
  );
  const questionChips = (clarification.questions || []).map((question) =>
    `<span class="chip chip-warning">待补充：${escapeHtml(question)}</span>`
  );
  const analysisChips = (lastAnalysis?.factors || []).map((factor) =>
    `<span class="chip chip-analysis">${escapeHtml(factor)}</span>`
  );
  const decisionChips = lastAnalysis && !lastAnalysis.matched
    ? [`<span class="chip chip-warning">编排结论：${escapeHtml(lastAnalysis.message)}</span>`]
    : [];
  const chips = [
    ...sourceChips,
    ...parameterChips,
    ...missingChips,
    ...questionChips,
    ...analysisChips,
    ...decisionChips
  ];
  $("intent-summary").innerHTML = chips.length
    ? chips.join("")
    : '<span class="chip muted">等待 MQTT 返回预处理字段</span>';

  if (semanticResultStale) $("intent-state").textContent = "预处理结果已过期";
  else if (!latestSemanticMessage) $("intent-state").textContent = "等待预处理";
  else if (latestSemanticMessage.status === "failed") $("intent-state").textContent = "预处理失败";
  else if (clarification.needed) $("intent-state").textContent = "需要补充信息";
  else if (latestSemanticSource.type === "live" && latestSemanticMessage.workflowId && !latestPlannerMessage) $("intent-state").textContent = "等待同事B编排";
  else if (lastAnalysis?.matched) $("intent-state").textContent = "已生成元操作流程";
  else if (lastAnalysis) $("intent-state").textContent = "当前任务不可编排";
  else $("intent-state").textContent = "预处理完成";
}

function resetExecutionState() {
  executionRecords = [];
  executionRun = {
    status: "not_started",
    started_at: null,
    finished_at: null
  };
}

function syncExecutionRecords() {
  executionRecords = workflow.map((step) => {
    const existing = executionRecords.find((record) => record.step_id === step.id);
    return existing || {
      step_id: step.id,
      meta_operation_id: step.operation.meta_operation_id,
      name: step.operation.name,
      category: step.operation.category,
      status: "pending",
      started_at: null,
      finished_at: null,
      duration_ms: null,
      key_data: formatParameterSummary(step.params) || "暂无关键参数"
    };
  });
}

function simulateExecution() {
  if (!workflow.length) {
    showToast("请先生成任务流程");
    return;
  }
  const validation = validateWorkflow();
  if (!validation.semanticReady) {
    showToast("语义校验未通过，不能模拟执行");
    return;
  }

  const finishTime = Date.now();
  const baseTime = finishTime - workflow.length * 1200;
  executionRun = {
    status: "simulation_completed",
    started_at: new Date(baseTime).toISOString(),
    finished_at: new Date(finishTime).toISOString()
  };
  executionRecords = workflow.map((step, index) => {
    const startedAt = baseTime + index * 1200;
    const durationMs = 800 + index * 100;
    return {
      step_id: step.id,
      meta_operation_id: step.operation.meta_operation_id,
      name: step.operation.name,
      category: step.operation.category,
      status: "simulated_success",
      started_at: new Date(startedAt).toISOString(),
      finished_at: new Date(startedAt + durationMs).toISOString(),
      duration_ms: durationMs,
      key_data: formatParameterSummary(step.params) ||
        `内部小操作：${step.operation.internal_operations.length}项`
    };
  });
  renderAll();
  activateTab("status");
  showToast("模拟执行完成，未向真实设备发送指令");
}

function formatTimestamp(value) {
  if (!value) return "--";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function createTaskHandoff(validation) {
  const locationKeys = [
    "source_location_id", "target_location_id", "location_id", "source_station", "target_station"
  ];
  const referencedLocationIds = new Set();
  workflow.forEach((step) => {
    locationKeys.forEach((key) => {
      if (step.params?.[key]) referencedLocationIds.add(step.params[key]);
    });
  });
  return {
    task_id: taskId,
    source_text: $("intent-input").value,
    semantic_preprocessing: latestSemanticMessage,
    semantic_source: latestSemanticSource,
    spatial_context: {
      map_id: spatialLocationLibrary?.map_id || null,
      coordinate_frame: spatialLocationLibrary?.coordinate_frame || null,
      building: spatialLocationLibrary?.building || null,
      locations: [...referencedLocationIds]
        .map((id) => spatialIndex.get(id) || { id, status: "unregistered" }),
      transport_links: spatialLocationLibrary?.transport_links || []
    },
    operation_sequence: workflow.map((step, index) => ({
      order: index + 1,
      meta_operation_id: step.operation.meta_operation_id,
      name: step.operation.name,
      category: step.operation.category,
      params: step.params,
      internal_operation_tree: step.operation.internal_operations.map((operation, atomIndex) => ({
        order: atomIndex + 1,
        capability_id: operation.capability_id,
        name: operation.name,
        execution_policy: operation.execution_policy
      })),
      physical_requirements: step.operation.physical_requirements
    })),
    semantic_validation: validation.semanticReady ? "pass" : "blocked",
    physical_validation: validation.physicalReady ? "pass" : "pending",
    execution_mode: "simulation_only",
    execution_run: executionRun,
    execution_records: executionRecords,
    structured_experiment_result: buildStructuredExperimentResult(validation)
  };
}

function renderExecutionStatus(validation) {
  if (!workflow.length) {
    $("tab-status").innerHTML = '<div class="empty">生成任务流程后显示逐步执行状态与记录</div>';
    return;
  }

  const runStatus = executionRun.status === "simulation_completed"
    ? "模拟执行完成"
    : "等待模拟执行";
  $("tab-status").innerHTML = `
    <div class="status-card execution-summary">
      <strong>当前任务：${escapeHtml(taskId)}</strong>
      <div class="status-line"><span>任务状态</span><span class="${executionRun.status === "simulation_completed" ? "success" : "warning"}">${runStatus}</span></div>
      <div class="status-line"><span>语义校验</span><span class="${validation.semanticReady ? "success" : "warning"}">${validation.semanticReady ? "通过" : "已阻止"}</span></div>
      <div class="status-line"><span>物理校验</span><span class="${validation.physicalReady ? "success" : "warning"}">${validation.physicalReady ? "通过" : "等待真实环境确认"}</span></div>
      <div class="status-line"><span>任务开始</span><span>${escapeHtml(formatTimestamp(executionRun.started_at))}</span></div>
      <div class="status-line"><span>任务完成</span><span>${escapeHtml(formatTimestamp(executionRun.finished_at))}</span></div>
    </div>
    <div class="execution-records">
      ${executionRecords.map((record, index) => `
        <article class="execution-record record-${escapeHtml(record.category)}">
          <div class="record-head">
            <span class="record-index">${index + 1}</span>
            <strong>${escapeHtml(record.name)}</strong>
            <span class="record-badge ${record.status === "simulated_success" ? "done" : "pending"}">
              ${record.status === "simulated_success" ? "模拟完成" : "待执行"}
            </span>
          </div>
          <div class="record-data"><span>开始时间</span><b>${escapeHtml(formatTimestamp(record.started_at))}</b></div>
          <div class="record-data"><span>完成时间</span><b>${escapeHtml(formatTimestamp(record.finished_at))}</b></div>
          <div class="record-data"><span>耗时</span><b>${record.duration_ms === null ? "--" : `${record.duration_ms} ms`}</b></div>
          <div class="record-key-data"><span>关键数据</span><p>${escapeHtml(record.key_data)}</p></div>
        </article>`).join("")}
    </div>`;
}

function buildStructuredExperimentResult(validation) {
  const allParams = workflow.map((step) => step.params || {});
  const pickFirst = (...keys) => {
    for (const params of allParams) {
      for (const key of keys) {
        const value = params[key];
        if (value !== null && value !== undefined && value !== "") return value;
      }
    }
    return null;
  };
  const instrumentOperations = workflow.filter((step) => step.operation.category === "instrument");
  return {
    task_id: taskId,
    result_status: executionRun.status === "simulation_completed"
      ? "simulation_completed_waiting_device_data"
      : "not_executed",
    sample: {
      count: pickFirst("target_count", "sample_count"),
      volume_each: pickFirst("volume_each", "sample_volume")
    },
    destination: {
      floor: pickFirst("destination_floor")
    },
    execution: {
      semantic_validation: validation.semanticReady ? "pass" : "blocked",
      physical_validation: validation.physicalReady ? "pass" : "pending",
      started_at: executionRun.started_at,
      finished_at: executionRun.finished_at
    },
    instrument_results: instrumentOperations.map((step) => ({
      meta_operation_id: step.operation.meta_operation_id,
      device: step.params.target_device || "pending_assignment",
      status: "waiting_real_device_data",
      measurements: null
    }))
  };
}

function renderStructuredResults(validation) {
  const result = buildStructuredExperimentResult(validation);
  const instrumentResults = result.instrument_results.length
    ? result.instrument_results.map((item, index) => `
        <article class="instrument-result">
          <div><span>仪器任务 ${index + 1}</span><b>${escapeHtml(item.device === "pending_assignment" || item.device === "instrument_pending_assignment" ? "仪器待分配" : item.device)}</b></div>
          <div><span>数据状态</span><b class="warning">等待真实设备回传</b></div>
          <div><span>测量数据</span><b>--</b></div>
        </article>`).join("")
    : '<div class="empty compact-empty">当前流程中没有检测仪器元操作</div>';

  $("tab-results").innerHTML = `
    <div class="result-overview">
      <div><span>结果状态</span><b>${executionRun.status === "simulation_completed" ? "模拟流程完成" : "尚未执行"}</b></div>
      <div><span>样品数量</span><b>${result.sample.count ?? "--"}</b></div>
      <div><span>单份体积</span><b>${escapeHtml(result.sample.volume_each ?? "--")}</b></div>
      <div><span>目标楼层</span><b>${escapeHtml(result.destination.floor ?? "--")}</b></div>
    </div>
    <h3 class="result-subtitle">仪器检测结果</h3>
    ${instrumentResults}
    <p class="simulation-note">当前为模拟模式，只记录流程和参数，不生成虚假的 VD10 测量值。</p>
  `;
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.querySelectorAll(".tab-content").forEach((panel) => {
    panel.hidden = panel.id !== `tab-${name}`;
  });
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 1800);
}

initialize();
