import unittest

from backend.planning_service import plan_natural_language
from backend.server import NaturalLanguagePlanningRequest, plan_from_natural_language


def operation_ids(result):
    return [
        operation["metaOperationId"]
        for operation in result.get("operationChain", {}).get("operations", [])
    ]


class NaturalLanguagePlanningTests(unittest.TestCase):
    def test_vd10_text_generates_standard_ordered_operation_chain(self):
        result = plan_natural_language(
            "将桌上的样品分成4份，每份25ml，分别送到四个VD10仪器中进行检测"
        )

        self.assertEqual(result["type"], "planner_result")
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["workflowId"].startswith("wf_"))
        self.assertTrue(result["operationChain"]["planId"].startswith("plan_"))
        self.assertEqual(result["operationChain"]["capabilityLibrary"]["id"], "autolab.vd10.meta_operations")
        self.assertEqual(operation_ids(result), [
            "robot.meta.aliquot_sample",
            "robot.meta.load_tube_to_agv",
            "lab.meta.cross_zone_transport",
            "lab.meta.transfer_sample_by_agv",
            "robot.meta.prepare_and_load_instrument",
            "vd10.meta.sample_test",
            "vd10.meta.query_test_results",
            "robot.meta.read_result_from_screen",
        ])
        operations = result["operationChain"]["operations"]
        self.assertEqual(operations[0]["arguments"]["target_count"], 4)
        self.assertEqual(operations[0]["arguments"]["volume_each"], 25)
        self.assertEqual(operations[0]["dependsOn"], [])
        self.assertEqual(operations[-1]["dependsOn"], [operations[-2]["stepId"]])

    def test_processing_steps_follow_natural_language_order(self):
        result = plan_natural_language(
            "将样品加热到40度，持续10分钟，再摇匀30秒后送到VD10检测"
        )

        self.assertEqual(result["status"], "success")
        ids = operation_ids(result)
        self.assertLess(ids.index("robot.meta.heat_sample"), ids.index("robot.meta.mix_sample"))
        heating = result["operationChain"]["operations"][ids.index("robot.meta.heat_sample")]
        mixing = result["operationChain"]["operations"][ids.index("robot.meta.mix_sample")]
        self.assertEqual(heating["arguments"]["temperature_c"], 40)
        self.assertEqual(heating["arguments"]["duration_seconds"], 600)
        self.assertEqual(mixing["arguments"]["duration_seconds"], 30)

    def test_final_floor_transfer_is_appended_after_result_reading(self):
        result = plan_natural_language("将样品送到VD10检测并读取结果，最后送到2楼")
        ids = operation_ids(result)
        self.assertEqual(ids[-1], "lab.meta.cross_zone_transport")
        self.assertLess(ids.index("robot.meta.read_result_from_screen"), len(ids) - 1)
        self.assertEqual(
            result["operationChain"]["operations"][-1]["arguments"]["destination_floor"],
            "2楼",
        )

    def test_missing_required_physical_parameter_returns_failed_contract(self):
        result = plan_natural_language("将样品分成4份后送去检测")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("operationChain", result)
        self.assertIn("sample_volume_requirement", result["preprocessing"]["clarification"]["missingFields"])

    def test_unknown_text_is_not_forced_to_a_device(self):
        result = plan_natural_language("今天天气怎么样")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("operationChain", result)

    def test_http_adapter_preserves_supplied_workflow_id(self):
        result = plan_from_natural_language(NaturalLanguagePlanningRequest(
            text="读取VD10检测结果",
            workflowId="wf_direct-test",
        ))
        self.assertEqual(result["workflowId"], "wf_direct-test")
        self.assertEqual(result["status"], "success")
        self.assertEqual(operation_ids(result), [
            "vd10.meta.query_test_results",
            "robot.meta.read_result_from_screen",
        ])


if __name__ == "__main__":
    unittest.main()
