"use strict";

(() => {
  const panel = document.getElementById("manual-import");
  if (!panel) return;
  const file = panel.querySelector('input[type="file"]');
  const token = panel.querySelector('input[type="password"]');
  const status = panel.querySelector('[role="status"]');
  const list = panel.querySelector(".manual-candidates");
  const filter = panel.querySelector(".manual-filter select");
  const deviceSelect = panel.querySelector("#manual-device");
  const deviceNote = panel.querySelector("#manual-device-note");
  const deviceForm = panel.querySelector("#manual-device-form");
  const deviceName = panel.querySelector("#manual-device-name");
  const newDeviceButton = panel.querySelector("#manual-device-new");
  const reuseVd10 = panel.querySelector("#manual-reuse-vd10");
  const api = "/api/v1/manual-capabilities";
  const scene = "/scenarios/vd10_single_sample_demo";
  let batch = "";
  let draftItems = [];
  const tokenLabel = token.closest("label");
  tokenLabel.hidden = true;
  const access = fetch(api + "/access", { cache: "no-store" }).then(async response => {
    if (!response.ok) throw new Error("无法确认说明书导入权限。");
    const { mode } = await response.json();
    tokenLabel.hidden = mode !== "token";
    if (mode === "disabled") status.textContent = "远程导入未启用；可使用本机演示入口。";
    return mode;
  }).catch(err => {
    status.textContent = err.message;
    return "disabled";
  });

  const element = (tag, value) => {
    const node = document.createElement(tag);
    node.textContent = value;
    return node;
  };

  function updateDeviceNote() {
    const option = deviceSelect.selectedOptions[0];
    const canReuse = option?.dataset.reusable === "true";
    reuseVd10.closest("label").hidden = !canReuse;
    deviceNote.textContent = !deviceSelect.value || option?.dataset.supported === "true" ? "" : canReuse
      ? "请核对说明书是否适用于所选设备。生成的元操作将归入该设备，仍需审核后发布。"
      : "该设备暂未配置说明书解析规则。";
  }

  async function loadDevices(selected = deviceSelect.value) {
    const response = await fetch(api + "/devices", { cache: "no-store" });
    if (!response.ok) throw new Error("无法读取设备列表。");
    const {devices} = await response.json();
    const placeholder = element("option", "请选择设备");
    placeholder.value = "";
    deviceSelect.replaceChildren(placeholder, ...devices.map(device => {
      const option = element("option", device.name + (device.is_new ? " · 新" : ""));
      option.value = device.id;
      option.dataset.supported = String(device.manual_import_supported);
      option.dataset.reusable = String(device.can_reuse_vd10);
      return option;
    }));
    if (devices.some(device => device.id === selected)) deviceSelect.value = selected;
    updateDeviceNote();
  }

  function showDeviceForm(show) {
    deviceForm.hidden = !show;
    newDeviceButton.setAttribute("aria-expanded", String(show));
    newDeviceButton.textContent = show ? "取消新增" : "新增设备";
    if (show) deviceName.focus();
  }

  document.getElementById("manual-import-open").addEventListener("click", () => {
    panel.showModal();
    loadDevices().catch(err => { status.textContent = err.message; });
  });
  deviceSelect.addEventListener("change", () => {
    reuseVd10.checked = false;
    updateDeviceNote();
  });
  newDeviceButton.addEventListener("click", () => showDeviceForm(deviceForm.hidden));
  deviceForm.addEventListener("submit", async event => {
    event.preventDefault();
    const submit = deviceForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const device = await request("/devices", "POST", {name: deviceName.value.trim()});
      reuseVd10.checked = false;
      deviceForm.reset();
      showDeviceForm(false);
      await loadDevices(device.id);
      await reloadManualCatalog();
      status.textContent = (device.restored ? "已恢复并选中「" : "已添加并选中「") + device.name + "」。";
    } catch (err) { status.textContent = err.message; }
    finally { submit.disabled = false; }
  });
  async function request(path, method = "GET", payload) {
    const mode = await access;
    const headers = {};
    if (mode === "local") headers["X-Manual-Import"] = "1";
    else if (mode === "token") {
      if (!token.value) throw new Error("请输入管理员令牌。");
      headers.Authorization = "Bearer " + token.value;
    } else throw new Error("请使用本机演示入口，或请部署管理员启用远程导入。");
    let body = payload;
    if (payload && !(payload instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(payload);
    }
    const response = await fetch(api + path, { method, headers, body, cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "提交内容不符合要求。");
    return result;
  }

  function button(label, handler, primary = false) {
    const node = element("button", label);
    node.className = "button " + (primary ? "primary" : "secondary");
    node.type = "button";
    node.addEventListener("click", async () => {
      node.disabled = true;
      status.textContent = "处理中…";
      try { status.textContent = await handler() || "操作完成。"; }
      catch (err) { status.textContent = err.message; }
      finally { node.disabled = false; }
    });
    return node;
  }

  async function refresh() {
    const data = await request("/drafts" + (batch ? "?batch=" + encodeURIComponent(batch) : ""));
    batch = data.batch;
    draftItems = data.items;
    filter.closest("label").hidden = false;
    renderDrafts();
  }

  function renderDrafts() {
    list.replaceChildren();
    const states = {draft:"待审核", approved:"已通过 · 待发布", rejected:"已驳回", published:"已发布", withdrawn:"已撤回"};
    if (draftItems.some(item => item.state === "approved" && item.details)) {
      list.append(button("发布本批已通过项", async () => {
        const result = await request("/batches/" + encodeURIComponent(batch) + "/publish", "POST");
        await reloadManualCatalog();
        await loadDevices();
        await refresh();
        return releaseName(result.release_id) + " 已发布 " + result.published + " 项，能力库已更新。";
      }, true));
    }
    const items = draftItems.filter(item => !filter.value || item.state === filter.value);
    if (!items.length) list.append(element("p", draftItems.length
      ? "没有符合当前审核状态的草稿。"
      : "还没有任务级草稿。请选择说明书 PDF 并点击「生成元操作」。"));
    for (const item of items) {
      const card = document.createElement("article");
      card.className = "manual-card";
      const badge = element("span", states[item.state]);
      badge.className = "chip";
      card.append(element("h3", item.name), badge, element("p", "设备：" + (item.details?.device_name || "VD10 自动蒸馏测定仪")));
      if (item.release_id) card.append(element("p", "发布编号：" + releaseName(item.release_id)));
      const detail = document.createElement("details");
      detail.append(element("summary", "查看内部步骤、输入与说明书依据"));
      const task = item.details;
      if (task) {
        card.append(element("p", "预期结果：" + task.outcome));
        detail.append(element("p", "输入：" + task.inputs), element("p", item.filename));
        const tree = document.createElement("ol");
        for (const step of task.steps) {
          const branch = element("li", step.name);
          branch.append(element("p", step.section + " · 第 " + step.page + " 页"), element("blockquote", step.evidence));
          tree.append(branch);
        }
        detail.append(tree);
        if (item.approved_steps) {
          const approved = document.createElement("ol");
          approved.append(...item.approved_steps.map(step => element("li", step)));
          detail.append(element("p", "审核后的描述：" + item.approved_description),
            element("p", "审核后的操作树"), approved);
        }
      } else {
        card.append(element("p", "旧版碎片记录。重新导入可生成任务级卡片。"));
        detail.append(element("p", item.filename + " · 第 " + item.page + " 页"), element("blockquote", item.evidence));
      }
      card.append(detail);
      const path = "/drafts/" + encodeURIComponent(item.id);
      if (item.state === "draft" && task) {
        const name = element("input", "");
        name.value = item.name;
        name.maxLength = 100;
        name.setAttribute("aria-label", "能力名称");
        const description = element("textarea", "");
        description.value = task.outcome;
        description.maxLength = 600;
        description.setAttribute("aria-label", "能力描述");
        const steps = element("textarea", "");
        steps.value = task.steps.map(step => step.name).join("\n");
        steps.rows = Math.min(6, task.steps.length + 1);
        const field = (label, input) => {
          const wrapper = element("label", label);
          wrapper.append(input);
          return wrapper;
        };
        const review = async approve => {
          await request(path + "/review", "POST", {name:name.value, description:description.value, approve,
            steps:steps.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean)});
          await refresh();
        };
        detail.append(field("能力名称", name), field("能力描述", description), field("内部步骤（每行一步）", steps));
        const actions = document.createElement("div");
        actions.append(button("审核通过", () => review(true), true), button("驳回", () => review(false)));
        card.append(actions);
      } else if (item.state === "published" && (!task?.device_id || task.device_id === "vd10")) {
        card.append(button(item.scene ? "停用 VD10 草案预览" : "启用 VD10 草案预览", async () => {
          await request(scene + "/" + encodeURIComponent(item.id), "PUT", {enabled:!item.scene});
          await refresh();
          await reloadManualCatalog();
        }));
      }
      list.append(card);
    }
  }

  const releaseName = id => "R" + String(id).padStart(4, "0");

  async function withdraw(path, question) {
    if (!window.confirm(question + " 撤回后将从左侧能力库和草案预览移除，审核记录会保留。")) return "已取消撤回。";
    const result = await request(path, "POST");
    await reloadManualCatalog();
    await loadDevices();
    await showReleases();
    return "已撤回 " + result.withdrawn + " 项。";
  }

  async function showReleases() {
    const history = await request("/releases");
    filter.closest("label").hidden = true;
    list.replaceChildren();
    if (!history.releases.length) list.append(element("p", "暂无发布记录。"));
    for (const release of history.releases) {
      const card = element("article", "");
      card.className = "manual-card";
      const active = release.items.filter(item => item.state === "published").length;
      const publishedAt = release.published_at ? new Date(release.published_at).toLocaleString() : "旧版记录，发布时间未登记";
      card.append(element("h3", releaseName(release.id)),
        element("p", publishedAt + " · 生效 " + active + " / " + release.items.length + " 项"));
      const items = element("ul", "");
      for (const item of release.items) {
        const row = element("li", item.name + (item.withdrawn_at ? " · 已撤回 " + new Date(item.withdrawn_at).toLocaleString() : " · 已发布"));
        if (item.state === "published") row.append(button("撤回此项", () => withdraw(
          "/drafts/" + encodeURIComponent(item.operation_id) + "/withdraw", "确认撤回「" + item.name + "」？")));
        items.append(row);
      }
      card.append(items);
      card.append(button("查看该批审核记录", async () => {
        batch = release.batch;
        filter.value = "";
        await refresh();
      }));
      if (active) card.append(button("撤回本次发布", () => withdraw(
        "/releases/" + release.id + "/withdraw", "确认撤回 " + releaseName(release.id) + " 中仍生效的 " + active + " 项？")));
      list.append(card);
    }
  }

  filter.addEventListener("change", renderDrafts);
  panel.querySelector(".manual-actions").append(button("生成元操作", async () => {
    if (!deviceSelect.value) throw new Error("请先选择目标设备。");
    const reuse = !reuseVd10.closest("label").hidden && reuseVd10.checked;
    if (deviceSelect.value !== "vd10" && !reuse) {
      throw new Error(reuseVd10.closest("label").hidden ? "所选设备暂未配置说明书解析规则。" : "请先批准所选设备使用此说明书。");
    }
    if (!file.files[0]) throw new Error("请选择说明书 PDF。");
    const form = new FormData();
    form.append("document", file.files[0]);
    form.append("device", deviceSelect.value);
    form.append("use_vd10_manual", String(reuse));
    batch = (await request("/drafts", "POST", form)).batch;
    await refresh();
    return "已生成 " + draftItems.length + " 张任务卡片。";
  }, true), button("读取最近一批任务草稿", async () => {
    batch = "";
    filter.value = "";
    await refresh();
    return draftItems.length ? "已载入 " + draftItems.length + " 张任务卡片。" : "旧版碎片不会出现在任务审核列表中。";
  }),
  button("发布历史与撤回", showReleases),
  button("查看已启用能力快照", async () => {
    const snapshot = await request(scene + "/preview");
    filter.closest("label").hidden = true;
    list.replaceChildren(element("p", "VD10 草案预览 · 不修改原编排，不允许执行"),
      element("p", snapshot.checksum));
    const choices = [];
    for (const operation of snapshot.operations) {
      const label = element("label", "");
      const check = document.createElement("input");
      check.type = "checkbox";
      label.append(check, document.createTextNode(operation.name));
      label.className = "manual-card";
      list.append(label);
      choices.push([check, operation.id]);
    }
    const plan = element("ol", "");
    list.append(button("按所选条目生成草案", async () => {
      const operation_ids = choices.filter(([check]) => check.checked).map(([, id]) => id);
      if (!operation_ids.length) throw new Error("请选择需要预览的元操作。");
      const result = await request(scene + "/preview", "POST", {checksum:snapshot.checksum, operation_ids});
      plan.replaceChildren(...result.steps.map(step => element("li", step.name + " · 待实机验证")));
    }), plan);
  }));
})();
