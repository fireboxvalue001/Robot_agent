"use strict";

const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const library = JSON.parse(
  fs.readFileSync(path.join(root, "data", "meta-operations.json"), "utf8")
);
const spatialLibrary = JSON.parse(
  fs.readFileSync(path.join(root, "data", "spatial-locations.json"), "utf8")
);

const categories = new Set(["instrument", "robot", "lab"]);
const statuses = new Set(["draft", "pending_verification", "verified", "interface_only", "disabled"]);
const ids = new Set();
const preconditionIds = new Set(library.preconditions.map((item) => item.id));

assert(library.schema_version === "1.3.0", "unexpected schema version");
assert(library.categories.length === 3, "the library must declare exactly three categories");
assert(library.instruments.length === 2, "the library must declare its instrument groups");
assert(library.meta_operations.length === 35, "the catalog should contain 35 meta operations");
assert(library.meta_operations.filter((item) => item.category === "instrument").length === 7, "instrument catalog should contain 7 operations");
assert(library.meta_operations.filter((item) => item.category === "robot").length === 24, "robot catalog should contain 24 operations");
assert(library.meta_operations.filter((item) => item.category === "lab").length === 4, "lab catalog should contain 4 operations");

const instrumentIds = new Set(library.instruments.map((item) => item.id));
assert(instrumentIds.has("vd10"), "VD10 instrument group is missing");
assert(instrumentIds.has("generic"), "generic instrument group is missing");

for (const operation of library.meta_operations) {
  assert(operation.id && !ids.has(operation.id), `duplicate or empty id: ${operation.id}`);
  ids.add(operation.id);
  assert(categories.has(operation.category), `invalid category: ${operation.id}`);
  if (operation.category === "instrument") {
    assert(instrumentIds.has(operation.instrument_id), `unknown instrument group: ${operation.id}`);
  }
  assert(statuses.has(operation.status), `invalid status: ${operation.id}`);
  assert(operation.inputs?.type === "object", `missing input schema: ${operation.id}`);
  assert(operation.outputs?.type === "object", `missing output schema: ${operation.id}`);
  assert(operation.source?.reference, `missing source reference: ${operation.id}`);
  assert(operation.operation_tree?.children?.length > 0, `empty operation tree: ${operation.id}`);
  assert(Array.isArray(operation.physical_requirements), `invalid physical requirements: ${operation.id}`);
  assert(operation.capability_boundary?.allowed, `missing capability boundary: ${operation.id}`);
  assert(operation.failure_policy?.default_action, `missing failure policy: ${operation.id}`);
  for (const preconditionRef of operation.precondition_refs || []) {
    assert(preconditionIds.has(preconditionRef), `unknown precondition reference: ${operation.id}/${preconditionRef}`);
  }
  for (const node of operation.operation_tree.children) {
    assert(node.type === "atomic_node", `invalid node type: ${operation.id}/${node.instance_id}`);
    assert(node.node_ref && node.name && node.source_type, `incomplete node: ${operation.id}/${node.instance_id}`);
  }
}

assert(ids.has("robot.meta.aliquot_sample"), "sample aliquoting operation is missing");
assert(ids.has("robot.meta.register_tube_pose"), "tube registration operation is missing");
assert(ids.has("vd10.meta.sample_test"), "VD10 sample test interface is missing");
assert(ids.has("robot.meta.transfer_object"), "physical object transfer operation is missing");
assert(ids.has("robot.meta.heat_sample"), "sample heating operation is missing");
assert(ids.has("robot.meta.mix_sample"), "sample mixing operation is missing");
assert(ids.has("robot.meta.hold_sample"), "sample holding operation is missing");
assert(ids.has("robot.meta.receive_and_register_sample"), "sample registration operation is missing");
assert(ids.has("robot.meta.condition_sample_water_bath"), "water-bath conditioning operation is missing");
assert(ids.has("robot.meta.filter_sample"), "sample filtering operation is missing");
assert(ids.has("robot.meta.degas_sample"), "sample degassing operation is missing");
assert(ids.has("instrument.meta.prepare_test_method"), "test-method preparation operation is missing");
assert(ids.has("instrument.meta.run_registered_project_test"), "registered project test interface is missing");
assert(ids.has("robot.meta.collect_sample"), "sample collection operation is missing");
assert(ids.has("robot.meta.seal_and_label_sample"), "sample sealing operation is missing");
assert(ids.has("robot.meta.inspect_sample_appearance"), "sample visual inspection operation is missing");
assert(ids.has("robot.meta.load_unload_processing_device"), "processing-device handling operation is missing");
assert(ids.has("lab.meta.resolve_test_destination"), "test destination routing operation is missing");
assert(ids.has("lab.meta.confirm_sample_handoff"), "sample handoff boundary is missing");
for (const operationId of [
  "robot.meta.heat_sample",
  "robot.meta.mix_sample",
  "robot.meta.hold_sample",
  "robot.meta.read_result_from_lims",
  "robot.meta.read_result_from_screen"
]) {
  assert(
    library.meta_operations.find((item) => item.id === operationId)?.category === "robot",
    `${operationId} must be classified as a robot operation`
  );
}
for (const operationId of ["vd10.meta.query_test_results", "vd10.meta.inspect_quality_status"]) {
  const operation = library.meta_operations.find((item) => item.id === operationId);
  assert(operation?.category === "instrument", `${operationId} must be an instrument operation`);
  assert(operation?.instrument_id === "vd10", `${operationId} must belong to VD10`);
}
assert(
  library.meta_operations.find((item) => item.id === "lab.meta.transfer_sample_by_agv")?.category === "lab",
  "AGV inter-station sample transport must be classified as a laboratory environment operation"
);
assert(
  library.meta_operations.find((item) => item.id === "vd10.meta.sample_test").status === "interface_only",
  "VD10 sample test must remain interface-only"
);
assert(
  library.meta_operations.find((item) => item.id === "lab.meta.confirm_sample_handoff").execution_policy === "interface_only",
  "human sample handoff must remain an interface-only boundary"
);
assert(
  library.meta_operations.find((item) => item.id === "instrument.meta.run_registered_project_test").execution_policy === "interface_only",
  "unbound external tests must remain interface-only"
);
for (const operationId of [
  "robot.meta.receive_and_register_sample",
  "robot.meta.condition_sample_water_bath",
  "robot.meta.filter_sample",
  "robot.meta.degas_sample",
  "instrument.meta.prepare_test_method",
  "instrument.meta.run_registered_project_test",
  "robot.meta.collect_sample",
  "robot.meta.seal_and_label_sample",
  "robot.meta.inspect_sample_appearance",
  "robot.meta.load_unload_processing_device",
  "lab.meta.resolve_test_destination",
  "lab.meta.confirm_sample_handoff"
]) {
  const plannerContract = library.meta_operations.find((item) => item.id === operationId)?.extensions?.planner_contract;
  assert(plannerContract?.consumes?.length > 0, `missing planner consumes contract: ${operationId}`);
  assert(plannerContract?.produces?.length > 0, `missing planner produces contract: ${operationId}`);
}

for (const legacyId of [
  "instrument.meta.operate_industrial_pc",
  "instrument.meta.read_result_from_lims",
  "instrument.meta.read_result_from_screen",
  "instrument.meta.generate_word_report",
  "instrument.meta.heat_sample",
  "instrument.meta.mix_sample",
  "instrument.meta.hold_sample",
  "instrument.meta.receive_and_register_sample",
  "instrument.meta.condition_sample_water_bath",
  "instrument.meta.filter_sample",
  "instrument.meta.degas_sample",
  "vd10.meta.query_results",
  "vd10.meta.inspect_quality",
  "robot.meta.read_vd10_results",
  "robot.meta.read_vd10_quality_status",
  "robot.meta.transfer_sample_by_agv"
]) {
  assert(!ids.has(legacyId), `legacy meta-operation id must not remain: ${legacyId}`);
}

const locationIds = new Set(spatialLibrary.locations.map((location) => location.id));
const locationsById = new Map(spatialLibrary.locations.map((location) => [location.id, location]));
assert(spatialLibrary.schema_version === "1.1.0", "unexpected spatial library schema version");
assert(spatialLibrary.coordinate_frame.origin_description.includes("一楼"), "building origin must be the first-floor wall corner");
assert(spatialLibrary.building.floor_count === 3, "the temporary building model should contain three floors");
assert(spatialLibrary.building.floor_height_m === 3.6, "temporary floor height should be 3.6 m");
assert(spatialLibrary.building.floor_height_status === "placeholder", "temporary floor height must be marked as a placeholder");
assert(spatialLibrary.locations.length === 5, "the spatial registry should contain five locations");
assert(locationIds.has("lab.location.vd10_station"), "VD10 spatial location is missing");
assert(locationIds.has("lab.location.sample_checkin_station"), "sample check-in spatial location is missing");
assert(locationIds.has("lab.location.vd10_support_table"), "VD10 support table is missing");
assert(locationIds.has("lab.location.elevator_lobby_floor1"), "first-floor elevator stop is missing");
assert(locationIds.has("lab.location.elevator_lobby_floor3"), "third-floor elevator stop is missing");

const workbench = locationsById.get("lab.location.sample_checkin_station");
assert(workbench.pose.x === 1.025, "workbench X coordinate should be converted from 102.5 cm");
assert(workbench.pose.y === 2.93, "workbench Y coordinate should be converted from 293 cm");
assert(workbench.geometry.length_m === 1.75, "workbench length should be converted from 175 cm");
assert(workbench.geometry.width_m === 0.75, "workbench width should be converted from 75 cm");
assert(workbench.geometry.height_m === 0.763, "workbench height should be converted from 76.3 cm");
assert(workbench.placeholder === false, "user-provided workbench data must not be labelled as assumed data");
assert(workbench.status === "pending_calibration", "workbench must remain pending calibration");

const vd10 = locationsById.get("lab.location.vd10_station");
assert(vd10.floor === "3楼", "VD10 must be registered on the third floor");
assert(vd10.support_location_id === "lab.location.vd10_support_table", "VD10 must reference its support table");
assert(vd10.placeholder === true, "temporary VD10 coordinates must remain explicit placeholders");

assert(spatialLibrary.transport_links.length === 1, "one elevator route should be registered");
const elevatorRoute = spatialLibrary.transport_links[0];
assert(
  locationsById.get(elevatorRoute.from_location_id)?.floor === "1楼" &&
    locationsById.get(elevatorRoute.to_location_id)?.floor === "3楼",
  "elevator route must connect floor 1 to floor 3"
);
assert(elevatorRoute.waypoints.includes("lab.location.elevator_lobby_floor1"), "elevator route must include the floor-1 stop");
assert(elevatorRoute.waypoints.includes("lab.location.elevator_lobby_floor3"), "elevator route must include the floor-3 stop");
assert(elevatorRoute.status === "placeholder", "temporary elevator route must remain a placeholder");
for (const location of spatialLibrary.locations) {
  assert(location.replace_before_execution === true, `${location.id} must block physical execution`);
}

console.log("meta-operation library structure test passed");

function assert(condition, message) {
  if (!condition) {
    console.error(`FAILED: ${message}`);
    process.exit(1);
  }
}
