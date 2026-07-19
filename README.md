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
