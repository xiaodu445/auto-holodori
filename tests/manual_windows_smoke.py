"""Manual, reversible Windows smoke test. Does not click or type text."""
import json
import time
from modular_agent.computer import ActionComputer
from modular_agent.computer.windows import WindowsBackend
from modular_agent.core import Action, Outcome

def main():
    backend=WindowsBackend()
    original=backend.cursor()
    results=[]
    try:
        with ActionComputer(live=True,backend=backend) as c:
            windows=c.perform(Action('windows'))
            if windows.outcome != Outcome.SUCCESS: raise RuntimeError(windows.message)
            results.append({'check':'window enumeration','count':len(windows.data['windows'])})
            for action in (Action('move_relative',arguments={'dx':5,'dy':0}),Action('press',arguments={'key':'shift','duration':.03})):
                report=c.perform(action)
                if report.outcome != Outcome.SUCCESS: raise RuntimeError(report.message)
                results.append({'check':action.name,'status':'dispatched'})
            moved=backend.cursor()
            results.append({'check':'cursor changed','passed':moved != original})
            if moved == original: raise RuntimeError('Relative movement had no observable cursor effect')
    finally:
        backend.move_to(original['x'],original['y'])
    time.sleep(.05)
    restored=backend.cursor()
    if abs(restored['x']-original['x'])>1 or abs(restored['y']-original['y'])>1:
        raise RuntimeError('Cursor did not return to its original position')
    results.append({'check':'cursor restored','passed':True})
    print(json.dumps(results))

if __name__ == '__main__': main()
