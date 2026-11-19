"""Reviewed manual additions, isolated from the production planner library."""
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parent.parent
SCENE = "vd10_single_sample_demo"
LIMIT = 10 * 1024 * 1024
router = APIRouter(prefix="/api/v1/manual-capabilities", tags=["manual-capabilities"])


def local_access(request: Request):
    hosts = {"127.0.0.1", "::1", "localhost"}
    if (os.environ.get("MANUAL_IMPORT_LOCAL_ACCESS") != "1"
            or not request.client or request.client.host not in {"127.0.0.1", "::1"}
            or request.url.hostname not in hosts
            or any(key == "forwarded" or key.startswith("x-forwarded-") for key in request.headers)):
        return False
    origin = request.headers.get("origin")
    return (request.headers.get("sec-fetch-site") in {None, "same-origin"}
            and (origin is None or origin == f"{request.url.scheme}://{request.url.netloc}"))


@router.get("/access")
def access(request: Request):
    mode = "local" if local_access(request) else "token" if os.environ.get("MANUAL_IMPORT_ADMIN_TOKEN") else "disabled"
    return {"mode": mode}


def admin(request: Request, authorization: str = Header(default="")):
    if local_access(request) and request.headers.get("x-manual-import") == "1":
        return
    token = os.environ.get("MANUAL_IMPORT_ADMIN_TOKEN", "")
    if not token:
        raise HTTPException(403, "只能从本机演示页面免令牌操作，远程管理需要管理员令牌。")
    if not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
        raise HTTPException(403, "管理员令牌无效。")


def db_path():
    return Path(os.environ.get("MANUAL_IMPORT_DB") or ROOT / "data/execution_history/manual-capabilities.sqlite3")


def db():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_candidates (
        id TEXT PRIMARY KEY, batch TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
        page INTEGER NOT NULL, evidence TEXT NOT NULL, name TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'draft', operation TEXT, scene TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_task_details (
        id TEXT PRIMARY KEY, details TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_devices (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_device_archive (
        device_id TEXT PRIMARY KEY, archived_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_releases (
        id INTEGER PRIMARY KEY, batch TEXT NOT NULL, published_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_release_members (
        candidate_id TEXT PRIMARY KEY, release_id INTEGER NOT NULL, withdrawn_at TEXT)""")
    conn.execute("CREATE TABLE IF NOT EXISTS manual_registry_migrations (name TEXT PRIMARY KEY)")
    if not conn.execute("SELECT 1 FROM manual_registry_migrations WHERE name='archive_withdrawn_devices'").fetchone():
        with conn:
            claimed = conn.execute("INSERT OR IGNORE INTO manual_registry_migrations VALUES ('archive_withdrawn_devices')")
            if claimed.rowcount:
                archive_withdrawn_devices(conn, now())
    return conn


def archive_withdrawn_devices(conn, timestamp, device_id=None):
    conn.execute("""INSERT OR IGNORE INTO manual_device_archive(device_id, archived_at)
        SELECT d.id, ? FROM manual_devices d
        WHERE (? IS NULL OR d.id = ?)
          AND EXISTS (SELECT 1 FROM manual_candidates c
            WHERE substr(c.id, 1, length(d.id) + 1) = d.id || '.' AND c.state='withdrawn')
          AND NOT EXISTS (SELECT 1 FROM manual_candidates c
            WHERE substr(c.id, 1, length(d.id) + 1) = d.id || '.' AND c.state='published')""",
        (timestamp, device_id, device_id))


VD10_TASKS = (
    ("VD10测试信息准备", "样品 ID、操作员及测试方法或预设", "测试表单已填写，可核对必填信息",
     (("测试模式", "按下主菜单", "进入 VD10 测试界面"),
      ("测试模式", "首先从预编程列表中选择其名称，输入样品ID", "填写样品 ID 并选择操作员"),
      ("测试模式", "通过选择测试方法和组或使用预编程配置文件", "选择测试方法和分组，或选择预设"),
      ("测试设置控制", "按键变为激活", "核对必填信息和设备就绪状态，确认开始按钮可用；不启动测试"))),
    ("VD10检测结果查询", "样品 ID、日期或操作员等检索条件", "显示指定测试报告的详情",
     (("结果数据库", "按下主菜单上的", "打开结果数据库"),
      ("数据库检索结果", "选择所需字段并输入一个条件", "选择检索字段并填写条件"),
      ("结果数据库", "报告将随之显示", "打开匹配结果并查看报告详情"))),
    ("VD10质量状态检查", "待查看的 VD10 仪器", "看见传感器校准或验证状态及质控样有效性",
     (("质量控制菜单", "要访问质量菜单", "进入质量控制菜单"),
      ("质量控制菜单", "所有传感器当前校准/验证状态", "读取传感器状态和质控样有效性"))),
    ("VD10测试报告导出到USB", "已有测试结果、USB 存储设备", "测试报告保存到 USB",
     (("结果数据库", "报告将随之显示", "从结果数据库打开要导出的报告"),
      ("以ASCII格式的USB数据存储", "将测试报告以 ASCII文本文件", "将当前报告保存为 USB 上的文本文件"))),
)


def base_devices():
    return json.loads((ROOT / "data/meta-operations.json").read_bytes())["instruments"]


def device_entry(device_id, name):
    return {"id": device_id, "name": name, "manual_import_supported": device_id == "vd10",
            "can_reuse_vd10": device_id.startswith("manual_device_"),
            "is_new": device_id.startswith("manual_device_")}


@router.get("/devices")
def devices():
    entries = [device_entry(item["id"], item["name"]) for item in base_devices()]
    if db_path().is_file():
        with closing(db()) as conn:
            entries.extend(device_entry(row["id"], row["name"])
                           for row in conn.execute("""SELECT id,name FROM manual_devices
                               WHERE id NOT IN (SELECT device_id FROM manual_device_archive) ORDER BY rowid"""))
            changed = {json.loads(row["operation"])["instrument_id"] for row in
                       conn.execute("SELECT operation FROM manual_candidates WHERE state='published'")}
        for entry in entries:
            entry["is_new"] |= entry["id"] in changed
    return {"devices": entries}


def archive_devices(device_ids):
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        for device_id in device_ids:
            if not conn.execute("SELECT 1 FROM manual_devices WHERE id=?", (device_id,)).fetchone():
                raise HTTPException(404, "不是已登记的扩展设备。")
            active = conn.execute("""SELECT 1 FROM manual_candidates
                WHERE substr(id, 1, length(?) + 1) = ? || '.'
                AND state IN ('draft', 'approved', 'published') LIMIT 1""", (device_id, device_id)).fetchone()
            if active:
                raise HTTPException(409, "设备仍有待审核、待发布或已发布的元操作。")
            conn.execute("INSERT OR IGNORE INTO manual_device_archive VALUES (?,?)", (device_id, now()))


class NewDevice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)


@router.post("/devices", dependencies=[Depends(admin)], status_code=201)
def add_device(request: NewDevice):
    name = " ".join(request.name.split())
    key = name.casefold()
    if any(" ".join(item["name"].split()).casefold() == key for item in base_devices()):
        raise HTTPException(409, "已有同名设备，请从列表中选择。")
    device = device_entry("manual_device_" + uuid.uuid4().hex, name)
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT id,name FROM manual_devices WHERE name_key=?", (key,)).fetchone()
        if existing is None:
            conn.execute("INSERT INTO manual_devices(id,name,name_key) VALUES (?,?,?)", (device["id"], name, key))
        else:
            restored = conn.execute("DELETE FROM manual_device_archive WHERE device_id=?", (existing["id"],))
            if not restored.rowcount:
                raise HTTPException(409, "已有同名设备，请从列表中选择。")
            device = {**device_entry(existing["id"], existing["name"]), "restored": True}
    return device


def extract_candidates(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted or len(reader.pages) > 150:
        raise ValueError("仅支持未加密、最多150页的 PDF。")
    pages = []
    for number, page in enumerate(reader.pages, 1):
        lines = [line.strip() for line in (page.extract_text() or "").splitlines()]
        body = " ".join(line for line in lines if line and not re.search(r"[.．·…]{4,}", line))
        pages.append((number, set(lines), body))
    candidates = []
    for name, inputs, outcome, rules in VD10_TASKS:
        steps = []
        for section, anchor, label in rules:
            match = next(((number, body, body.index(anchor)) for number, headings, body in pages
                          if section in headings and anchor in body), None)
            if not match:
                break
            number, body, position = match
            start = max(body.rfind("。", 0, position) + 1, position - 100)
            end = body.find("。", position)
            excerpt = body[start:min(end + 1 if end >= 0 else len(body), position + 160)].strip()
            steps.append({"name": label, "section": section, "page": number, "evidence": excerpt})
        else:
            candidates.append({"name": name, "inputs": inputs, "outcome": outcome, "steps": steps})
    return candidates


def save_pdf(content, filename, device="vd10", use_vd10_manual=False):
    target = next((item for item in devices()["devices"] if item["id"] == device), None)
    if not target or not (target["manual_import_supported"] or
                          (target["can_reuse_vd10"] and use_vd10_manual)):
        raise HTTPException(422, "所选设备不支持当前解析规则，或尚未批准该设备使用此说明书。")
    try:
        candidates = extract_candidates(content)
    except ImportError as exc:
        raise HTTPException(503, "未安装 PDF 读取组件。") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, "无法读取该 PDF。") from exc
    if not candidates:
        raise HTTPException(422, "未找到有完整章节依据的 VD10 任务。请上传带文字层的受支持说明书；不会用零碎按钮文字生成草稿。")
    batch = uuid.uuid4().hex
    digest = hashlib.sha256(content).hexdigest()
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM manual_device_archive WHERE device_id=?", (device,)).fetchone():
            raise HTTPException(422, "所选设备已归档，请重新选择。")
        for item in candidates:
            oid = f"{device}.meta.manual_{uuid.uuid4().hex}"
            item.update(device_id=device, device_name=target["name"])
            first = item["steps"][0]
            conn.execute("INSERT INTO manual_candidates(id,batch,filename,sha256,page,evidence,name) VALUES (?,?,?,?,?,?,?)",
                         (oid, batch, filename, digest, first["page"], first["evidence"], item["name"]))
            conn.execute("INSERT INTO manual_task_details VALUES (?,?)", (oid, json.dumps(item, ensure_ascii=False)))
    return {"batch": batch}


@router.post("/drafts", dependencies=[Depends(admin)])
async def upload(document: UploadFile = File(...), device: str = Form(default="vd10"),
                 use_vd10_manual: bool = Form(default=False)):
    filename = (document.filename or "").replace("\\", "/").rsplit("/", 1)[-1][:200]
    content = await document.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise HTTPException(413, "PDF 超过 10 MB。")
    if not filename.lower().endswith(".pdf") or not content.startswith(b"%PDF-"):
        raise HTTPException(422, "请上传有效的 PDF。")
    return await run_in_threadpool(save_pdf, content, filename, device, use_vd10_manual)


@router.get("/drafts", dependencies=[Depends(admin)])
def drafts(batch: str | None = None):
    with closing(db()) as conn:
        if batch is None:
            row = conn.execute("""SELECT c.batch FROM manual_candidates c
                                JOIN manual_task_details d ON c.id=d.id
                                ORDER BY c.rowid DESC LIMIT 1""").fetchone()
            batch = row["batch"] if row else ""
        rows = conn.execute("""SELECT c.id,filename,page,evidence,name,state,scene,operation,d.details,m.release_id
                            FROM manual_candidates c LEFT JOIN manual_task_details d ON c.id=d.id
                            LEFT JOIN manual_release_members m ON c.id=m.candidate_id
                            WHERE c.batch=? ORDER BY c.rowid""",
                            (batch,)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        details = json.loads(item.pop("details")) if row["details"] else None
        approved = item.pop("operation")
        item["details"] = details
        if approved:
            operation = json.loads(approved)
            item["approved_steps"] = [step["name"] for step in operation["operation_tree"]["children"]]
            item["approved_description"] = operation["description"]
        items.append(item)
    return {"batch": batch, "items": items}


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=600)
    approve: bool
    steps: list[str] | None = Field(default=None, min_length=1, max_length=15)


def make_operation(row, review, details):
    oid = row["id"]
    return {
        "id": oid, "version": "1.0.0", "name": review.name, "description": review.description,
        "category": "instrument", "instrument_id": details.get("device_id", "vd10"), "status": "pending_verification",
        "execution_policy": "interface_only",
        "source": {"type": "electronic_manual", "reference": row["filename"],
                   "sections": list(dict.fromkeys(f"{s['section']}（第{s['page']}页）" for s in details["steps"]))},
        "inputs": {"type": "object", "properties": {}}, "outputs": {"type": "object", "properties": {}},
        "input_hint": details["inputs"], "output_hint": details["outcome"] + "；实机反馈待核对",
        "operation_tree": {"type": "sequence", "children": [{
            "instance_id": f"action_{index:02d}", "type": "atomic_node",
            "node_ref": oid.replace(".meta.", ".action.") + f".{index}",
            "name": name, "source_type": "reserved_interface", "execution_policy": "interface_only",
        } for index, name in enumerate(review.steps or [s["name"] for s in details["steps"]], 1)]},
        "physical_requirements": ["核对设备型号、对象、控制接口及实际反馈"],
        "capability_boundary": {"allowed": ["人工审阅与编排预览"], "forbidden": ["下发设备指令", "将说明书审核当成实机验证"]},
        "failure_policy": {"default_action": "stop", "max_retries": 0},
        "extensions": {"manual_import": {
            "sha256": row["sha256"], "page": row["page"], "evidence": details["steps"]}},
    }


@router.post("/drafts/{oid}/review", dependencies=[Depends(admin)])
def review_draft(oid: str, review: Review):
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM manual_candidates WHERE id=?", (oid,)).fetchone()
        if not row or row["state"] != "draft":
            raise HTTPException(409, "条目不存在或已审核。")
        task = conn.execute("SELECT details FROM manual_task_details WHERE id=?", (oid,)).fetchone()
        if review.approve and not task:
            raise HTTPException(409, "此条是旧版碎片草稿，请重新导入说明书。")
        if review.approve and review.steps and any(not step.strip() or len(step) > 150 for step in review.steps):
            raise HTTPException(422, "操作步骤不得为空或超过150字。")
        operation = make_operation(row, review, json.loads(task["details"])) if review.approve else None
        if operation:
            base = json.loads((ROOT / "data/meta-operations.json").read_bytes())
            if any(item["id"] == oid for item in base["meta_operations"]):
                raise HTTPException(409, "能力 ID 与基础库冲突。")
            base["meta_operations"].append(operation)
            schema = json.loads((ROOT / "schemas/meta-operation-library.schema.json").read_bytes())
            if not Draft202012Validator(schema).is_valid(base):
                raise HTTPException(422, "候选能力未通过结构校验。")
        state = "approved" if operation else "rejected"
        conn.execute("UPDATE manual_candidates SET state=?, name=?, operation=? WHERE id=?",
                     (state, review.name, json.dumps(operation, ensure_ascii=False) if operation else None, oid))
    return {"state": state}


def now():
    return datetime.now(timezone.utc).isoformat()


def create_release(conn, batch, ids, published_at):
    release_id = conn.execute("INSERT INTO manual_releases(batch,published_at) VALUES (?,?)",
                              (batch, published_at)).lastrowid
    conn.executemany("INSERT INTO manual_release_members(candidate_id,release_id) VALUES (?,?)",
                     [(oid, release_id) for oid in ids])
    return release_id


def register_legacy_releases(conn):
    batches = {}
    for row in conn.execute("""SELECT c.id,c.batch FROM manual_candidates c
                            LEFT JOIN manual_release_members m ON m.candidate_id=c.id
                            WHERE c.state='published' AND m.candidate_id IS NULL ORDER BY c.rowid"""):
        batches.setdefault(row["batch"], []).append(row["id"])
    for batch, ids in batches.items():
        create_release(conn, batch, ids, None)


def publish_items(field, key):
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        register_legacy_releases(conn)
        selector = "c.id=?" if field == "id" else "c.batch=?"
        rows = conn.execute(f"""SELECT c.id,c.batch,d.details FROM manual_candidates c
                            JOIN manual_task_details d ON c.id=d.id
                            WHERE {selector} AND c.state='approved'""", (key,)).fetchall()
        if not rows:
            raise HTTPException(409, "仅审核通过且尚未发布的条目可以发布。")
        target = json.loads(rows[0]["details"]).get("device_id", "vd10")
        if conn.execute("SELECT 1 FROM manual_device_archive WHERE device_id=?", (target,)).fetchone():
            raise HTTPException(409, "设备已移除，请先用同名设备重新登记再发布。")
        ids = [row["id"] for row in rows]
        release_id = create_release(conn, rows[0]["batch"], ids, now())
        conn.executemany("UPDATE manual_candidates SET state='published' WHERE id=?", [(oid,) for oid in ids])
        return {"state": "published", "published": len(ids), "release_id": release_id}


@router.post("/drafts/{oid}/publish", dependencies=[Depends(admin)])
def publish(oid: str):
    return publish_items("id", oid)


@router.post("/batches/{batch}/publish", dependencies=[Depends(admin)])
def publish_batch(batch: str):
    return publish_items("batch", batch)


@router.get("/releases", dependencies=[Depends(admin)])
def releases():
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        register_legacy_releases(conn)
        records = {}
        for row in conn.execute("""SELECT r.id,r.batch,r.published_at,c.id AS operation_id,c.name,c.state,m.withdrawn_at
                                FROM manual_releases r JOIN manual_release_members m ON m.release_id=r.id
                                JOIN manual_candidates c ON c.id=m.candidate_id ORDER BY r.id DESC,c.rowid"""):
            record = records.setdefault(row["id"], {**{k: row[k] for k in ("id", "batch", "published_at")}, "items": []})
            record["items"].append({k: row[k] for k in ("operation_id", "name", "state", "withdrawn_at")})
    return {"releases": list(records.values())}


def withdraw_items(release_id=None, oid=None):
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        register_legacy_releases(conn)
        selector, key = ("m.release_id", release_id) if oid is None else ("m.candidate_id", oid)
        rows = conn.execute(f"""SELECT c.id FROM manual_release_members m JOIN manual_candidates c ON c.id=m.candidate_id
                            WHERE {selector}=? AND c.state='published'""", (key,)).fetchall()
        if not rows:
            raise HTTPException(409, "没有仍在发布状态的条目可撤回。")
        timestamp = now()
        conn.executemany("UPDATE manual_candidates SET state='withdrawn',scene=NULL WHERE id=?",
                         [(row["id"],) for row in rows])
        conn.executemany("UPDATE manual_release_members SET withdrawn_at=? WHERE candidate_id=?",
                         [(timestamp, row["id"]) for row in rows])
        for device_id in {row["id"].partition(".")[0] for row in rows}:
            archive_withdrawn_devices(conn, timestamp, device_id)
    return {"withdrawn": len(rows)}


@router.post("/releases/{release_id}/withdraw", dependencies=[Depends(admin)])
def withdraw_release(release_id: int):
    return withdraw_items(release_id=release_id)


@router.post("/drafts/{oid}/withdraw", dependencies=[Depends(admin)])
def withdraw_operation(oid: str):
    return withdraw_items(oid=oid)


class Enable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


@router.put("/scenarios/vd10_single_sample_demo/{oid}", dependencies=[Depends(admin)])
def set_scene(oid: str, request: Enable):
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT operation FROM manual_candidates WHERE id=? AND state='published'", (oid,)).fetchone()
        if request.enabled and row and json.loads(row["operation"])["instrument_id"] != "vd10":
            raise HTTPException(422, "新增设备不能加入原 VD10 草案预览。")
        updated = conn.execute("UPDATE manual_candidates SET scene=? WHERE id=? AND state='published'",
                               (SCENE if request.enabled else None, oid))
        if not updated.rowcount:
            raise HTTPException(409, "只能启用已发布条目。")
    return {"scenario_id": SCENE, "enabled": request.enabled}


def published_rows():
    with closing(db()) as conn:
        return conn.execute("SELECT operation, scene FROM manual_candidates WHERE state='published' ORDER BY id").fetchall()


@router.get("/published")
def published():
    if not db_path().is_file():
        return {"meta_operations": []}
    items = []
    for row in published_rows():
        operation = json.loads(row["operation"])
        operation["extensions"]["manual_import"]["preview_enabled"] = row["scene"] == SCENE
        # The public catalog does not disclose uploaded manual excerpts.
        operation["extensions"]["manual_import"].pop("evidence")
        items.append(operation)
    instruments = [{"id": device["id"], "name": device["name"], "status": "interface_only"}
                   for device in devices()["devices"] if device["can_reuse_vd10"]]
    return {"meta_operations": items, "instruments": instruments}


@router.get("/scenarios/vd10_single_sample_demo/preview", dependencies=[Depends(admin)])
def preview():
    items = [json.loads(row["operation"]) for row in published_rows() if row["scene"] == SCENE]
    snapshot = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    return {"scenario_id": SCENE, "checksum": "sha256:" + snapshot,
            "execution_allowed": False, "operations": items}


class PreviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    checksum: str
    operation_ids: list[str] = Field(min_length=1, max_length=30)


@router.post("/scenarios/vd10_single_sample_demo/preview", dependencies=[Depends(admin)])
def preview_plan(request: PreviewPlan):
    snapshot = preview()
    if request.checksum != snapshot["checksum"]:
        raise HTTPException(409, "启用的能力已变化，请重新加载预览快照。")
    by_id = {op["id"]: op for op in snapshot["operations"]}
    if any(oid not in by_id for oid in request.operation_ids):
        raise HTTPException(422, "草案只能引用本场景已启用的说明书能力。")
    steps = [{"index": index, "operation_id": oid, "operation_version": by_id[oid]["version"],
              "name": by_id[oid]["name"], "status": "needs_hardware_verification"}
             for index, oid in enumerate(request.operation_ids, 1)]
    return {"scenario_id": SCENE, "checksum": snapshot["checksum"], "execution_allowed": False,
            "status": "preview_only", "steps": steps}
