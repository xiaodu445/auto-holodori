"""Common UI execution with a non-game adapter and simulated input only."""
from types import SimpleNamespace
import unittest

from modular_agent.agent.interaction import InteractionPolicy, TransitionState, transition
from modular_agent.agent.ui_actions import send_action, target_center
from modular_agent.core import Outcome


class CommonTransitionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.sent = []

    def report(self, page, enabled=True):
        return SimpleNamespace(page=page, enabled=enabled,
            frame={'target_window_handle': 1},
            windows=[{'handle': 1, 'foreground': True}])

    def wait(self, seconds):
        self.now += seconds

    def run_flow(self, observe, **overrides):
        options = dict(observe=observe, send=self.sent.append,
            resolve=lambda r: {'item': 'save', 'enabled': r.enabled},
            source=lambda r: r.page == 'settings', completed=lambda r: r.page == 'saved',
            state_of=lambda r: {'busy': TransitionState.LOADING, 'modal': TransitionState.OVERLAY,
                                'other': TransitionState.UNKNOWN}.get(r.page, TransitionState.READY),
            wait=self.wait, clock=lambda: self.now,
            policy=InteractionPolicy(timeout=4, retry_interval=.5, poll_interval=.25))
        options.update(overrides)
        return transition(**options)

    def test_custom_adapter_retries_dropped_input_and_confirms_destination(self):
        result = self.run_flow(lambda: self.report('settings' if len(self.sent) < 2 else 'saved'))
        self.assertEqual(result.page, 'saved')
        self.assertEqual(len(self.sent), 2)

    def test_loading_or_disabled_control_never_sends(self):
        for page, enabled in [('busy', True), ('settings', False)]:
            with self.subTest(page=page):
                self.now = 0.
                with self.assertRaises(RuntimeError):
                    self.run_flow(lambda: self.report(page, enabled))
                self.assertEqual(self.sent, [])

    def test_late_modal_prevents_repeating_original_action(self):
        recovered = []
        def observe():
            if not self.sent:
                return self.report('settings')
            return self.report('modal' if self.now < 1 else 'settings')
        with self.assertRaises(RuntimeError):
            self.run_flow(observe, recover=lambda r: recovered.append(r.page))
        self.assertTrue(recovered)
        self.assertEqual(len(self.sent), 1)

    def test_cancel_after_observation_prevents_send(self):
        checks = []
        def check():
            checks.append(True)
            if len(checks) == 2:
                raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.run_flow(lambda: self.report('settings'), check=check)
        self.assertFalse(self.sent)

    def test_discovery_is_bounded_and_does_not_confirm_completion(self):
        discoveries = []
        with self.assertRaises(RuntimeError):
            self.run_flow(lambda: self.report('other'),
                discover=lambda: discoveries.append(True) or self.report('other'))
        self.assertEqual(discoveries, [True])
        self.assertFalse(self.sent)


class CommonActionTests(unittest.TestCase):
    def test_cancel_before_delivery_never_calls_backend(self):
        calls = []
        computer = SimpleNamespace(perform=calls.append)
        def cancelled():
            raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            send_action(computer, 'click', {'x': 1, 'y': 2}, check=cancelled)
        self.assertFalse(calls)

    def test_input_failure_records_context_and_is_not_success(self):
        events = []
        computer = SimpleNamespace(perform=lambda action: SimpleNamespace(
            outcome=Outcome.FAILURE, message='input rejected'))
        with self.assertRaisesRegex(RuntimeError, 'input rejected'):
            send_action(computer, 'click', {'x': 1, 'y': 2}, check=lambda: None,
                context={'task': 'settings'}, emit=lambda event, **data: events.append((event, data)))
        self.assertEqual(events[0][1]['task'], 'settings')
        self.assertEqual(events[0][1]['outcome'], Outcome.FAILURE.value)

    def test_off_window_target_rejected_and_negative_monitor_coordinates_supported(self):
        frame = {'x': -100, 'y': 0, 'width': 100, 'height': 100}
        self.assertEqual(target_center({'bounds': {'x': -90, 'y': 10, 'width': 20, 'height': 20}}, frame), (-80, 20))
        with self.assertRaises(RuntimeError):
            target_center({'bounds': {'x': 10, 'y': 10, 'width': 20, 'height': 20}}, frame)


class DailyImportCompatibilityTests(unittest.TestCase):
    def test_legacy_import_resolves_same_game_workflow(self):
        from modular_agent.agent.daily_tasks import DailyTasks as legacy
        from modular_agent.domains.hololive_dreams.daily_tasks import DailyTasks
        self.assertIs(legacy, DailyTasks)


if __name__ == '__main__':
    unittest.main()
