"""Local stdio MCP adapter. Never captures or returns screenshots."""
from contextlib import asynccontextmanager
from dataclasses import asdict
import argparse
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP
from modular_agent.core import Action
from .controller import ActionComputer, SCHEMA

def build_server(computer):
    @asynccontextmanager
    async def lifespan(server):
        try: yield {}
        finally: computer.close()
    server = FastMCP('Game Agent Computer', lifespan=lifespan)

    @server.tool()
    def execute_action(name: str, arguments: dict[str, Any] | None = None) -> dict:
        """Execute one input/window action. Consult computer://actions for parameters.
        Coordinates are desktop physical pixels. Relative movement controls game view.
        key_down/mouse_down persist until release, with a 30-second safety timeout.
        Success only confirms dispatch; external perception must verify the outcome.
        """
        return asdict(computer.perform(Action(name,arguments=arguments or {})))

    @server.tool()
    def execute_batch(actions: list[dict[str, Any]]) -> list[dict]:
        """Validate then run actions locally in order; stop on failure and release held inputs.
        Use hold with keys, duration, dx, dy to move and look together without model calls.
        """
        return [asdict(r) for r in computer.run_actions([Action(**a) for a in actions])]

    @server.tool()
    def list_windows() -> dict:
        """List visible windows with handle, title, PID, and foreground flag; no screenshot."""
        return asdict(computer.perform(Action('windows')))

    @server.tool()
    def emergency_stop() -> dict:
        """Stop this session and release all inputs held by this server. Restart to resume."""
        computer.stop()
        return {'stopped':True}

    @server.resource('computer://actions')
    def action_contract() -> dict:
        """Action parameter reference. Duration/interval are seconds (0..30)."""
        return {name:{'required':sorted(required),'optional':sorted(optional)}
                for name,(required,optional) in SCHEMA.items()}
    return server

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--audit',type=Path,default=Path('runtime/computer-actions.jsonl'))
    args=parser.parse_args()
    computer=ActionComputer(live=args.live,audit_path=args.audit)
    try: build_server(computer).run(transport='stdio')
    finally: computer.close()

if __name__ == '__main__': main()
