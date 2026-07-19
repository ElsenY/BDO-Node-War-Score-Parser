"""Small, local PaddleOCR example.

Run without arguments to OCR a generated sample image, or pass your own image:

    python paddleocr_example.py
    python paddleocr_example.py receipt.jpg --lang en
"""

from __future__ import annotations

import argparse
from pathlib import Path


def create_sample_image(path: Path) -> None:
    """Create a simple image so the example can run without an input file."""
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(image)

    font_paths = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "C:/Windows/Fonts/arial.ttf",  # Windows
    )
    font = None
    for font_path in font_paths:
        try:
            font = ImageFont.truetype(font_path, 52)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    draw.text((45, 55), "Hello PaddleOCR!", fill="black", font=font)
    draw.text((45, 135), "Invoice number: 2026-001", fill="black", font=font)
    image.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recognize text in an image or PDF with PaddleOCR."
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Image/PDF path or URL. A sample image is generated when omitted.",
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="OCR language model to use (default: en).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Directory for the annotated image and JSON result (default: output).",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Inference device, for example cpu or gpu:0 (default: cpu).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from paddleocr import PaddleOCR
        if args.input is None:
            import PIL  # noqa: F401 - verifies the sample-image dependency
    except ModuleNotFoundError as error:
        raise SystemExit(
            "PaddleOCR dependencies are not installed. Follow the setup steps "
            "in README.md."
        ) from error

    args.output.mkdir(parents=True, exist_ok=True)
    if args.input is None:
        sample_path = args.output / "sample_input.png"
        create_sample_image(sample_path)
        input_source = str(sample_path)
        print(f"Created sample image: {sample_path}")
    else:
        input_source = args.input
        if "://" not in input_source and not Path(input_source).exists():
            raise SystemExit(f"Input file does not exist: {input_source}")

    # The orientation and unwarping models are disabled to keep this first example
    # lightweight. PaddleOCR downloads its OCR models on the first run.
    ocr = PaddleOCR(
        lang=args.lang,
        device=args.device,
        engine="paddle",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    print(f"\nReading: {input_source}\n")
    found_text = False
    for page_number, result in enumerate(ocr.predict(input_source), start=1):
        # `result.json` is a normal dictionary in PaddleOCR 3.x.
        data = result.json
        page_data = data.get("res", data)
        texts = page_data.get("rec_texts", [])
        scores = page_data.get("rec_scores", [])

        if texts:
            found_text = True
            if page_number > 1:
                print(f"Page {page_number}")
            for text, score in zip(texts, scores):
                print(f"  {float(score):.1%}  {text}")

        result.save_to_img(str(args.output))
        result.save_to_json(str(args.output))

    if not found_text:
        print("No text was detected.")

    print(f"\nAnnotated image and JSON saved in: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
