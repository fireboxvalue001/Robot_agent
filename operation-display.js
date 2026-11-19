"use strict";

// Presentation only: a call keeps its C2 ID/version regardless of its title or parameters.
globalThis.OperationDisplay = Object.freeze({
  describe({ capabilityName = "", label = "", display = {}, bindings = {}, parameters = {} } = {}) {
    const valueFor = (key) => {
      const binding = bindings[key];
      if (binding === undefined || binding === null) return `待补充 ${key}`;
      if (typeof binding !== "object") return String(binding);
      if ("value" in binding) return String(binding.value ?? "待补充");
      if (binding.parameter_ref) return parameters[binding.parameter_ref]?.value !== undefined
        ? String(parameters[binding.parameter_ref].value) : `待补充 ${binding.parameter_ref}`;
      if (binding.result_ref) return `前序反馈 ${binding.result_ref}`;
      if (binding.resource_ref) return `待绑定 ${binding.resource_ref}`;
      if (binding.object_ref) return `待绑定对象 ${binding.object_ref}`;
      if (binding.method_ref) return `待确认方法 ${binding.method_ref}`;
      return JSON.stringify(binding);
    };
    const title = String(display.title || label || capabilityName).replace(/\{\{([a-zA-Z0-9_]+)\}\}/g, (_, key) => valueFor(key));
    const fields = display.fields || Object.keys(bindings).map(argument => ({ argument, label: argument }));
    const summary = fields.map(field => `${field.label || field.argument}：${valueFor(field.argument)}${field.unit || ""}`).join("；");
    return { title, capabilityName, summary };
  },
  wrap(text, width = 24) {
    const lines = [];
    for (const paragraph of String(text).split("\n")) {
      let line = "", length = 0;
      for (const character of paragraph) {
        const size = character.charCodeAt(0) < 128 ? 0.55 : 1;
        if (length + size > width && line) { lines.push(line); line = ""; length = 0; }
        line += character;
        length += size;
      }
      lines.push(line);
    }
    return lines;
  }
});
