"""Read-only perception MCP; screenshots remain local, tools return structured JSON."""
import argparse
import asyncio
import threading
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .general import GeneralVision

def build_server(vision,default_environment='default'):
    server=FastMCP('Game Agent Local Vision')

    @server.tool()
    async def observe_screen(monitor: int = 0, environment: str | None = None,
                       window_handle: int | None = None, enable_ocr: bool | None = None,
                       enable_uia: bool | None = None, enable_cv_buttons: bool | None = None,
                       enable_knowledge: bool | None = None, ocr_max_side: int | None = None,
                       template_names: list[str] | None = None, template_scales: list[float] | None = None,
                       template_threshold: float | None = None, region: list[int] | None = None) -> dict:
        """Read local screen, window geometry, button candidates, OCR and knowledge matches.
        Return desktop-pixel coordinates and confidence; never return image pixels.
        UIA reads the foreground window (or requested handle). CV examines captured pixels.
        """
        options={key:value for key,value in {
            'enable_ocr':enable_ocr,'enable_uia':enable_uia,'enable_cv_buttons':enable_cv_buttons,
            'enable_knowledge':enable_knowledge,'ocr_max_side':ocr_max_side,'template_names':template_names,
            'template_scales':template_scales,'template_threshold':template_threshold,'region':region}.items() if value is not None}
        report=await asyncio.to_thread(vision.observe,monitor,environment or default_environment,window_handle,**options)
        return report.to_dict()


    @server.tool()
    async def find_text(query: list[str], mode: str = 'contains', window_handle: int | None = None,
                  region: list[int] | None = None, min_confidence: float = 0) -> dict:
        """Search current OCR text; region is desktop [x,y,width,height]."""
        return await asyncio.to_thread(vision.find_text,query,mode=mode,window_handle=window_handle,region=region,min_confidence=min_confidence,environment=default_environment)

    @server.tool()
    async def find_templates(template_names: list[str], window_handle: int | None = None,
                       region: list[int] | None = None, threshold: float | None = None,
                       scales: list[float] | None = None) -> dict:
        """Match only specified templates; request overrides never modify registry."""
        return await asyncio.to_thread(vision.find_templates,template_names,window_handle=window_handle,region=region,template_threshold=threshold,template_scales=scales,environment=default_environment)

    @server.tool()
    async def wait_for(kind: str, query: list[str], timeout: float = 30, interval: float = .5,
                 stable_count: int = 1, require_all: bool = False, window_handle: int | None = None,
                 region: list[int] | None = None) -> dict:
        """Bounded read-only polling for text or template, with fresh screen each time."""
        stop=threading.Event()
        try:
            return await asyncio.to_thread(vision.wait_for,kind,query,timeout=timeout,interval=interval,stable_count=stable_count,require_all=require_all,window_handle=window_handle,region=region,environment=default_environment,cancelled=stop.is_set)
        except asyncio.CancelledError:
            stop.set()
            raise

    return server

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path('.'))
    parser.add_argument('--domain')
    parser.add_argument('--environment',default='default')
    parser.add_argument('--no-ocr',action='store_true')
    parser.add_argument('--no-uia',action='store_true')
    args=parser.parse_args()
    vision=GeneralVision.for_project(args.project_root,args.domain,
        enable_ocr=not args.no_ocr,enable_uia=not args.no_uia)
    try: build_server(vision,args.environment).run(transport='stdio')
    finally: vision.close()

if __name__=='__main__': main()
