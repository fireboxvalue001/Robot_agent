"use strict";

function extractionEscape(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function renderConfiguredClarifications(definition) {
  const esc = extractionEscape;
  const entries = definition.clarifications || [];
  const parameters = entries.filter(item => item.kind === "parameter");
  const blockers = entries.filter(item => item.kind !== "parameter");
  if (!entries.length) return '<p class="clarification-complete">本次没有待补参数；设备与现场条件仍需独立确认。</p>';
  return `<details class="clarification-checklist-details"><summary class="clarification-checklist-heading"><strong>本次需要补充什么</strong><span>${parameters.length} 项参数 · ${blockers.length} 项其他待处理 · 点击展开</span></summary><div class="clarification-checklist-body">
    <p>可以直接在下方填写，支持分批提交。单位已标明；数值须由实验负责人或已审核方法确认。</p>
    ${blockers.map(item => `<article class="clarification-blocker"><b>${esc(item.label)}</b><p>${esc(item.instruction)}</p>${item.questions?.length ? `<ul>${item.questions.map(question => `<li>${esc(question)}</li>`).join("")}</ul>` : ""}${item.configuration_notice ? `<p><b>系统配置：</b>${esc(item.configuration_notice)}</p>` : ""}${item.format ? `<small>处理完成后填写：${esc(item.format)}</small>` : ""}</article>`).join("")}
    ${parameters.length ? `<div class="clarification-fields">${parameters.map((item, index) => {
      const steps = [...new Set(item.related_steps || [])];
      const inputType = item.type || "number";
      const attributes = `id="extraction-field-${index}" data-extraction-field="${esc(item.field)}" data-label="${esc(item.label)}" data-unit="${esc(item.unit || "")}" data-input-type="${esc(inputType)}"`;
      const choices = item.enum || (inputType === "boolean" ? ["是", "否"] : null);
      const input = choices ? `<select ${attributes}><option value="">请选择确认值</option>${choices.map(value => `<option value="${esc(typeof value === "boolean" ? value ? "是" : "否" : value)}">${esc(typeof value === "boolean" ? value ? "是" : "否" : value)}</option>`).join("")}</select>`
        : `<input ${attributes} type="${inputType === "number" ? "number" : "text"}" ${item.minimum !== undefined ? `min="${esc(item.minimum)}"` : ""} ${item.maximum !== undefined ? `max="${esc(item.maximum)}"` : ""} step="${item.integer ? "1" : "any"}" placeholder="请填写确认值">`;
      return `<label class="clarification-field" for="extraction-field-${index}"><b>${esc(item.label)}</b><small>用于：${esc(steps.slice(0, 2).join("、"))}${steps.length > 2 ? `等${steps.length}处` : ""}</small>
        <span class="clarification-number">${input}<span>${esc(item.unit || "")}</span></span>
        <small>文字填写格式：${esc(item.format)}</small></label>`;
    }).join("")}</div><div class="clarification-checklist-actions"><button class="button primary" type="button" data-apply-extraction-fields>应用已填写项并重新编排</button><small>空白项保持待补充，不会自动填入默认值。</small></div>` : ""}</div></details>`;
}

function renderConfiguredWorkflow(definition) {
  const groups = new Map();
  for (const phase of definition.phases || []) groups.set(phase.id, []);
  for (const node of definition.nodes || []) {
    const phase = node.phase_id || "default";
    if (!groups.has(phase)) groups.set(phase, []);
    groups.get(phase).push(node);
  }
  const labels = new Map(definition.nodes.map((node) => [node.id, node.label]));
  const esc = extractionEscape;
  const phaseItems = [...groups].filter(([, nodes]) => nodes.length).map(([phaseId, nodes]) => {
    const phase = definition.phases?.find(item => item.id === phaseId)?.label || "流程步骤";
    const missing = nodes.filter((node) => node.status !== "covered");
    const loops = nodes.filter((node) => node.kind === "loop_check");
    return `<details class="extraction-phase"><summary><b>${esc(phase)}</b><span>${nodes.length} 步 · ${missing.length ? `${missing.length} 处待处理` : "定义已匹配"}${loops.length ? " · 含恒重循环" : ""}</span></summary>
      <div class="extraction-node-list">${nodes.map((node) => {
        const call = OperationDisplay.describe({ label: node.label, capabilityName: node.operation_name,
          display: node.display, bindings: node.arguments || node.input_bindings, parameters: definition.parameters });
        const isCheck = ["loop_check", "decision", "guard"].includes(node.kind);
        const branches = [];
        for (const [key, label] of [["on_pass", "是"], ["on_fail", "否，更新上次质量后返回"], ["on_limit", "达到循环上限"], ["on_timeout", "超时"], ["on_error", "异常"]]) {
          if (node[key]) branches.push(`<span>${esc(node.display?.branch_labels?.[key] || (key === "on_fail" ? "否，返回" : label))} → ${esc(labels.get(node[key]) || node[key])}</span>`);
        }
        const next = node.next ? `<small>↓ ${esc(labels.get(node.next) || node.next)}</small>` : "";
        const params = (node.requires || []).map((key) => {
          const binding = definition.parameters[key];
          return binding ? `${binding.label || key}=${binding.value}${binding.unit || ""}（${binding.source === "provided_document" ? "实验文档" : binding.source === "user_supplement" ? "用户补充方案" : "用户输入"}）` : `待补充：${node.reason.replace("待补充：", "")}`;
        });
        return `<article class="extraction-node ${node.status === "covered" ? "matched" : "missing"}${isCheck ? " condition" : ""}">
          <div class="extraction-node-title"><span>${isCheck ? "◇ 判断" : node.kind === "compute" ? "计算" : node.kind === "monitored_hold" ? "持续监测" : "操作"}</span><b>${esc(call.title)}</b></div>
          ${call.capabilityName ? `<p>使用能力：${esc(call.capabilityName)}</p>` : ""}
          ${call.summary ? `<p>${esc(call.summary)}</p>` : ""}
          <p>${esc(node.reason)}</p>${node.display?.notice ? `<p>${esc(node.display.notice)}</p>` : ""}
          ${params.length ? `<details><summary>参数及来源</summary><p>${esc(params.join("；"))}</p></details>` : ""}
          ${node.data_refs?.length ? `<details><summary>引用前面步骤的数据</summary><p>${esc(node.data_refs.map((ref) => {const [id, field] = ref.split("."); return `${labels.get(id) || id}：${field}`;}).join("；"))}</p></details>` : ""}
          ${branches.length ? `<div class="extraction-branches">${branches.join("")}</div>` : ""}${next}
        </article>`;
      }).join("")}</div></details>`;
  }).join('<div class="extraction-phase-arrow">↓</div>');
  const scope = definition.task_scope;
  const scopeNotice = scope?.mode === "needs_selection"
    ? '<p class="chip chip-warning">尚未确定本次操作范围，请在C1待补清单中选择；当前不会生成完整实验流程。</p>' : "";
  return `<div class="extraction-workflow">${scopeNotice}
    ${renderConfiguredDiagram(groups, definition)}
    <details><summary>展开各阶段的单步动作、参数和分支</summary><div class="extraction-overview">${phaseItems}</div></details><details><summary>待绑定的设备与执行配置</summary>${definition.resources.map((resource) => `<p>${esc(resource.name || resource.id)}：${resource.type === "screen_adapter_profile" ? esc(resource.notice) : `${esc(resource.device_id || "设备待绑定")} / ${esc(resource.location_id || "位置待登记")}`}</p>`).join("")}</details>
    <details><summary>结构化流程定义（交接用）</summary><pre>${esc(JSON.stringify(definition, null, 2))}</pre></details></div>`;
}

function renderConfiguredDiagram(groups, definition) {
  const esc = extractionEscape;
  const configs = new Map((definition.phases || []).map(phase => [phase.id, phase]));
  const combinedInto = new Map();
  for (const [id, nodes] of groups) {
    const other = configs.get(id)?.diagram?.combine_with;
    if (other && nodes.length && groups.get(other)?.length) combinedInto.set(other, id);
  }
  const phases = [...groups].filter(([id, nodes]) => nodes.length && !configs.get(id)?.exception && !combinedInto.has(id));
  let shapes = "", edges = "";
  let y = 25;
  const positions = new Map();
  for (const [phaseId, phaseNodes] of phases) {
    const config = configs.get(phaseId) || {label:"流程步骤"};
    const diagram = config.diagram || {};
    const combined = combinedInto.get(diagram.combine_with) === phaseId;
    const nodes = combined ? [...phaseNodes, ...groups.get(diagram.combine_with)] : phaseNodes;
    const combinedLabel = diagram.combined_label || config.label;
    const phase = combined ? (definition.task_scope?.mode === "partial" ? combinedLabel.replace(/^\d+\.\s*/, "") : combinedLabel) : config.label;
    const loopNode = nodes.find((node) => node.kind === "loop_check");
    const loop = diagram.shape === "decision" || Boolean(loopNode);
    const missing = nodes.filter((node) => node.status !== "covered").length;
    const color = missing ? "#e6c15a" : "#4dcd9c";
    const actions = nodes.filter(node => node.operation_id);
    const singleCall = actions.length === 1 ? OperationDisplay.describe({ label: actions[0].label, capabilityName: actions[0].operation_name,
      display: actions[0].display, bindings: actions[0].arguments || actions[0].input_bindings, parameters: definition.parameters }) : null;
    const checkCount = nodes.filter(node => ["guard", "decision", "loop_check"].includes(node.kind)).length;
    const heading = singleCall && actions[0].display?.title
      ? `${phase.match(/^\d+\.\s*/)?.[0] || ""}${singleCall.title}` : phase;
    const titleLines = OperationDisplay.wrap(heading);
    const capabilityLines = singleCall?.capabilityName ? OperationDisplay.wrap(`使用能力：${singleCall.capabilityName}`) : [];
    const height = loop ? 108 : Math.max(68, (titleLines.length + capabilityLines.length + 1) * 21 + 24);
    const middle = y + height / 2;
    positions.set(phaseId, {top:y, bottom:y+height, middle});
    shapes += `<g><title>${esc(phase)}：${missing ? `${missing}个节点待补充` : "逻辑定义已匹配，尚未执行"}</title>`;
    shapes += loop
      ? `<polygon points="410,${y} 610,${middle} 410,${y + height} 210,${middle}" fill="#28243f" stroke="${color}"/>`
      : `<rect x="210" y="${y}" width="400" height="${height}" rx="8" fill="#1d2b35" stroke="${color}"/>`;
    const subtitle = diagram.subtitle ? diagram.subtitle.replace(/\{\{([a-z0-9_]+)\}\}/g, (_, key) => definition.parameters[key]?.value ?? "待确认")
      : `${actions.length ? `${actions.length}次能力调用 · ${checkCount}项检查` : `${nodes.length}个流程控制节点`} · ${missing ? `${missing}处待补充` : "定义已匹配"}`;
    if (loop) {
      shapes += `<text x="410" y="${middle - 7}" class="extraction-svg-title">${esc(phase)}</text><text x="410" y="${middle + 16}">${esc(subtitle)}</text>`;
    } else {
      const lines = [...titleLines, ...capabilityLines, subtitle];
      const firstY = middle - (lines.length - 1) * 10.5;
      shapes += lines.map((line, index) => `<text x="410" y="${firstY + index * 21}"${index < titleLines.length ? ' class="extraction-svg-title"' : ""}>${esc(line)}</text>`).join("");
    }
    shapes += "</g>";
    if (loop) {
      const limit = definition.parameters[diagram.limit_ref || loopNode?.max_iterations_ref]?.value;
      const repeatLines = diagram.repeat_lines || ["否：返回重试"];
      edges += `<path d="M210 ${middle} H65 V${y - 24} H410" stroke="#d2def2" stroke-width="2.3" stroke-dasharray="5 4"/><path d="M410 ${y - 24} V${y - 18}" stroke="#d2def2" stroke-width="2.3"/><polygon class="extraction-loop-arrow" points="402,${y - 18} 418,${y - 18} 410,${y - 2}" fill="#d2def2" stroke="none"/>${repeatLines.map((line, index) => `<text x="125" y="${middle - 9 + index * 20}">${esc(line)}</text>`).join("")}`;
      shapes += `<text x="742" y="${middle - 8}">循环上限：${limit || "待补充"}${limit ? "次" : ""}</text><text x="742" y="${middle + 14}">达到上限 → 停止复核</text>`;
    } else if (missing) shapes += `<text x="740" y="${middle}" fill="#efcf7b">待补信息见阶段详情</text>`;
    y += height + 42;
  }
  const nodesById = new Map(definition.nodes.map(node => [node.id,node]));
  const phaseEdges = new Map();
  for (const node of definition.nodes) {
    const fromId = combinedInto.get(node.phase_id) || node.phase_id;
    const from = positions.get(fromId);
    if (!from) continue;
    for (const [branch,label] of [["next",""],["on_pass","是"],["on_fail","否"],["on_limit","达到上限"],["on_error","异常"],["on_timeout","超时"]]) {
      const target = nodesById.get(node[branch]);
      const toId = target && (combinedInto.get(target.phase_id) || target.phase_id);
      const to = positions.get(toId);
      if (!to || toId === fromId) continue;
      const key = `${fromId}:${toId}`;
      if (!phaseEdges.has(key)) phaseEdges.set(key, {from, to, labels:new Set()});
      if (label) phaseEdges.get(key).labels.add(label);
    }
  }
  for (const [key, {from, to, labels}] of phaseEdges) {
    const label = [...labels].join(" / ");
    const adjacent = to.top > from.bottom && to.top - from.bottom < 50;
    edges += `<g data-phase-edge="${esc(key)}">` + (adjacent
      ? `<path d="M410 ${from.bottom} V${to.top - 3}" marker-end="url(#extraction-arrow)"/>${label ? `<text x="435" y="${from.bottom + 20}">${esc(label)}</text>` : ""}`
      : `<path d="M610 ${from.middle} H850 V${to.middle} H613" marker-end="url(#extraction-arrow)"/><text x="825" y="${from.middle-8}">${esc(label || "继续")}</text>`) + "</g>";
  }
  shapes += `<text x="450" y="${y + 10}">异常或超时 → 对应异常处理分支 → 人工复核</text>`;
  return `<div class="extraction-chart"><svg viewBox="0 0 910 ${y + 40}" role="img" aria-label="${esc(definition.name || "实验")}流程图"><defs><marker id="extraction-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="#9dacbf" stroke="none"/></marker></defs><g fill="none" stroke="#9dacbf" stroke-width="1.7">${edges}</g>${shapes}</svg></div>`;
}

// Historical function names remain available for cached clients.
function renderExtractionWorkflow(definition) { return renderConfiguredWorkflow(definition); }
function renderExtractionClarifications(definition) { return renderConfiguredClarifications(definition); }
