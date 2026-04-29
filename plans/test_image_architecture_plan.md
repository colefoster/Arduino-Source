# Plan: Test Image & Detection Architecture Overhaul

> Source PRD: `plans/test_image_architecture.md` | GitHub: PokemonAutomation/Arduino-Source#1219

## Architectural decisions

Durable decisions that apply across all phases:

- **Screen graph**: `test_images/screens.yaml` is the single source of truth for all screens, transitions, detector/reader registration, and field schemas
- **Image storage**: `test_images/<screen_name>/` directories, one per visually distinct screen state. In-battle screens split by singles/doubles. Images named by timestamp.
- **Labels**: `test_images/<screen_name>/manifest.json` per directory. Keys are filenames, values are reader output labels. Detectors have no manifest entries — positive/negative determined by directory membership.
- **Overlays**: `test_images/_overlays/<name>/` for cross-screen readers (e.g., battle_log)
- **Negative testing**: Implicit. Any image not in a detector's registered screen directories is a negative test case.
- **Null convention**: `null` for unreadable/missing values (not "NONE")
- **C++ deps**: yaml-cpp + nlohmann/json added to CMakeLists.txt
- **Dashboard**: FastAPI on ash (extends existing `dashboard/server.py`)
- **OCR suggestions**: New endpoint on ColePC job runner (port 8422)

---

## Phase 1: screens.yaml + directory skeleton + migration script

**User stories**: As a developer, I can see the full screen graph and all existing test images are migrated to the new structure with labels preserved.

### What to build

Create `test_images/screens.yaml` with all 13 screen directories and 1 overlay fully defined — screens, transitions, detectors, readers, and typed field schemas.

Create empty directory structure with placeholder `manifest.json` files.

Build a Python migration script (`tools/migrate_test_images.py`) that:
- Reads every image from `CommandLineTests/PokemonChampions/<DetectorName>/`
- Maps old detector directory names to new screen directories (e.g., `MoveNameReader/` → `move_select_singles/` or `move_select_doubles/`)
- Parses old filename labels into manifest.json entries using the existing conventions (`_True`/`_False`, `_word1_word2`, `_int`)
- Copies images to new directories with timestamp-only filenames
- Handles ambiguous mappings interactively (prompt: "Is this image singles or doubles?") or via a mapping config

Run the migration. Verify image count matches before and after.

### Acceptance criteria

- [ ] `test_images/screens.yaml` exists with all 13 screens + 1 overlay, transitions, detectors, readers, and typed field schemas
- [ ] All 13 screen directories + `_overlays/battle_log/` created with `manifest.json` files
- [ ] Migration script successfully moves all existing test images from `CommandLineTests/PokemonChampions/`
- [ ] Manifest entries contain correct labels parsed from old filenames
- [ ] No data loss — every old test image accounted for in new structure

---

## Phase 2: C++ test runner reads new structure

**User stories**: As a developer, I can run `--regression` against the new directory structure and get the same pass/fail results as before.

### What to build

Add yaml-cpp and nlohmann/json as dependencies in CMakeLists.txt.

Rewrite the test discovery and execution in `CommandLineTests.cpp` and `TestMap.cpp`:
- Parse `test_images/screens.yaml` to build the detector → screen and reader → screen mappings
- For each reader: scan its registered screen directories, load `manifest.json`, run the reader against each image, compare output to manifest values
- For each detector: run against registered screen images expecting `true` (positive tests only in this phase — negatives come in Phase 3)
- Preserve the existing regression report format (ASCII table, per-reader stats, failure listing)

Delete `CommandLineTests/PokemonChampions/` once the new runner passes.

Update `tools/retest.py` to point at the new test path.

### Acceptance criteria

- [ ] yaml-cpp and nlohmann/json integrated into CMake build
- [ ] C++ test runner parses `screens.yaml` and `manifest.json` files
- [ ] `--regression` produces equivalent pass/fail results to the old runner
- [ ] Regression report format unchanged (ASCII table, per-reader stats)
- [ ] `CommandLineTests/PokemonChampions/` deleted
- [ ] `tools/retest.py` works with new structure

---

## Phase 3: Implicit negative testing

**User stories**: As a developer, every detector is automatically tested against all non-registered screen images as negative cases, without any manual labeling.

### What to build

Extend the C++ test runner so that for each detector, after running positive tests on registered screens, it also runs the detector against every image in every non-registered screen directory and asserts `false`.

Update the regression report to show negative test counts per detector (e.g., "TeamPreviewDetector: 50 positive, 400 negative, 450 total").

### Acceptance criteria

- [ ] Each detector tested against all images in non-registered screen directories
- [ ] All negative tests assert detector returns `false`
- [ ] Regression report shows positive and negative counts per detector
- [ ] No false positives in existing test image set (or failures are flagged for investigation)

---

## Phase 4: Dashboard gallery/regression views updated

**User stories**: As a developer, I can browse test images by screen (not by detector) in the gallery, and view regression results mapped to the new structure.

### What to build

Update the dashboard's gallery API endpoints to read from `test_images/<screen>/` instead of `test_images/<DetectorName>/`. The gallery should:
- List screens (from directory structure or `screens.yaml`)
- Show images per screen with crop previews for all registered readers
- Display manifest labels alongside each image

Update regression API to map results to screens rather than detector directories.

Update crop definitions (`CROP_DEFS` in `server.py`) to be organized by reader name, loaded from `screens.yaml` or a derivative, rather than hardcoded.

### Acceptance criteria

- [ ] Gallery lists screens, not detectors
- [ ] Each image shows crop previews for all registered readers on that screen
- [ ] Manifest labels displayed alongside each image
- [ ] Regression results page works with new structure
- [ ] Crop definitions driven by configuration, not hardcoded

---

## Phase 5: Web labeler — inbox + screen sorting

**User stories**: As a developer, I can drop new screenshots into an inbox and sort them into the correct screen directories via the web UI.

### What to build

Add an inbox directory (`test_images/_inbox/`) where new images land.

Build a new labeler page on the dashboard with an inbox view:
- Shows all images in `_inbox/` as a grid of thumbnails
- Click an image to see it full-size
- Assign to a screen directory via dropdown or keyboard shortcut (list populated from `screens.yaml`)
- Bulk selection: shift-click or select-all, assign many images at once
- On assignment: move image to target screen directory, but do NOT add manifest entry yet (that's Phase 6)

Update DetectorTest's `SAVE_LABELED_TESTS` mode to dump images into `_inbox/` (or a staging path that gets synced to ash).

### Acceptance criteria

- [ ] `_inbox/` directory supported as image intake point
- [ ] Inbox view shows thumbnails of all unsorted images
- [ ] Single and bulk assignment to screen directories works
- [ ] Moved images appear in target screen directory
- [ ] No manifest entries created yet (unlabeled state)

---

## Phase 6: Web labeler — manifest editing

**User stories**: As a developer, I can open a screen directory, see all images, and fill in reader labels through a schema-driven form that saves to manifest.json.

### What to build

Build the screen labeling view on the dashboard:
- Pick a screen from sidebar
- See all images in that screen directory as a scrollable list
- For each image: show full screenshot + crop region previews for each registered reader
- Below crops: auto-generated form fields based on `screens.yaml` schema (text inputs for strings, number inputs for ints, array inputs with correct length)
- Pre-populate fields from existing manifest entry if one exists
- Save button writes to `manifest.json`
- Keyboard navigation: tab through fields, enter to save and advance to next image
- Visual indicator for images with no manifest entry (unlabeled) vs. complete vs. partial

### Acceptance criteria

- [ ] Screen view shows all images with crop previews
- [ ] Form fields generated from `screens.yaml` schema (correct types, lengths, constraints)
- [ ] Labels save to `manifest.json` correctly
- [ ] Existing labels load and display on revisit
- [ ] Keyboard-driven workflow (tab, enter to advance)
- [ ] Visual status indicators: unlabeled / partial / complete

---

## Phase 7: OCR suggestion API on ColePC

**User stories**: As a developer, the labeler can call ColePC to run the actual C++ reader against an image and get suggested labels.

### What to build

Extend the ColePC job runner (`scripts/job_runner.py`) with a new synchronous endpoint:

```
POST /ocr-suggest
Body: { image: <base64>, reader: "MoveNameReader", screen: "move_select_doubles" }
Response: { "moves": ["fake-out", "close-combat", "dire-claw", "protect"] }
```

This endpoint:
- Decodes the image, writes to a temp file
- Shells out to `SerialProgramsCommandLine` with a new `--ocr-suggest` mode that runs a single reader against a single image and prints JSON output
- Parses the output and returns it
- Synchronous (not queued) — fast enough for single-image OCR

Add the `--ocr-suggest` mode to the C++ command line entry point.

### Acceptance criteria

- [ ] `POST /ocr-suggest` endpoint added to job runner
- [ ] C++ `--ocr-suggest` mode runs one reader on one image, outputs JSON
- [ ] Round-trip works: send image from ash → ColePC runs reader → returns labels
- [ ] Handles errors gracefully (reader not found, image unreadable, etc.)

---

## Phase 8: Web labeler — OCR pre-population + validation

**User stories**: As a developer, the labeler pre-fills reader fields with OCR suggestions so I only need to confirm or correct. A validation view shows me what's still incomplete.

### What to build

Integrate the OCR suggestion API into the labeler's screen view:
- "Auto-suggest" button per image (or per reader) calls `POST /ocr-suggest` on ColePC
- Returned values populate the form fields (highlighted as suggestions, not yet saved)
- Developer confirms (enter) or edits before saving
- Bulk suggest: run OCR on all unlabeled images in a screen directory

Build a validation view:
- Lists all screen directories with completion stats (X/Y images labeled)
- Drill into a screen to see which images are missing labels or have partial labels
- Validate manifest entries against `screens.yaml` schema (correct types, array lengths, value ranges)
- Flag errors: missing required fields, wrong types, array length mismatch

### Acceptance criteria

- [ ] Auto-suggest button calls OCR API and pre-fills form fields
- [ ] Suggestions visually distinguished from confirmed labels
- [ ] Bulk suggest runs OCR across all unlabeled images in a directory
- [ ] Validation view shows per-screen completion stats
- [ ] Schema validation catches type errors, missing fields, wrong array lengths
- [ ] All unlabeled images discoverable from validation view
