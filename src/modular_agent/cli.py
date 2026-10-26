from __future__ import annotations

import argparse
import json
from pathlib import Path

from modular_agent.bootstrap import initialize_domain, initialize_project
from modular_agent.model_client import ModelConfig, create_model_client
from modular_agent.perception import TemplateLibrary, TemplateMatcher, capture_monitor, load_image
from modular_agent.agent import AgentOrchestrator
from modular_agent.core import Outcome, SkillResult, State
from modular_agent.memory import MarkdownMemoryStore
from modular_agent.skills import SkillMetadata, SkillRegistry, SkillRouter


class DemoObserver:
    def observe(self) -> State:
        return State(environment="demo_game", facts={"reward_visible": True})


class CollectRewardSkill:
    name = "collect_reward"
    def can_handle(self, state: State) -> bool:
        return bool(state.facts.get("reward_visible"))
    def execute(self, state: State) -> SkillResult:
        return SkillResult(Outcome.SUCCESS, message="Reward collection was simulated")
    def verify(self, before: State, result: SkillResult, after: State) -> bool:
        return result.outcome == Outcome.SUCCESS


def main() -> None:
    parser = argparse.ArgumentParser(description="Modular Agent MVP")
    parser.add_argument("command", choices=["init", "domain-init", "demo", "run", "vision-add-template", "vision-import", "vision-scan", "vision-feedback", "observe", "chat", "local-run", "local-start", "local-play", "local-daily"])
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--log-window", action="store_true", help="Show floating live log window")
    parser.add_argument("--live", action="store_true", help="Enable real desktop operations")
    parser.add_argument("--max-steps", type=int, default=0, help="0 means unlimited decisions (default)")
    parser.add_argument("--goal", help="Natural-language goal for `run`")
    parser.add_argument("--config", default="config/model.json", help="Model configuration JSON")
    parser.add_argument("--provider", choices=["mock", "openai_responses", "openai_chat"])
    parser.add_argument("--model")
    parser.add_argument("--model-profile", help="Named model profile from config/models.json")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env")
    parser.add_argument("--name", help="Template name in lowercase snake_case")
    parser.add_argument("--source-dir", help="Folder containing game template images and sidecars")
    parser.add_argument("--image", help="Image file: template source or scan input")
    parser.add_argument("--environment", default="default")
    parser.add_argument("--domain", help="Specialized domain, e.g. game_x; required for vision commands")
    parser.add_argument("--threshold", type=float, default=.65)
    parser.add_argument("--notes", default="")
    parser.add_argument("--global-library", action="store_true", help="Use the shared visual knowledge library")
    parser.add_argument("--role", choices=["object", "button", "panel", "icon"], default="object")
    parser.add_argument("--knowledge-file", help="Knowledge document reference for a template")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--no-uia", action="store_true")
    parser.add_argument("--window-handle", type=int)
    parser.add_argument("--output", help="Save structured perception JSON locally")
    parser.add_argument("--monitor", type=int, default=1)
    feedback = parser.add_mutually_exclusive_group()
    feedback.add_argument("--accepted", action="store_true")
    feedback.add_argument("--rejected", action="store_true")
    parser.add_argument("--daily-collected",type=int,default=None,help="Confirmed gross rewards collected today")
    parser.add_argument("--stage",type=int,choices=[0,1,2],default=None,help="0 first big reward, 1 staging reward, 2 final big reward")
    parser.add_argument("--max-rounds",type=int,default=200)
    parser.add_argument("--max-loss",type=int,default=10000)
    parser.add_argument('--daily-plan',help='local-daily JSON request file')
    parser.add_argument('--daily-tasks',help='Comma-separated task IDs; empty string runs no tasks')
    parser.add_argument('--record-rewards',action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument('--plan-only',action='store_true',help='Preview daily plan without desktop control')
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    if args.command == "local-play":
        if args.domain != "hololive_dreams": parser.error("local-play requires --domain hololive_dreams")
        from modular_agent.local_models import run_greed_cards_play
        result=run_greed_cards_play(root,live=args.live, image=args.image,
            daily_collected=args.daily_collected,stage=args.stage,max_rounds=args.max_rounds,max_loss=args.max_loss)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    if args.command == "local-daily":
        if args.domain != "hololive_dreams": parser.error("local-daily requires --domain hololive_dreams")
        from modular_agent.local_models import run_daily_tasks
        request=json.loads(Path(args.daily_plan).read_text(encoding='utf-8-sig')) if args.daily_plan else {}
        if not isinstance(request,dict):parser.error('daily-plan must be a JSON object')
        if args.daily_tasks is not None:request['selected_tasks']=[n.strip() for n in args.daily_tasks.split(',') if n.strip()]
        if args.record_rewards is not None:request['record_rewards']=args.record_rewards
        print(json.dumps(run_daily_tasks(root,live=args.live,request=request,plan_only=args.plan_only),ensure_ascii=False,indent=2))
        return
    if args.command == "local-start":
        if args.domain != "hololive_dreams": parser.error("local-start requires --domain hololive_dreams")
        from modular_agent.local_models import run_startup
        print(json.dumps(run_startup(root,live=args.live),ensure_ascii=False,indent=2))
        return
    if args.command == "local-run":
        if args.domain != "hololive_dreams": parser.error("local-run currently requires --domain hololive_dreams")
        from modular_agent.local_models import run_greed_cards
        result=run_greed_cards(root,live=args.live)
        destination=root/'runtime'/'last-local-model-result.json'
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    if args.command == "init":
        created = initialize_project(root)
        print(json.dumps({"created": [str(path.relative_to(root)) for path in created]}, ensure_ascii=False))
        return

    if args.command == "domain-init":
        if not args.domain:
            parser.error("domain-init requires --domain")
        created = initialize_domain(root, args.domain)
        print(json.dumps({"domain": args.domain, "created": [str(path.relative_to(root)) for path in created]}, ensure_ascii=False))
        return

    if args.command == "observe":
        from modular_agent.perception import GeneralVision
        vision = GeneralVision.for_project(root, args.domain,
            enable_ocr=not args.no_ocr, enable_uia=not args.no_uia)
        if args.image:
            if args.window_handle is not None:
                parser.error("--window-handle only applies to live screen capture")
            report = vision.analyze(load_image(Path(args.image)), environment=args.environment)
        else:
            report = vision.observe(args.monitor, args.environment, args.window_handle)
        output = json.dumps(report.to_dict(), ensure_ascii=False)
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(output, encoding="utf-8")
        else:
            print(output)
        return

    if args.command.startswith("vision-") and not args.domain and not args.global_library:
        parser.error(f"{args.command} requires --domain")
    if args.global_library and args.domain:
        parser.error("Choose --global-library or --domain, not both")
    library = TemplateLibrary(root / "knowledge" / "vision_library") if args.global_library else (TemplateLibrary(root / "domains" / args.domain / "vision_library") if args.domain else None)
    if args.command == "vision-import":
        if not args.domain: parser.error("vision-import requires --domain")
        from modular_agent.perception.template_import import import_game_templates
        report=import_game_templates(root,args.domain,args.source_dir)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return
    if args.command == "vision-add-template":
        if not args.name or not args.image:
            parser.error("vision-add-template requires --name and --image")
        knowledge = root / "knowledge" / "templates" if args.global_library else root / "domains" / args.domain / "knowledge" / "templates"
        reference = args.knowledge_file or str((knowledge / f"{args.name}.md").relative_to(root))
        record = library.add(args.name, Path(args.image), [args.environment], args.threshold, args.notes, args.role, reference)
        knowledge.mkdir(parents=True, exist_ok=True)
        (knowledge / f"{record.name}.md").write_text(
            f"# {record.name}\n\n- Template ID: `{record.id}`\n- Environment: `{args.environment}`\n- Threshold: `{record.threshold}`\n- Notes: {record.notes or 'None'}\n- Verification: requires human feedback after matching.\n", encoding="utf-8")
        print(json.dumps({"template": record.name, "id": record.id, "reliability": record.reliability}, ensure_ascii=False))
        return
    if args.command == "vision-feedback":
        if not args.name or args.accepted == args.rejected:
            parser.error("vision-feedback requires --name and exactly one of --accepted/--rejected")
        record = library.record_feedback(args.name, args.accepted)
        print(json.dumps({"template": record.name, "reliability": record.reliability, "successes": record.confirmed_successes, "failures": record.confirmed_failures}, ensure_ascii=False))
        return
    if args.command == "vision-scan":
        image, frame = (load_image(Path(args.image)), None) if args.image else capture_monitor(args.monitor)
        matches = TemplateMatcher(library).match(image, args.environment)
        print(json.dumps({"source": args.image or "screen", "frame": None if frame is None else {"width": frame.width, "height": frame.height, "monitor": frame.monitor}, "environment": args.environment, "detections": [item.to_dict() for item in matches]}, ensure_ascii=False))
        return

    if args.command in ("run", "chat"):
        if args.command == "run" and not args.goal:
            parser.error("run requires --goal")
        if args.max_steps < 0:
            parser.error("--max-steps must be 0 (unlimited) or a positive integer")
        from modular_agent.agent.console import run_console
        run_console(args,root)
        return

    registry = SkillRegistry()
    registry.register(SkillMetadata("collect_reward", "Collect a visible reward", ("demo_game",), reliability=.95, tags=("reward",)), CollectRewardSkill())
    runtime = root / args.runtime_dir
    registry.export_manifest(runtime / "skill_registry.json")
    report = AgentOrchestrator(DemoObserver(), SkillRouter(registry), MarkdownMemoryStore(runtime / "memory")).run_once("collect daily reward")
    print(f"outcome={report.outcome}; skill={report.selected_skill}; verified={report.verification_passed}")


if __name__ == "__main__":
    main()
