import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Request
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend import manual_import
from backend.planner.knowledge import KnowledgeStore


def text_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(300, 300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 200 Td (Click Results) Tj ET")
    page[NameObject("/Contents")] = stream
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def incoming(client="127.0.0.1", host="127.0.0.1:8877", **headers):
    return Request({"type": "http", "scheme": "http", "path": "/", "headers": [
        (key.encode(), value.encode()) for key, value in {"host": host, **headers}.items()
    ], "client": (client, 12345)})


class ManualImportTest(unittest.TestCase):
    def test_device_catalog_and_persistent_custom_registration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "MANUAL_IMPORT_DB": directory + "/devices.sqlite3",
        }):
            original = manual_import.devices()["devices"]
            self.assertIn("soxhlet", {item["id"] for item in original})
            self.assertEqual([item["id"] for item in original if item["manual_import_supported"]], ["vd10"])
            added = manual_import.add_device(manual_import.NewDevice(name=" Test  Device "))
            self.assertEqual(added["name"], "Test Device")
            self.assertFalse(added["manual_import_supported"])
            self.assertTrue(added["can_reuse_vd10"])
            self.assertTrue(added["is_new"])
            self.assertEqual(manual_import.published()["instruments"][0]["id"], added["id"])
            self.assertEqual(manual_import.devices()["devices"], [*original, added])
            for name in ("test device", original[0]["name"]):
                with self.assertRaises(HTTPException) as duplicate:
                    manual_import.add_device(manual_import.NewDevice(name=name))
                self.assertEqual(duplicate.exception.status_code, 409)
            with self.assertRaises(HTTPException) as unconfirmed:
                manual_import.save_pdf(b"fixture", "vd10.pdf", added["id"])
            self.assertEqual(unconfirmed.exception.status_code, 422)
            task = {"name": "查询", "inputs": "无", "outcome": "显示结果",
                    "steps": [{"name": "打开数据库", "section": "结果", "page": 1, "evidence": "打开数据库"}]}
            with patch.object(manual_import, "extract_candidates", return_value=[task]):
                batch = manual_import.save_pdf(b"fixture", "vd10.pdf", added["id"], True)["batch"]
            item, = manual_import.drafts(batch)["items"]
            oid = item["id"]
            manual_import.review_draft(oid, manual_import.Review(name="查询", description="显示结果", approve=True))
            manual_import.publish(oid)
            catalog = manual_import.published()
            self.assertEqual(catalog["meta_operations"][0]["instrument_id"], added["id"])
            self.assertEqual(catalog["instruments"][0]["name"], added["name"])
            with self.assertRaises(HTTPException):
                manual_import.set_scene(oid, manual_import.Enable(enabled=True))
            with self.assertRaises(HTTPException) as still_active:
                manual_import.archive_devices([added["id"]])
            self.assertEqual(still_active.exception.status_code, 409)
            with patch.object(manual_import, "extract_candidates", return_value=[task]):
                other_batch = manual_import.save_pdf(b"other fixture", "vd10.pdf", added["id"], True)["batch"]
            other = manual_import.drafts(other_batch)["items"][0]["id"]
            manual_import.review_draft(other, manual_import.Review(name="查询", description="显示结果", approve=True))
            manual_import.publish(other)
            manual_import.withdraw_operation(other)
            self.assertIn(added["id"], [device["id"] for device in manual_import.devices()["devices"]])
            manual_import.withdraw_operation(oid)
            self.assertEqual(manual_import.published()["instruments"], [])
            self.assertEqual(manual_import.devices()["devices"], original)
            self.assertEqual(manual_import.drafts(batch)["items"][0]["state"], "withdrawn")
            from contextlib import closing
            with closing(manual_import.db()) as conn, conn:
                conn.execute("DELETE FROM manual_device_archive WHERE device_id=?", (added["id"],))
                conn.execute("DELETE FROM manual_registry_migrations WHERE name='archive_withdrawn_devices'")
            self.assertEqual(manual_import.devices()["devices"], original)
            restored = manual_import.add_device(manual_import.NewDevice(name=added["name"]))
            self.assertTrue(restored["restored"])
            self.assertEqual(restored["id"], added["id"])
            self.assertEqual(manual_import.published()["meta_operations"], [])
            self.assertEqual(manual_import.published()["instruments"][0]["id"], added["id"])
            self.assertEqual(manual_import.drafts(batch)["items"][0]["state"], "withdrawn")

    def test_tokenless_mode_only_accepts_direct_same_origin_loopback(self):
        marker = {"x-manual-import": "1"}
        with patch.dict(os.environ, {"MANUAL_IMPORT_LOCAL_ACCESS": "1", "MANUAL_IMPORT_ADMIN_TOKEN": ""}):
            local = incoming(**marker, origin="http://127.0.0.1:8877")
            self.assertEqual(manual_import.access(local)["mode"], "local")
            manual_import.admin(local, "")
            for request in (incoming(), incoming(client="192.0.2.1", **marker),
                            incoming(host="external.example", **marker),
                            incoming(**marker, origin="http://127.0.0.1:9000"),
                            incoming(**marker, **{"sec-fetch-site": "cross-site"}),
                            incoming(**marker, **{"x-forwarded-for": "127.0.0.1"})):
                with self.assertRaises(HTTPException) as denied:
                    manual_import.admin(request, "")
                self.assertEqual(denied.exception.status_code, 403)
        with patch.dict(os.environ, {"MANUAL_IMPORT_LOCAL_ACCESS": "", "MANUAL_IMPORT_ADMIN_TOKEN": ""}):
            self.assertEqual(manual_import.access(local)["mode"], "disabled")
            with self.assertRaises(HTTPException):
                manual_import.admin(local, "")

    def test_review_publish_and_scene_isolation(self):
        base = KnowledgeStore().metadata()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "MANUAL_IMPORT_DB": directory + "/manual.sqlite3", "MANUAL_IMPORT_ADMIN_TOKEN": "test-token",
        }):
            with self.assertRaises(HTTPException) as denied:
                manual_import.admin(incoming(client="192.0.2.1"), "Bearer invalid")
            self.assertEqual(denied.exception.status_code, 403)
            manual_import.admin(incoming(client="192.0.2.1"), "Bearer test-token")
            self.assertEqual(manual_import.extract_candidates(text_pdf()), [])
            pages = [
                "打开……………30\n点击结果按钮",
                "结果数据库\n按下主菜单上的数据库按钮。完整的测试报告将随之显示。",
                "数据库检索结果\n选择所需字段并输入一个条件。",
            ]
            reader = SimpleNamespace(is_encrypted=False, pages=[
                SimpleNamespace(extract_text=lambda text=text: text) for text in pages])
            with patch("pypdf.PdfReader", return_value=reader):
                batch = manual_import.save_pdf(b"%PDF-fixture", "vd10.pdf")["batch"]
            from contextlib import closing
            with closing(manual_import.db()) as conn, conn:
                conn.execute("""INSERT INTO manual_candidates(id,batch,filename,sha256,page,evidence,name)
                              VALUES ('old','legacy','vd10.pdf','old',1,'点击','点击')""")
            self.assertEqual(manual_import.drafts()["batch"], batch)
            self.assertEqual(manual_import.drafts("legacy")["items"][0]["id"], "old")
            item, = manual_import.drafts(batch)["items"]
            self.assertEqual((item["page"], item["name"]), (2, "VD10检测结果查询"))
            self.assertEqual([step["page"] for step in item["details"]["steps"]], [2, 3, 2])
            oid = item["id"]
            with self.assertRaises(HTTPException) as pending:
                manual_import.publish(oid)
            self.assertEqual(pending.exception.status_code, 409)
            manual_import.review_draft(oid, manual_import.Review(
                name="打开结果页面", description="打开结果页面并等待显示", approve=True))
            self.assertEqual(manual_import.published()["meta_operations"], [])
            release = manual_import.publish_batch(batch)
            self.assertEqual(release["published"], 1)
            self.assertTrue(next(d for d in manual_import.devices()["devices"] if d["id"] == "vd10")["is_new"])
            operation, = manual_import.published()["meta_operations"]
            with patch.dict(os.environ, {"MANUAL_IMPORT_ADMIN_TOKEN": ""}):
                self.assertEqual(manual_import.published()["meta_operations"][0]["id"], oid)
            self.assertEqual(operation["execution_policy"], "interface_only")
            self.assertEqual(len(operation["operation_tree"]["children"]), 3)
            self.assertNotIn("evidence", operation["extensions"]["manual_import"])
            before = manual_import.preview()
            self.assertEqual(before["operations"], [])
            manual_import.set_scene(oid, manual_import.Enable(enabled=True))
            enabled = manual_import.preview()
            payload = manual_import.PreviewPlan(checksum=enabled["checksum"], operation_ids=[oid])
            plan = manual_import.preview_plan(payload)
            self.assertFalse(plan["execution_allowed"])
            self.assertEqual(plan["steps"][0]["operation_id"], item["id"])
            self.assertEqual(KnowledgeStore().metadata(), base)
            manual_import.set_scene(oid, manual_import.Enable(enabled=False))
            with self.assertRaises(HTTPException) as stale:
                manual_import.preview_plan(payload)
            self.assertEqual(stale.exception.status_code, 409)
            manual_import.set_scene(oid, manual_import.Enable(enabled=True))
            with patch("pypdf.PdfReader", return_value=reader):
                other_batch = manual_import.save_pdf(b"%PDF-other", "vd10.pdf")["batch"]
            other = manual_import.drafts(other_batch)["items"][0]["id"]
            manual_import.review_draft(other, manual_import.Review(name="另一次发布", description="独立条目", approve=True))
            other_release = manual_import.publish(other)
            self.assertNotEqual(release["release_id"], other_release["release_id"])
            self.assertEqual(manual_import.withdraw_release(release["release_id"])["withdrawn"], 1)
            self.assertEqual(manual_import.preview()["operations"], [])
            self.assertEqual([op["id"] for op in manual_import.published()["meta_operations"]], [other])
            history = {r["id"]: r for r in manual_import.releases()["releases"]}
            self.assertTrue(history[release["release_id"]]["items"][0]["withdrawn_at"])
            saved = manual_import.drafts(batch)["items"][0]
            self.assertEqual(saved["state"], "withdrawn")
            self.assertTrue(saved["approved_steps"])
            self.assertTrue(saved["details"]["steps"][0]["evidence"])
            self.assertEqual(manual_import.withdraw_operation(other)["withdrawn"], 1)
            self.assertEqual(manual_import.published()["meta_operations"], [])
            self.assertFalse(next(d for d in manual_import.devices()["devices"] if d["id"] == "vd10")["is_new"])
            with self.assertRaises(HTTPException):
                manual_import.withdraw_operation(other)
            self.assertEqual(KnowledgeStore().metadata(), base)
        self.assertEqual(KnowledgeStore().metadata(), base)
