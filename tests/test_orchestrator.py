import tempfile
import unittest
from pathlib import Path

from modular_agent.agent import AgentOrchestrator
from modular_agent.core import Outcome, SkillResult, State
from modular_agent.memory import MarkdownMemoryStore
from modular_agent.skills import SkillMetadata, SkillRegistry, SkillRouter
from modular_agent.bootstrap import initialize_domain, initialize_project
from modular_agent.model_client import ModelConfig, create_model_client
from modular_agent.perception import TemplateLibrary, TemplateMatcher
import cv2
import numpy as np


class Observer:
    def observe(self):
        return State(environment="test_game", facts={"reward_visible": True})


class RewardSkill:
    name = "collect_reward"
    def can_handle(self, state): return state.facts["reward_visible"]
    def execute(self, state): return SkillResult(Outcome.SUCCESS, message="Reward button is available")
    def verify(self, before, result, after): return True


class OrchestratorTests(unittest.TestCase):
    def test_success_is_verified_and_becomes_memory(self):
        registry = SkillRegistry()
        registry.register(SkillMetadata("collect_reward", "collect reward", ("test_game",), reliability=.9), RewardSkill())
        with tempfile.TemporaryDirectory() as directory:
            store = MarkdownMemoryStore(Path(directory))
            report = AgentOrchestrator(Observer(), SkillRouter(registry), store).run_once("collect reward")
            self.assertEqual(report.outcome, Outcome.SUCCESS)
            self.assertTrue(report.verification_passed)
            self.assertEqual(len(store.retrieve("reward", "test_game")), 1)

    def test_unknown_state_escalates_without_writing_memory(self):
        registry = SkillRegistry()
        with tempfile.TemporaryDirectory() as directory:
            report = AgentOrchestrator(Observer(), SkillRouter(registry), MarkdownMemoryStore(Path(directory))).run_once("collect reward")
        self.assertEqual(report.outcome, Outcome.UNKNOWN)
        self.assertIsNone(report.selected_skill)

    def test_project_initialization_creates_knowledge_base_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(initialize_project(root))
            self.assertTrue((root / "knowledge" / "global" / "system.md").exists())
            self.assertEqual(initialize_project(root), [])

    def test_domain_initialization_keeps_specialized_resources_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_domain(root, "game_x")
            domain = root / "domains" / "game_x"
            for name in ("knowledge", "skills", "vision_library", "models", "data"):
                self.assertTrue((domain / name / "README.md").exists())

    def test_mock_model_works_without_a_secret(self):
        output = create_model_client(ModelConfig()).complete("JSON only", "inspect state")
        self.assertIn('"decision": "escalate"', output)

    def test_template_library_matches_and_records_human_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screen = np.zeros((100, 100, 3), dtype=np.uint8)
            patch = np.random.default_rng(42).integers(0, 255, (12, 15, 3), dtype=np.uint8)
            screen[30:42, 40:55] = patch
            source = root / "template.png"
            cv2.imwrite(str(source), patch)
            library = TemplateLibrary(root / "vision")
            record = library.add("reward_button", source, ["game_x"], .99)
            detected = TemplateMatcher(library).match(screen, "game_x")
            self.assertEqual(len(detected), 1)
            self.assertEqual(detected[0].bbox, (40, 30, 55, 42))
            self.assertEqual(library.record_feedback(record.id, True).reliability, 1.0)


if __name__ == "__main__":
    unittest.main()
