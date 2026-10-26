"""Local perception adapters: screen capture and human-curated CV templates."""
from .screen import capture_monitor, load_image
from .template_library import TemplateLibrary, TemplateMatcher

__all__ = ["TemplateLibrary", "TemplateMatcher", "capture_monitor", "load_image"]

from .general import GeneralVision
from .report import Rect, ScreenReport
from .ocr import LocalOCR
from .knowledge import KnowledgeMatcher

__all__ += ["GeneralVision", "Rect", "ScreenReport", "LocalOCR", "KnowledgeMatcher"]
