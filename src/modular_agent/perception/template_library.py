from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from shutil import copy2
from uuid import uuid4

import cv2
import numpy as np

from .models import VisionDetection


@dataclass
class TemplateRecord:
    id: str
    name: str
    image_file: str
    image_sha256: str
    environments: list[str]
    threshold: float
    created_at: str
    confirmed_successes: int = 0
    confirmed_failures: int = 0
    notes: str = ""
    mask_mode: str = "none"
    role: str = "object"
    knowledge_file: str | None = None

    @property
    def reliability(self) -> float | None:
        total = self.confirmed_successes + self.confirmed_failures
        return round(self.confirmed_successes / total, 4) if total else None


class TemplateLibrary:
    """A versioned, human-curated local image matching library."""

    def __init__(self, root: Path) -> None:
        self.root, self.images_dir, self.registry_path = root, root / "images", root / "registry.json"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._save([])

    def add(self, name: str, image_path: Path, environments: list[str], threshold: float = .65, notes: str = "", role: str = "object", knowledge_file: str | None = None) -> TemplateRecord:
        if role not in ("object", "button", "panel", "icon"): raise ValueError("Invalid template role")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("Template name must be lowercase snake_case")
        if not .0 < threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        raw=np.fromfile(str(image_path),dtype=np.uint8)
        try:
            decoded=cv2.imdecode(raw,cv2.IMREAD_GRAYSCALE) if raw.size else None
        except cv2.error:
            decoded=None
        if decoded is None: raise ValueError("image must be a readable image file")
        content_hash = sha256(image_path.read_bytes()).hexdigest()
        destination = self.images_dir / f"{name}_{content_hash[:12]}{image_path.suffix.lower() or '.png'}"
        if not destination.exists():
            copy2(image_path, destination)
        record = TemplateRecord(str(uuid4()), name, str(destination.relative_to(self.root)), content_hash,
                                environments or ["*"], threshold, datetime.now(UTC).isoformat(), notes=notes, role=role, knowledge_file=knowledge_file)
        records = self.records(); records.append(record); self._save(records)
        return record

    def records(self) -> list[TemplateRecord]:
        return [TemplateRecord(**item) for item in json.loads(self.registry_path.read_text(encoding="utf-8"))]

    def record_feedback(self, template_id: str, accepted: bool) -> TemplateRecord:
        records = self.records()
        record = next((item for item in records if item.id == template_id or item.name == template_id), None)
        if record is None:
            raise KeyError(f"No template named or identified by {template_id!r}")
        if accepted: record.confirmed_successes += 1
        else: record.confirmed_failures += 1
        self._save(records)
        return record

    def _save(self, records: list[TemplateRecord]) -> None:
        self.registry_path.write_text(json.dumps([asdict(item) for item in records], ensure_ascii=False, indent=2), encoding="utf-8")


class TemplateMatcher:
    """Local OpenCV matching. It never sends image pixels to a network."""
    def __init__(self, library: TemplateLibrary) -> None: self.library = library

    def match(self, screen: np.ndarray, environment: str) -> list[VisionDetection]:
        screen_gray = self._gray(screen); detections: list[VisionDetection] = []
        for record in self.library.records():
            if "*" not in record.environments and environment not in record.environments: continue
            template = cv2.imread(str(self.library.root / record.image_file), cv2.IMREAD_GRAYSCALE)
            if template is None or template.shape[0] > screen_gray.shape[0] or template.shape[1] > screen_gray.shape[1]: continue
            _, confidence, _, point = cv2.minMaxLoc(cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED))
            if confidence >= record.threshold:
                h, w = template.shape
                detections.append(VisionDetection(record.id, record.name, round(float(confidence), 4),
                                                   (point[0], point[1], point[0] + w, point[1] + h), environment))
        return sorted(detections, key=lambda item: item.confidence, reverse=True)

    @staticmethod
    def _gray(image: np.ndarray) -> np.ndarray:
        return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
