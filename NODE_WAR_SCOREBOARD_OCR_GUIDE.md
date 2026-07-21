# Node War Scoreboard OCR Guide

This document explains how `node_war_scoreboard_ocr.py` processes Black Desert
Online Node War scoreboard screenshots and what each function is responsible
for.

## Purpose

The script reads either one screenshot or a directory of screenshots. For each
image, it:

1. Runs PaddleOCR over the entire screenshot.
2. Finds the `NODE WAR RESULT` title and uses it as the scoreboard anchor.
3. Locates the `Family Name` header and the rows beneath it.
4. Assigns recognized numbers to 15 fixed scoreboard columns.
5. Performs a foreground-enhanced recognition pass for blank cells and the
   four columns most vulnerable to ghost-text overlap.
6. Exports the reconstructed scoreboard as CSV, JSON, and an annotated PNG.

The title is a positional reference, not the source of the table text. The
script first OCRs the complete image. It then uses the title's bounding box to
predict where the table header should be and restrict the subsequent header and
row search. Column positions come from normalized X coordinates measured from
the supplied scoreboard layout.

## High-Level Flow

```text
Command-line arguments
        |
        v
Select input file/directory and discover images
        |
        v
Initialize full-image OCR and cell-only recognizer
        |
        v
For each screenshot
        |
        +--> Run full-image PaddleOCR
        |        |
        |        v
        |    Convert raw OCR output into Detection objects
        |        |
        |        v
        |    Find "NODE WAR RESULT"
        |        |
        |        v
        |    Find "Family Name" and reconstruct row positions
        |        |
        |        v
        |    Assign detected values to the 15 expected columns
        |
        +--> For blank or ghost-prone cells, crop the expected cell area
        |        |
        |        v
        |    Isolate bright foreground text and enlarge it 5x
        |        |
        |        v
        |    Run recognition-only OCR on five threshold variants
        |        |
        |        v
        |    Accept predictions that agree or have very high confidence
        |        |
        |        v
        |    Fill blanks or correct ghost-overlapped values
        |
        +--> Write CSV, JSON, and annotated PNG
        |
        v
Continue with the next screenshot, even if one image fails
```

## Main Processing Flow

### 1. Read the command-line options

`main()` calls `parse_args()` to read the input path, output path, OCR language,
device, minimum confidence, and optional flags.

If no input is supplied, `default_input_path()` looks for these directories in
order:

1. `image scoreboard/`
2. `nw scoreboard/`

`find_images()` then produces a sorted list of supported image files.

### 2. Initialize the OCR models

The script initializes two PaddleOCR components:

- `PaddleOCR` performs detection and recognition over the entire screenshot.
- `TextRecognition` recognizes tightly cropped cell images without first having
  to detect text inside the crop.

The second component is skipped when `--no-cell-fallback` is supplied.

### 3. Run full-image OCR

For each screenshot, the script calls `ocr.predict()`. PaddleOCR returns text,
confidence scores, and bounding boxes in separate arrays.

`detections_from_result()` converts those arrays into `Detection` objects and
removes empty or low-confidence results.

### 4. Find the scoreboard

`extract_scoreboard()` uses fuzzy text matching to find `NODE WAR RESULT`. This
anchor is necessary because the screenshot may contain other UI text outside
the scoreboard.

The anchor's bottom edge and height provide the vertical reference used to
predict the header position below it. The script then looks for `Family Name`.
If that text cannot be found, it continues with the predicted header position.
The anchor does not define the column X positions and the script does not crop
the initial OCR input to the anchor-derived table box.

### 5. Detect the rows

The script collects alphabetic detections in the family-name area below the
header. It groups detections with similar Y coordinates using `cluster_by_y()`.

Because the scoreboard is translucent, OCR can sometimes see text from a panel
behind it. `keep_regular_rows()` estimates the scoreboard's normal row spacing
and rejects candidate rows that do not align with that grid.

Fragments belonging to one family name are sorted left-to-right and combined
by `join_horizontal()`.

### 6. Assign values to columns

The scoreboard has 15 expected value columns:

- `metric_01` through `metric_13`
- `time_1`
- `time_2`

The first 13 headings are icons in the game UI, so the code uses neutral metric
names rather than guessing their meaning.

Each column has an expected horizontal center stored as a fraction of the image
width in `COLUMN_X_RATIOS`. For every row and column,
`choose_cell_detection()` looks for a numeric OCR result close to the expected
X coordinate and the row's Y coordinate. If no suitable detection exists, the
cell remains blank.

### 7. Recover blanks and correct ghost overlap

`fill_missing_cells()` performs the optional second OCR pass for:

- every cell left blank by full-image OCR; and
- every cell in `metric_10` through `metric_13`, even when full-image OCR
  returned a value.

The four right-side columns are always rechecked because their small digits
frequently overlap numeric text visible through the translucent panel. For
example, full-image OCR can combine a foreground `0` with a background `7` and
return the plausible but incorrect value `70`.

For each selected cell, the function:

1. Crops a small, deliberately thin region around the expected position. The
   thin height excludes background rows that are vertically offset from the
   foreground row.
2. Converts the crop to grayscale.
3. Creates five black-and-white variants using brightness thresholds `70`,
   `85`, `100`, `115`, and `130`. Bright beige foreground glyphs become black,
   while the darker ghost table is usually removed.
4. Enlarges every variant by five times with nearest-neighbor scaling.
5. Sends all variants through the recognition-only model in a batch.
6. Discards predictions below `0.50` confidence, normalizes common `O`/`0`
   confusion, and validates the text as a metric or time value.
7. Groups identical predictions across the threshold variants.
8. Accepts a value if at least two thresholds agree, or if one result has a
   confidence of at least `0.96`.
9. Fills the cell when it was blank, or replaces the first-pass value when a
   ghost-prone column produces a different supported result.

This is recognition, not default-value insertion: the script does not replace
unknown cells with a guessed `0`. A value must pass numeric/time validation and
the consensus or high-confidence rule.

### 8. Write the results

For each source image, the script creates:

- `<image-name>.csv`: the extracted table.
- `<image-name>.json`: rows plus anchor and table coordinates.
- `<image-name>_annotated.png`: a visual debugging image.

The annotated image uses:

- red for the anchor bounding box;
- yellow for the calculated table area;
- blue for row-center lines; and
- green for family names.

## Function Reference

### Data classes and properties

| Name | What it does |
| --- | --- |
| `Detection` | Stores one OCR result: its text, confidence score, and rectangular bounding box. It is immutable after creation. |
| `Detection.center_x` | Calculates the horizontal center of a detection's bounding box. |
| `Detection.center_y` | Calculates the vertical center of a detection's bounding box. |
| `Detection.height` | Calculates the height of a detection's bounding box. |
| `ScoreboardRow` | Stores one reconstructed row: family name, column-value dictionary, and row-center Y coordinate. It is mutable so fallback OCR can fill blank cells. |

### Input and configuration functions

| Function | What it does |
| --- | --- |
| `parse_args()` | Defines and parses all command-line arguments. Returns an `argparse.Namespace`. |
| `default_input_path()` | Chooses the default screenshot directory when the user does not provide an input path. |
| `find_images(input_path, recursive=False)` | Validates a file or directory and returns all supported image paths. Raises an error for a missing path or unsupported single file. |

### PaddleOCR conversion functions

| Function | What it does |
| --- | --- |
| `box_from_value(value)` | Converts either a four-value rectangle or a four-point PaddleOCR polygon into `(x1, y1, x2, y2)`. |
| `detections_from_result(result, min_confidence)` | Extracts recognized text, confidence scores, and boxes from a PaddleOCR result. Cleans them and returns `Detection` objects above the confidence threshold. |

### Text-matching functions

| Function | What it does |
| --- | --- |
| `normalized(text)` | Uppercases text and removes all characters except letters and digits. This makes UI-title comparisons less sensitive to spaces and punctuation. |
| `text_similarity(left, right)` | Measures fuzzy similarity between two normalized strings. It handles partial matches first, then falls back to `SequenceMatcher`. |
| `find_text(detections, target, threshold)` | Ranks detections by similarity and OCR confidence, then returns the best one if it reaches the required similarity threshold. |

### Row and cell reconstruction functions

| Function | What it does |
| --- | --- |
| `cluster_by_y(detections, tolerance)` | Sorts detections vertically and groups items whose center Y coordinates are close enough to represent the same row. |
| `join_horizontal(detections)` | Sorts text fragments from left to right and concatenates them into one string. It does not insert spaces. |
| `choose_cell_detection(detections, expected_x, row_y, width, row_tolerance)` | Finds the best numeric detection near one expected column position and row position. It favors the closest candidate, then higher confidence. |
| `keep_regular_rows(row_clusters, estimated_step)` | Removes ghost or background rows that do not align with the estimated foreground scoreboard row grid. |
| `extract_scoreboard(detections, image_size, anchor_text)` | Coordinates anchor matching, header detection, row clustering, ghost-row removal, and fixed-column assignment. Returns the anchor, table box, and reconstructed rows. |

### Enhanced-cell recognition functions

| Function | What it does |
| --- | --- |
| `normalize_cell_prediction(text, column_name)` | Cleans a recognition-only result, changes common `O`/`0` mistakes, optionally restores a missing time colon, and validates the result as a metric or time. |
| `fill_missing_cells(image, rows, recognizer)` | Reprocesses blank cells and all ghost-prone cells, creates foreground-only threshold variants, recognizes them in batches, and updates supported results. Returns separate lists of filled and corrected row/column locations. |

### Output functions

| Function | What it does |
| --- | --- |
| `write_csv(path, rows)` | Writes family names and all 15 cell values to a CSV file. |
| `write_json(path, source, anchor, table_box, rows)` | Writes source information, anchor details, table coordinates, column names, and complete row data to JSON. |
| `write_annotated_image(source, destination, anchor, table_box, rows)` | Draws the calculated table, detected anchor, row centers, and family names over the source screenshot. |
| `print_rows(source, rows)` | Prints the extracted table to the terminal in a pipe-separated format. |

### Program entry point

| Function | What it does |
| --- | --- |
| `main()` | Runs the complete program: parses arguments, finds images, initializes OCR, processes each image, performs fallback recognition, writes outputs, reports failures, and returns the process exit code. |
| `if __name__ == "__main__"` | Calls `main()` when the file is executed directly and passes its return value to the operating system as the exit status. |

## Important Constants

| Constant | Purpose |
| --- | --- |
| `IMAGE_SUFFIXES` | File extensions accepted as input images. |
| `COLUMN_NAMES` | Output names for the 15 scoreboard columns. |
| `COLUMN_X_RATIOS` | Expected horizontal center of each column as a fraction of screenshot width. |
| `CELL_TEXT_RE` | Loose pattern for numeric values found during full-image OCR. |
| `METRIC_TEXT_RE` | Strict pattern used to validate recovered metric values. |
| `TIME_TEXT_RE` | Strict one-or-two-digits, colon, two-digits pattern used for recovered time values. It validates shape without assigning time-unit semantics. |
| `CELL_THRESHOLDS` | Brightness cutoffs used to generate fallback recognition variants. |
| `GHOST_PRONE_COLUMNS` | Columns `metric_10` through `metric_13`, which are rechecked even when the first pass returned text. |

## Error Handling

Input problems stop the program immediately, including:

- a missing input path;
- an unsupported single-image extension;
- a directory containing no supported images; and
- missing OCR dependencies.

Once image processing begins, an error in one screenshot is caught and reported
without preventing later screenshots from being processed. The final exit code
is `1` if any screenshot failed and `0` if all screenshots succeeded.

## Key Assumptions and Limitations

- `NODE WAR RESULT` must be detected well enough to pass fuzzy matching.
- Family-name rows must contain at least one alphabetic character.
- Metric columns are not discovered dynamically. Their positions come from the
  fixed values in `COLUMN_X_RATIOS`.
- Those normalized positions assume the game UI scales uniformly across
  screenshots.
- `join_horizontal()` combines name fragments without spaces.
- `table_box` is output as metadata and drawn for debugging, but the initial OCR
  is still run over the complete screenshot.
- Blank cells in any metric/time column are sent through enhanced recognition.
  Nonblank cells are only rechecked automatically in `metric_10` through
  `metric_13`.
- The enhanced pass is conservative but OCR can still be wrong when foreground
  and background glyphs have similar brightness and occupy nearly the same
  position. The annotated output and overlapping screenshots remain useful for
  validation.
- If recursively processed images in different directories have the same file
  stem, their output filenames can collide.

## Example Commands

Process the default screenshot directory:

```bash
python node_war_scoreboard_ocr.py
```

Process all images directly inside `nw scoreboard/`:

```bash
python node_war_scoreboard_ocr.py "nw scoreboard"
```

Process one image and choose an output directory:

```bash
python node_war_scoreboard_ocr.py screenshot.png --output results
```

Process subdirectories recursively:

```bash
python node_war_scoreboard_ocr.py screenshots --recursive
```

Disable both missing-cell recovery and ghost-prone-column correction:

```bash
python node_war_scoreboard_ocr.py "nw scoreboard" --no-cell-fallback
```
