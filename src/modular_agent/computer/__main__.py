"""Run a JSON action batch. Simulation is the default; --live enables Windows input."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from modular_agent.core import Action, Outcome
from .controller import ActionComputer

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--file',type=Path,help='JSON array of actions')
    parser.add_argument('--list-windows',action='store_true')
    parser.add_argument('--audit',type=Path,default=Path('runtime/computer-actions.jsonl'))
    args = parser.parse_args()
    if args.list_windows:
        if not args.live: parser.error('--list-windows requires --live')
        actions = [Action('windows')]
    elif args.file:
        raw = json.loads(args.file.read_text(encoding='utf-8-sig'))
        if not isinstance(raw,list): parser.error('Action file must contain a JSON array')
        actions = [Action(**item) for item in raw]
    else: parser.error('Provide --file or --list-windows')
    try:
        with ActionComputer(live=args.live,audit_path=args.audit) as computer:
            results = computer.run_actions(actions)
        print(json.dumps([asdict(r) for r in results],ensure_ascii=False))
        return 0 if all(r.outcome == Outcome.SUCCESS for r in results) else 1
    except KeyboardInterrupt:
        print('Interrupted; input release attempted')
        return 130
    except Exception as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False))
        return 1

if __name__ == '__main__': raise SystemExit(main())
