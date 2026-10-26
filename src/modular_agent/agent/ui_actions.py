"""Game-independent input delivery and geometry checks; no UI success inference."""
from modular_agent.core import Action, Outcome


def send_action(computer, name, arguments, *, check, emit=lambda *a, **k: None, context=None):
    """Check cancellation around delivery and report the actual input outcome."""
    check()
    result = computer.perform(Action(name, arguments=arguments))
    emit('input', **(context or {}), name=name, arguments=arguments, outcome=result.outcome.value)
    if result.outcome != Outcome.SUCCESS:
        raise RuntimeError(result.message or '输入失败')
    check()


def target_center(target, frame):
    """Resolve a fresh target's center within its observed window bounds."""
    bounds = target['bounds']
    x = bounds['x'] + bounds['width'] // 2
    y = bounds['y'] + bounds['height'] // 2
    if not frame['x'] <= x < frame['x'] + frame['width'] or not frame['y'] <= y < frame['y'] + frame['height']:
        raise RuntimeError('模板目标不在游戏窗口内')
    return x, y
