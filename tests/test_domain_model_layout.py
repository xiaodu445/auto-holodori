"""Integration checks for category-based domain model loading (no game input)."""
import json
import sys
import unittest
from pathlib import Path

from modular_agent.local_models import load_greed_cards, load_greed_cards_play_module, run_daily_tasks
from modular_agent.realtime import fishing, jump_rope

ROOT = Path(__file__).resolve().parents[1]


class DomainModelLayoutTests(unittest.TestCase):
    def test_fishing_loader_and_sibling_components(self):
        config, module, vision = fishing.load(ROOT)
        self.assertEqual(Path(module.__file__).parent.name, 'fishing')
        self.assertIsInstance(module.FishingProgram(config, vision).controller, module.FishingController)

    def test_jump_rope_loader_and_stage_assets(self):
        config, module, _ = jump_rope.load(ROOT)
        self.assertEqual(Path(module.__file__).parent.name, 'jump_rope')
        # Stage-aware gear loading resolves domain assets relative to the moved source.
        settings = 'domains/hololive_dreams/models/jump_rope/jump_rope_stage_config.json'
        vision, _ = jump_rope.phase_rope_components(ROOT, config, module, gear=True, gear_settings_path=settings)
        self.assertIsNotNone(vision.stage_badge)

    def test_greed_cards_dispatchers(self):
        self.assertIsNotNone(load_greed_cards(ROOT))
        module = load_greed_cards_play_module(ROOT)
        self.assertEqual(Path(module.__file__).parent.name, 'greed_cards')
        self.assertIsNotNone(module.GreedCardsPlay())

    def test_daily_plan_preview_uses_game_level_config(self):
        result = run_daily_tasks(ROOT, request={'selected_tasks': ['wheel']}, plan_only=True)
        self.assertFalse(result['executed'])
        self.assertEqual(result['plan']['tasks'], ['wheel'])

    def test_gui_resolves_rhythm_engine_and_config(self):
        gui_path = ROOT / 'gui'
        sys.path.insert(0, str(gui_path))
        try:
            import engine_runner
            engine = engine_runner._load_engine()
        finally:
            sys.path.remove(str(gui_path))
        self.assertEqual(Path(engine.__file__).parent.name, 'rhythm')
        config = engine.load_config(ROOT)
        expected = json.loads((ROOT / 'domains/hololive_dreams/models/rhythm/rhythm_game_config.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(config, expected)


if __name__ == '__main__':
    unittest.main()
