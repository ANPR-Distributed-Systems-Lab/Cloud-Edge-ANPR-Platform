"""Validates a CVAT export ("CVAT for images 1.1", .zip or annotations.xml) against the labeling guide.

Checks every plate polygon (4 points, TL-TR-BR-BL clockwise order, convex, inside the image, attributes,
text) and prints plate width statistics on the original frame, which is what the small-plate threshold is
decided from. With --out it also writes the validated annotations as JSON lines with corners normalized
to 0-1, the resolution-independent form all later steps read.
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

PLATE, IGNORE = "plate", "plate_ignore"
READABLE = {"yes", "no"}
OCCLUSION = {"none", "partial"}
TYPES = {"standard", "two-line", "motorcycle", "other"}
TEXT_RE = re.compile(r"[A-Z0-9]{3,8}")  # generic charset; the per-position Polish rules come with the OCR model
IGNORE_WIDTH_PX = 80  # plates narrower than this on the original belong in plate_ignore
EDGE_TOLERANCE_PX = 2


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    widths: list[float] = field(default_factory=list)
    images: int = 0
    plates: int = 0
    ignored: int = 0


def _signed_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _convex(pts: np.ndarray) -> bool:
    edges = np.roll(pts, -1, axis=0) - pts
    nxt = np.roll(edges, -1, axis=0)
    cross = edges[:, 0] * nxt[:, 1] - edges[:, 1] * nxt[:, 0]
    return bool(np.all(cross > 0) or np.all(cross < 0))


def parse_points(text: str) -> np.ndarray:
    return np.array([[float(v) for v in p.split(",")] for p in text.split(";")])


def check_quad(pts: np.ndarray, width: int, height: int, where: str, report: Report) -> bool:
    if pts.shape != (4, 2):
        report.errors.append(f"{where}: {len(pts)} points instead of 4")
        return False
    ok = True
    # Image coordinates have y pointing down, so a positive signed area is clockwise on screen.
    if _signed_area(pts) <= 0:
        report.errors.append(f"{where}: corners are not clockwise (expected TL, TR, BR, BL)")
        ok = False
    if not _convex(pts):
        report.errors.append(f"{where}: polygon is not convex (crossed or collapsed corners)")
        ok = False
    t = EDGE_TOLERANCE_PX
    if np.any(pts < -t) or np.any(pts[:, 0] > width + t) or np.any(pts[:, 1] > height + t):
        report.errors.append(f"{where}: a corner lies outside the image")
        ok = False
    if ok and pts[:2, 1].mean() > pts[2:, 1].mean():
        report.warnings.append(f"{where}: the first edge is below the opposite one, check that the start is the plate's top-left")
    return ok


def _attrs(shape: ET.Element) -> dict[str, str]:
    return {a.get("name"): (a.text or "").strip() for a in shape.findall("attribute")}


def validate_xml(root: ET.Element) -> tuple[Report, list[dict]]:
    report, records = Report(), []
    for image in root.iter("image"):
        name, w, h = image.get("name"), int(image.get("width")), int(image.get("height"))
        report.images += 1
        record = {"image": name, "width": w, "height": h, "plates": [], "ignore": []}
        for shape in image:
            if shape.tag == "attribute" or shape.tag == "tag":
                continue
            where = f"{name} [{shape.get('label')}]"
            if shape.tag != "polygon":
                report.errors.append(f"{where}: unexpected shape '{shape.tag}', only polygons are allowed")
                continue
            label = shape.get("label")
            if label not in (PLATE, IGNORE):
                report.errors.append(f"{where}: unknown label")
                continue
            pts = parse_points(shape.get("points"))
            if not check_quad(pts, w, h, where, report):
                continue
            norm = (pts / np.array([w, h])).round(6).tolist()
            attrs = _attrs(shape)
            if label == IGNORE:
                report.ignored += 1
                if attrs.get("text"):
                    report.warnings.append(f"{where}: ignored region carries text")
                record["ignore"].append({"corners": norm})
                continue

            report.plates += 1
            width_px = float((np.linalg.norm(pts[1] - pts[0]) + np.linalg.norm(pts[2] - pts[3])) / 2)
            report.widths.append(width_px)
            text, readable = attrs.get("text", ""), attrs.get("readable", "")
            occlusion, kind = attrs.get("occlusion", ""), attrs.get("type", "")
            if readable not in READABLE:
                report.errors.append(f"{where}: readable must be one of {sorted(READABLE)}, got '{readable}'")
            if occlusion not in OCCLUSION:
                report.errors.append(f"{where}: occlusion must be one of {sorted(OCCLUSION)}, got '{occlusion}'")
            if kind not in TYPES:
                report.errors.append(f"{where}: type must be one of {sorted(TYPES)}, got '{kind}'")
            if readable == "yes" and not TEXT_RE.fullmatch(text):
                report.errors.append(f"{where}: readable plate needs text matching {TEXT_RE.pattern}, got '{text}'")
            if readable == "no" and text:
                report.warnings.append(f"{where}: unreadable plate has text '{text}'")
            if width_px < IGNORE_WIDTH_PX:
                report.warnings.append(f"{where}: {width_px:.0f}px wide, below {IGNORE_WIDTH_PX}px; should it be {IGNORE}?")
            record["plates"].append(
                {"corners": norm, "text": text, "readable": readable == "yes", "occlusion": occlusion, "type": kind}
            )
        records.append(record)
    return report, records


def load_xml(path: Path) -> ET.Element:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            return ET.fromstring(z.read("annotations.xml"))
    return ET.parse(path).getroot()


def print_report(report: Report) -> None:
    print(f"{report.images} images, {report.plates} plates, {report.ignored} ignored regions")
    if report.widths:
        w = np.array(report.widths)
        q = np.percentile(w, [0, 10, 25, 50, 75, 90, 100])
        print("plate width on the original (px): min {:.0f}, p10 {:.0f}, p25 {:.0f}, median {:.0f}, p75 {:.0f}, p90 {:.0f}, max {:.0f}".format(*q))
        print(f"plates narrower than {IGNORE_WIDTH_PX}px: {int((w < IGNORE_WIDTH_PX).sum())}")
    for line in report.warnings:
        print("WARNING", line)
    for line in report.errors:
        print("ERROR", line)
    print(f"{len(report.errors)} errors, {len(report.warnings)} warnings")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="CVAT export (.zip or annotations.xml)")
    parser.add_argument("--out", type=Path, help="write validated annotations as JSON lines")
    args = parser.parse_args()

    report, records = validate_xml(load_xml(args.export))
    print_report(report)
    if args.out and not report.errors:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(json.dumps(r) + "\n" for r in records))
        print(f"written {args.out}")
    sys.exit(1 if report.errors else 0)


if __name__ == "__main__":
    main()
