"""Extract BDO Node War scoreboard rows with PaddleOCR.

The script first finds ``NODE WAR RESULT`` in each screenshot.  Its bounding box
anchors the table search area, after which OCR detections are assigned to rows
and to the scoreboard's fixed-width statistic columns.

Examples:
    python node_war_scoreboard_ocr.py
    python node_war_scoreboard_ocr.py "nw scoreboard"
    python node_war_scoreboard_ocr.py screenshot.png --output results
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence


IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}

# Column centers measured as fractions of the screenshot width.  The UI scales
# uniformly in the supplied screenshots, so normalized coordinates work across
# slightly different resolutions.  The first 13 headings are icons in-game;
# neutral names are used instead of guessing their meaning.
COLUMN_NAMES = [*(f"metric_{number:02d}" for number in range(1, 14)), "time_1", "time_2"]
COLUMN_X_RATIOS = (
    0.277,
    0.326,
    0.373,
    0.422,
    0.470,
    0.518,
    0.566,
    0.614,
    0.663,
    0.711,
    0.759,
    0.807,
    0.856,
    0.904,
    0.951,
)
CELL_TEXT_RE = re.compile(r"^[0-9.,:KMB%+-]+$", re.IGNORECASE)
METRIC_TEXT_RE = re.compile(r"^[0-9]+(?:[.,][0-9]+)?[KMB]?$", re.IGNORECASE)
TIME_TEXT_RE = re.compile(r"^[0-9]{1,2}:[0-9]{2}$")
CELL_THRESHOLDS = (70, 85, 100, 115, 130)
GHOST_PRONE_COLUMNS = {"metric_10", "metric_11", "metric_12", "metric_13"}


@dataclass(frozen=True)
class Detection:
    text: str
    confidence: float
    box: tuple[int, int, int, int]

    @property
    def center_x(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def center_y(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]


@dataclass
class ScoreboardRow:
    family_name: str
    cells: dict[str, str]
    y: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read one screenshot or a directory of BDO Node War scoreboards "
            "using 'NODE WAR RESULT' as the table anchor."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help=(
            "Image or directory. Defaults to 'image scoreboard', then "
            "'nw scoreboard' when that directory exists."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/node-war-results"),
        help="Output directory for CSV, JSON, and annotated images.",
    )
    parser.add_argument("--anchor", default="NODE WAR RESULT", help="Anchor text.")
    parser.add_argument("--lang", default="en", help="PaddleOCR language model.")
    parser.add_argument("--device", default="cpu", help="PaddleOCR device, e.g. cpu or gpu:0.")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.45,
        help="Minimum OCR confidence retained (default: 0.45).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search directories recursively for images.",
    )
    parser.add_argument(
        "--no-cell-fallback",
        action="store_true",
        help="Disable enhanced blank-cell recovery and ghost-column correction.",
    )
    return parser.parse_args()


def default_input_path() -> Path:
    for candidate in (Path("image scoreboard"), Path("nw scoreboard")):
        if candidate.exists():
            return candidate
    return Path("image scoreboard")


def find_images(input_path: Path, recursive: bool = False) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image type: {input_path}")
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input does not exist: {input_path}")

    iterator = input_path.rglob("*") if recursive else input_path.iterdir()
    return sorted(
        path for path in iterator if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def box_from_value(value: Any) -> tuple[int, int, int, int]:
    """Convert PaddleOCR's rectangle or four-point polygon to x1/y1/x2/y2."""
    points = value.tolist() if hasattr(value, "tolist") else value
    if len(points) == 4 and all(not isinstance(item, (list, tuple)) for item in points):
        x1, y1, x2, y2 = points
        return round(x1), round(y1), round(x2), round(y2)

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))


def detections_from_result(result: Any, min_confidence: float) -> list[Detection]:
    data = result.json
    page = data.get("res", data)
    texts = page.get("rec_texts", [])
    scores = page.get("rec_scores", [])
    boxes = page.get("rec_boxes")
    if boxes is None:
        boxes = page.get("dt_polys", [])

    detections: list[Detection] = []
    for text, score, box in zip(texts, scores, boxes):
        cleaned = str(text).strip()
        confidence = float(score)
        if cleaned and confidence >= min_confidence:
            detections.append(Detection(cleaned, confidence, box_from_value(box)))
    return detections


def normalized(text: str) -> str:
    return "".join(character for character in text.upper() if character.isalnum())


def text_similarity(left: str, right: str) -> float:
    left_normalized = normalized(left)
    right_normalized = normalized(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized in right_normalized or right_normalized in left_normalized:
        return min(len(left_normalized), len(right_normalized)) / max(
            len(left_normalized), len(right_normalized)
        )
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def find_text(detections: Iterable[Detection], target: str, threshold: float) -> Detection | None:
    ranked = sorted(
        ((text_similarity(detection.text, target), detection) for detection in detections),
        key=lambda item: (item[0], item[1].confidence),
        reverse=True,
    )
    if ranked and ranked[0][0] >= threshold:
        return ranked[0][1]
    return None


def cluster_by_y(detections: Sequence[Detection], tolerance: float) -> list[list[Detection]]:
    clusters: list[list[Detection]] = []
    for detection in sorted(detections, key=lambda item: (item.center_y, item.box[0])):
        if not clusters:
            clusters.append([detection])
            continue
        cluster_y = median(item.center_y for item in clusters[-1])
        if abs(detection.center_y - cluster_y) <= tolerance:
            clusters[-1].append(detection)
        else:
            clusters.append([detection])
    return clusters


def join_horizontal(detections: Sequence[Detection]) -> str:
    return "".join(item.text for item in sorted(detections, key=lambda item: item.box[0]))


def choose_cell_detection(
    detections: Sequence[Detection], expected_x: float, row_y: float, width: int, row_tolerance: float
) -> Detection | None:
    max_x_distance = width * 0.027
    candidates = [
        detection
        for detection in detections
        if abs(detection.center_y - row_y) <= row_tolerance
        and abs(detection.center_x - expected_x) <= max_x_distance
        and CELL_TEXT_RE.fullmatch(detection.text)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            abs(item.center_x - expected_x) / max_x_distance
            + abs(item.center_y - row_y) / row_tolerance,
            -item.confidence,
        ),
    )


def keep_regular_rows(
    row_clusters: Sequence[list[Detection]], estimated_step: float
) -> list[list[Detection]]:
    """Remove ghost rows that do not align with the foreground table's row grid."""
    if len(row_clusters) < 3 or estimated_step <= 0:
        return list(row_clusters)

    first_y = median(item.center_y for item in row_clusters[0])
    max_residual = max(5.0, estimated_step * 0.28)
    by_slot: dict[int, tuple[float, list[Detection]]] = {}
    for cluster in row_clusters:
        row_y = median(item.center_y for item in cluster)
        slot = round((row_y - first_y) / estimated_step)
        if slot < 0:
            continue
        residual = abs(row_y - (first_y + slot * estimated_step))
        if residual > max_residual:
            continue
        previous = by_slot.get(slot)
        if previous is None or residual < previous[0]:
            by_slot[slot] = (residual, cluster)
    return [by_slot[slot][1] for slot in sorted(by_slot)]


def extract_scoreboard(
    detections: Sequence[Detection], image_size: tuple[int, int], anchor_text: str
) -> tuple[Detection, tuple[int, int, int, int], list[ScoreboardRow]]:
    width, height = image_size
    anchor = find_text(detections, anchor_text, threshold=0.72)
    if anchor is None:
        raise ValueError(f"Could not find anchor text {anchor_text!r}")

    anchor_height = max(anchor.height, 1)
    predicted_header_y = anchor.box[3] + anchor_height * 2.15
    header_candidates = [
        detection
        for detection in detections
        if detection.center_y > anchor.center_y and detection.center_y < predicted_header_y + anchor_height
    ]
    family_header = find_text(header_candidates, "Family Name", threshold=0.65)
    header_y = family_header.center_y if family_header else predicted_header_y
    family_right = max(
        (family_header.box[2] + width * 0.02) if family_header else 0,
        width * 0.12,
    )
    table_top = max(0, round(header_y - anchor_height * 0.65))
    table_box = (0, table_top, width, height)

    family_candidates = [
        detection
        for detection in detections
        if detection.center_x <= family_right
        and detection.center_y > header_y + anchor_height * 0.45
        and detection.box[1] < height
        and text_similarity(detection.text, "Family Name") < 0.65
        and any(character.isalpha() for character in detection.text)
    ]
    row_clusters = cluster_by_y(family_candidates, tolerance=max(4.0, height * 0.011))
    row_centers = [median(item.center_y for item in cluster) for cluster in row_clusters]
    row_gaps = [
        later - earlier
        for earlier, later in zip(row_centers, row_centers[1:])
        if later - earlier >= height * 0.025
    ]
    estimated_step = median(row_gaps) if row_gaps else height * 0.046
    row_clusters = keep_regular_rows(row_clusters, estimated_step)
    row_tolerance = max(5.0, min(estimated_step * 0.36, height * 0.015))

    rows: list[ScoreboardRow] = []
    expected_centers = [width * ratio for ratio in COLUMN_X_RATIOS]
    for cluster in row_clusters:
        row_y = median(item.center_y for item in cluster)
        family_name = join_horizontal(cluster)
        cells: dict[str, str] = {}
        for name, expected_x in zip(COLUMN_NAMES, expected_centers):
            match = choose_cell_detection(
                detections, expected_x, row_y, width, row_tolerance
            )
            cells[name] = match.text if match else ""
        rows.append(ScoreboardRow(family_name=family_name, cells=cells, y=round(row_y)))

    return anchor, table_box, rows


def normalize_cell_prediction(text: str, column_name: str) -> str | None:
    """Normalize common OCR substitutions and validate a cell prediction."""
    value = text.strip().upper().replace(" ", "").replace("O", "0")
    if column_name.startswith("time_"):
        digits = re.sub(r"[^0-9]", "", value)
        if ":" not in value and len(digits) == 4:
            value = f"{digits[:2]}:{digits[2:]}"
        return value if TIME_TEXT_RE.fullmatch(value) else None
    return value if METRIC_TEXT_RE.fullmatch(value) else None


def fill_missing_cells(
    image: Any,
    rows: Sequence[ScoreboardRow],
    recognizer: Any,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Fill blank cells and correct ghost-prone cells from enhanced crops.

    The scoreboard panel is translucent. A normal crop makes the recognition
    model read names from the table behind it, so several brightness thresholds
    are tried and only predictions that agree across variants are accepted.
    """
    import numpy as np
    from PIL import Image

    width, height = image.size
    half_width = max(16, round(width * 0.0215))
    # A thin vertical crop keeps the foreground glyph while excluding numbers
    # from background rows that are offset by roughly half a row.
    half_height = max(7, round(height * 0.012))
    scale = 5
    variants: list[Any] = []
    variant_keys: list[tuple[int, str]] = []

    for row_index, row in enumerate(rows):
        for column_name, ratio in zip(COLUMN_NAMES, COLUMN_X_RATIOS):
            if row.cells[column_name] and column_name not in GHOST_PRONE_COLUMNS:
                continue
            center_x = round(width * ratio)
            crop_box = (
                max(0, center_x - half_width),
                max(0, row.y - half_height),
                min(width, center_x + half_width),
                min(height, row.y + half_height),
            )
            grayscale = np.asarray(image.crop(crop_box).convert("L"))
            for threshold in CELL_THRESHOLDS:
                # Bright beige scoreboard glyphs survive; the dark ghost table
                # and decorative background are removed.
                binary = np.where(grayscale > threshold, 0, 255).astype("uint8")
                processed = Image.fromarray(binary).resize(
                    (binary.shape[1] * scale, binary.shape[0] * scale),
                    Image.Resampling.NEAREST,
                )
                variants.append(np.asarray(processed.convert("RGB")))
                variant_keys.append((row_index, column_name))

    if not variants:
        return [], []

    predictions: dict[tuple[int, str], dict[str, list[float]]] = {}
    results = recognizer.predict(variants, batch_size=min(64, len(variants)))
    for key, result in zip(variant_keys, results):
        data = result.json
        page = data.get("res", data)
        value = normalize_cell_prediction(str(page.get("rec_text", "")), key[1])
        score = float(page.get("rec_score", 0.0))
        if value is None or score < 0.50:
            continue
        predictions.setdefault(key, {}).setdefault(value, []).append(score)

    filled: list[tuple[int, str]] = []
    corrected: list[tuple[int, str]] = []
    for (row_index, column_name), candidates in predictions.items():
        value, scores = max(
            candidates.items(),
            key=lambda item: (len(item[1]), sum(item[1]) / len(item[1])),
        )
        # Agreement between thresholds guards against recognition hallucinations
        # from an empty or heavily obstructed crop.
        if len(scores) >= 2 or max(scores) >= 0.96:
            previous = rows[row_index].cells[column_name]
            if value == previous:
                continue
            rows[row_index].cells[column_name] = value
            target = corrected if previous else filled
            target.append((row_index, column_name))
    return filled, corrected


def write_csv(path: Path, rows: Sequence[ScoreboardRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=["family_name", *COLUMN_NAMES])
        writer.writeheader()
        for row in rows:
            writer.writerow({"family_name": row.family_name, **row.cells})


def write_json(
    path: Path,
    source: Path,
    anchor: Detection,
    table_box: tuple[int, int, int, int],
    rows: Sequence[ScoreboardRow],
) -> None:
    payload = {
        "source": str(source),
        "anchor": asdict(anchor),
        "table_box": table_box,
        "columns": COLUMN_NAMES,
        "rows": [asdict(row) for row in rows],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_annotated_image(
    source: Path,
    destination: Path,
    anchor: Detection,
    table_box: tuple[int, int, int, int],
    rows: Sequence[ScoreboardRow],
) -> None:
    from PIL import Image, ImageDraw

    with Image.open(source) as source_image:
        image = source_image.convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle(table_box, outline=(255, 205, 0), width=2)
    draw.rectangle(anchor.box, outline=(255, 70, 70), width=3)
    for row in rows:
        draw.line((0, row.y, image.width, row.y), fill=(60, 200, 255), width=1)
        draw.text((4, max(0, row.y - 14)), row.family_name, fill=(100, 255, 150))
    image.save(destination)


def print_rows(source: Path, rows: Sequence[ScoreboardRow]) -> None:
    print(f"\n{source} ({len(rows)} rows)")
    print(" | ".join(("family_name", *COLUMN_NAMES)))
    for row in rows:
        print(" | ".join((row.family_name, *(row.cells[name] for name in COLUMN_NAMES))))


def main() -> int:
    args = parse_args()
    input_path = args.input or default_input_path()
    try:
        images = find_images(input_path, recursive=args.recursive)
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if not images:
        raise SystemExit(f"No supported images found in: {input_path}")

    try:
        from PIL import Image
        from paddleocr import PaddleOCR, TextRecognition
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Missing OCR dependencies. Install them with: pip install -r requirements.txt"
        ) from error

    args.output.mkdir(parents=True, exist_ok=True)
    ocr = PaddleOCR(
        lang=args.lang,
        device=args.device,
        engine="paddle",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    cell_recognizer = None
    if not args.no_cell_fallback:
        cell_recognizer = TextRecognition(
            model_name="PP-OCRv6_medium_rec",
            device=args.device,
        )

    failures = 0
    for source in images:
        print(f"Reading {source} ...")
        try:
            results = list(ocr.predict(str(source)))
            if not results:
                raise ValueError("PaddleOCR returned no result")
            detections = detections_from_result(results[0], args.min_confidence)
            with Image.open(source) as source_image:
                image = source_image.convert("RGB")
            image_size = image.size
            anchor, table_box, rows = extract_scoreboard(
                detections, image_size, args.anchor
            )
            filled: list[tuple[int, str]] = []
            corrected: list[tuple[int, str]] = []
            if cell_recognizer is not None:
                filled, corrected = fill_missing_cells(image, rows, cell_recognizer)
                print(
                    f"Filled {len(filled)} blank cell(s); corrected "
                    f"{len(corrected)} ghost-overlapped cell(s)."
                )

            stem = source.stem
            write_csv(args.output / f"{stem}.csv", rows)
            write_json(
                args.output / f"{stem}.json", source, anchor, table_box, rows
            )
            write_annotated_image(
                source,
                args.output / f"{stem}_annotated.png",
                anchor,
                table_box,
                rows,
            )
            print_rows(source, rows)
        except Exception as error:  # Continue processing other screenshots.
            failures += 1
            print(f"ERROR: {source}: {error}")

    print(f"\nResults written to: {args.output.resolve()}")
    if failures:
        print(f"Failed to process {failures} of {len(images)} image(s).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
