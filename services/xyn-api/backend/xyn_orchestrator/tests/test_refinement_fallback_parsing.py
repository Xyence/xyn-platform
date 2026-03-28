import json

from django.test import SimpleTestCase

from xyn_orchestrator.xyn_api import _extract_json_object_text, _validate_hybrid_refinement_envelope


class RefinementFallbackParsingTests(SimpleTestCase):
    def test_extract_json_accepts_markdown_fence(self):
        payload = "```json\n" + json.dumps({"result_type": "plan_revision"}) + "\n```"
        extracted = _extract_json_object_text(payload)
        self.assertEqual(json.loads(extracted), {"result_type": "plan_revision"})

    def test_extract_json_accepts_surrounding_prose(self):
        payload = "Here you go:\n" + json.dumps({"result_type": "plan_revision", "confidence": 0.9}) + "\nDone"
        extracted = _extract_json_object_text(payload)
        self.assertEqual(
            json.loads(extracted),
            {"result_type": "plan_revision", "confidence": 0.9},
        )

    def test_extract_json_returns_empty_for_malformed(self):
        self.assertEqual(_extract_json_object_text("{not-json"), "")

    def test_validation_rejects_unknown_top_level_keys(self):
        safe, errors = _validate_hybrid_refinement_envelope(
            {
                "mode": "agent_fallback",
                "result_type": "plan_revision",
                "confidence": 0.5,
                "normalized_updates": {},
                "workspace_id": "evil-mutation",
            }
        )
        self.assertIsNone(safe)
        self.assertTrue(any("unknown top-level keys" in err for err in errors))

    def test_validation_accepts_theme_refinement_updates(self):
        safe, errors = _validate_hybrid_refinement_envelope(
            {
                "mode": "agent_fallback",
                "result_type": "answer_resolution",
                "confidence": 0.8,
                "normalized_updates": {
                    "ui_preferences": {"theme": "light"},
                    "resolved_answers": [{"question_key": "ui_theme", "value": "light"}],
                },
                "warnings": [],
            }
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(safe)
        self.assertEqual((safe or {}).get("normalized_updates"), {
            "ui_preferences": {"theme": "light"},
            "resolved_answers": [{"question_key": "ui_theme", "value": "light"}],
        })
