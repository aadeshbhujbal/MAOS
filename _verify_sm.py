import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from maos.core.state_machine import (
    apply_event,
    WorkUnitEvent,
    IllegalTransitionError,
    is_terminal,
    legal_events,
    is_legal,
)
from maos.contracts.work_units import WorkUnitState as S

assert apply_event(S.ASSIGNED, WorkUnitEvent.START) is S.IN_PROGRESS
assert apply_event(S.ASSIGNED, WorkUnitEvent.REQUIRE_APPROVAL) is S.AWAITING_APPROVAL
assert apply_event(S.AWAITING_APPROVAL, WorkUnitEvent.APPROVAL_GRANTED) is S.IN_PROGRESS
assert apply_event(S.AWAITING_APPROVAL, WorkUnitEvent.APPROVAL_DENIED) is S.FAILED
assert apply_event(S.IN_PROGRESS, WorkUnitEvent.COMPLETE) is S.COMPLETED
assert apply_event(S.IN_PROGRESS, WorkUnitEvent.FAIL) is S.FAILED
assert apply_event(S.IN_PROGRESS, WorkUnitEvent.TIMEOUT) is S.TIMED_OUT
assert apply_event(S.TIMED_OUT, WorkUnitEvent.FAIL) is S.FAILED
assert apply_event(S.FAILED, WorkUnitEvent.REASSIGN) is S.ASSIGNED
assert apply_event(S.FAILED, WorkUnitEvent.EXHAUST) is S.PERMANENTLY_FAILED

assert is_terminal(S.COMPLETED) and is_terminal(S.PERMANENTLY_FAILED)
assert not is_terminal(S.ASSIGNED)
assert legal_events(S.COMPLETED) == frozenset()

# illegal transition rejected, typed error, state unchanged
try:
    apply_event(S.COMPLETED, WorkUnitEvent.START)
    raise SystemExit("FAIL: expected IllegalTransitionError")
except IllegalTransitionError as e:
    assert e.state is S.COMPLETED and e.event is WorkUnitEvent.START

assert is_legal(S.ASSIGNED, WorkUnitEvent.START)
assert not is_legal(S.ASSIGNED, WorkUnitEvent.COMPLETE)

print("all state-machine checks passed")
