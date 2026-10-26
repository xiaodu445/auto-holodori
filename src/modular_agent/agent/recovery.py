"""Structured precondition failures, distinct from uncertain business outcomes."""


def precondition_failure(expected, observed, message, *, recoverable=False):
    return {'outcome': 'unknown', 'verified': False, 'message': message,
            'error': {'code': 'precondition_not_met', 'phase': 'precondition',
                      'expected_state': expected, 'observed_state': observed,
                      'business_input_sent': False, 'recoverable': recoverable}}


def recovery_target(catalog, step, result):
    """Only a declared adapter's pre-input failure can activate automatic recovery."""
    if step.get('recovery', 'auto') == 'none' or not isinstance(result, dict):
        return None
    if result.get('outcome') != 'unknown' or result.get('verified') is True:
        return None
    policy = catalog.read(step['capability']).get('precondition_recovery', {})
    error = result.get('error', {})
    if not isinstance(error, dict): return None
    if (error.get('code') != 'precondition_not_met' or error.get('phase') != 'precondition'
            or error.get('business_input_sent') is not False or error.get('recoverable') is not True
            or error.get('expected_state') != policy.get('expected_state')):
        return None
    target = policy.get('capability')
    if target:
        catalog.read(target)  # Repository-owned contract, never an error-message command.
    return target
