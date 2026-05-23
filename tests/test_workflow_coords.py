import os
import unittest
from unittest.mock import MagicMock, patch

from config.config_manager import ConfigManager
from core.ocr.page_detect import is_step1_text
from core.workflow_coords import (
    REFERENCE_GLOBAL_BUTTONS,
    REFERENCE_STEP1_SLOTS,
    REFERENCE_STEP2_SHARED,
    REFERENCE_STEP3_SHARED,
    get_step1_coord,
    get_step2_coord,
    get_step3_coord,
    use_reference_defaults,
)
from core.workflow.runner import DyclickerRunner


def _user_config() -> ConfigManager:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ConfigManager(config_path=os.path.join(root, "config", "config.yaml"))


class TestWorkflowCoords(unittest.TestCase):
    def setUp(self):
        self.config = _user_config()

    def test_use_reference_defaults_false(self):
        self.assertFalse(use_reference_defaults(self.config))

    def test_step1_wf_mapping(self):
        for wf in range(1, 7):
            pt = get_step1_coord(self.config, wf)
            self.assertEqual(pt, REFERENCE_STEP1_SLOTS[wf - 1])

    def test_step2_step3_slot6(self):
        s2 = get_step2_coord(self.config)
        s3 = get_step3_coord(self.config)
        self.assertEqual(s2, REFERENCE_STEP2_SHARED[5])
        self.assertEqual(s3, REFERENCE_STEP3_SHARED[5])

    def test_global_back(self):
        back = self.config.get("global_buttons.back")
        self.assertEqual(back, REFERENCE_GLOBAL_BUTTONS["back"])


class TestPageDetect(unittest.TestCase):
    def test_step1_keywords(self):
        self.assertTrue(is_step1_text("Company foo Description bar"))
        self.assertFalse(is_step1_text("Company only"))
        self.assertFalse(is_step1_text("Description only"))


class TestWorkflowSwitch(unittest.TestCase):
    @patch("core.workflow.runner.safe_click_back", return_value=True)
    @patch.object(DyclickerRunner, "_wait_for_silence", return_value=True)
    @patch.object(DyclickerRunner, "_run_video_review", return_value=True)
    @patch.object(DyclickerRunner, "_click", return_value=True)
    def test_wf1_calls_back_before_wf2(self, _click, _review, _silence, back):
        cfg = _user_config()
        cfg.set("dyclicker.video_review_cycles", 2)
        cfg.set("dyclicker.wf_switch_delay", 2.0)
        stop = __import__("threading").Event()
        runner = DyclickerRunner(cfg, MagicMock(), stop)
        with patch("core.workflow.runner.interruptible_sleep", return_value=True):
            runner._run_workflow(1)
        back.assert_called_once()
        _silence.assert_called_once()


if __name__ == "__main__":
    unittest.main()
