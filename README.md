# PaddleOCR Python example

This project contains a small local OCR example in `paddleocr_example.py`. It:

- creates a sample image when no input is supplied;
- prints each detected line and its confidence score;
- writes an annotated image and a JSON result to `output/`.

## Setup (macOS / Apple Silicon)

PaddlePaddle currently supports Python 3.9 through 3.13, not Python 3.14. This
computer already has Python 3.13, so create the virtual environment with it:

```bash
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install paddlepaddle==3.3.0 \
  -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install -r requirements.txt
```

On Windows or Linux, use a supported Python version and select the appropriate
PaddlePaddle CPU/GPU install command from the official installation guide.

## Run it

Run with the generated sample image:

```bash
python paddleocr_example.py
```

Or pass your own image or PDF:

```bash
python paddleocr_example.py path/to/receipt.jpg
```

Useful options:

```bash
python paddleocr_example.py --help
python paddleocr_example.py receipt.jpg --lang en --output my_results
```

The first OCR run downloads the pretrained models, so it needs an internet
connection and can take a little longer than later runs.

## Read Node War scoreboards

`node_war_scoreboard_ocr.py` reads every screenshot in a directory, locates the
`NODE WAR RESULT` title, and uses its position to reconstruct the rows beneath
it. Tiny digits missed by PaddleOCR's text detector receive a second,
foreground-enhanced recognition pass. The same pass rechecks the four
right-side statistic columns, where the translucent panel can cause foreground
zeros and ghost digits to be merged. Run it with the included screenshots:

```bash
python node_war_scoreboard_ocr.py "nw scoreboard"
```

When no input is supplied, the script looks for `image scoreboard/` and then
`nw scoreboard/`. Results are saved under `output/node-war-results/` as:

- one CSV file per screenshot;
- one JSON file containing anchor/table coordinates and row data; and
- one annotated PNG showing the detected anchor, table area, and row centers.

The first 13 data headings are icons rather than text in the game UI, so the
output calls them `metric_01` through `metric_13`; the final columns are
`time_1` and `time_2`.

Use a single image or select another output directory as needed:

```bash
python node_war_scoreboard_ocr.py screenshot.png --output results
python node_war_scoreboard_ocr.py --help
```

The cell fallback is enabled by default. Pass `--no-cell-fallback` when you only
want values found by the normal full-image OCR pass.
