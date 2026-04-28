#!/usr/bin/env python3
"""
Interactive crop box tuner for OpponentHPReader / SpeciesReader.

Starts a local web server with:
  - Live crop preview using Canvas (updates as you drag sliders)
  - Binarized preview
  - "Retest" button that rebuilds C++, runs regression, shows results inline

Usage: python3 tools/crop_tuner.py [--reader OpponentHPReader_Doubles]
"""

import base64, io, json, os, re, subprocess, sys, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(REPO, "build_mac")
TEST_ROOT = os.path.join(REPO, "CommandLineTests", "PokemonChampions")

# Default boxes — will be overridden by query params on retest
DEFAULT_BOXES = {
    "OpponentHPReader_Doubles": {
        "s0": [0.695, 0.116, 0.040, 0.0361],
        "s1": [0.9035, 0.1130, 0.040, 0.0426],
    },
    "OpponentHPReader": {
        "s0": [0.8963, 0.1098, 0.0498, 0.0524],
    },
    "SpeciesReader_Doubles": {
        "s0": [0.6172, 0.0454, 0.1219, 0.0417],
        "s1": [0.8286, 0.0481, 0.1151, 0.0417],
    },
}

# Map box keys to C++ source patterns for live patching
CPP_FILE = os.path.join(REPO, "SerialPrograms", "Source", "PokemonChampions",
                        "Inference", "PokemonChampions_BattleHUDReader.cpp")


def load_images(reader):
    reader_dir = os.path.join(TEST_ROOT, reader)
    images = []
    for f in sorted(os.listdir(reader_dir)):
        if not f.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        if f.startswith("_"):
            continue
        path = os.path.join(reader_dir, f)
        # Parse slot + expected from filename
        base = os.path.splitext(f)[0]
        parts = base.split("_")
        slot = None
        expected = None
        for i, p in enumerate(parts):
            if p in ("s0", "s1"):
                slot = p
                expected = "_".join(parts[i+1:])
                break
        if slot is None:
            # Old format: last part is the value
            expected = parts[-1]
            slot = "s0"
        images.append({
            "filename": f,
            "slot": slot,
            "expected": expected,
            "path": path,
        })
    return images


def img_to_data_uri(path):
    with open(path, "rb") as fh:
        data = fh.read()
    ext = os.path.splitext(path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def run_regression(reader):
    """Build and run regression, return parsed results dict."""
    # Build
    build = subprocess.run(
        ["cmake", "--build", BUILD_DIR, "-j8"],
        capture_output=True, text=True, timeout=120, cwd=REPO
    )
    if build.returncode != 0:
        return {"error": "Build failed", "output": build.stderr[-500:]}

    # Run
    test_path = os.path.join("..", "CommandLineTests", "PokemonChampions", reader)
    exe = os.path.join(BUILD_DIR, "SerialProgramsCommandLine")
    result = subprocess.run(
        [exe, "--regression", test_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=120, cwd=BUILD_DIR
    )
    output = result.stdout

    # Parse
    results = {}
    current_file = None
    for line in output.split("\n"):
        stripped = line.strip()
        if (stripped.endswith(".png") or stripped.endswith(".jpg")) and not stripped.startswith("Parse"):
            current_file = os.path.basename(stripped)
            results[current_file] = {"passed": True}
        m = re.search(r'result is (.+?) but should be (.+?)\.', stripped)
        if m and current_file:
            results[current_file]["passed"] = False
            results[current_file]["actual"] = m.group(1)
            results[current_file]["expected"] = m.group(2)
        m = re.match(r'OK: actual=(.+)', stripped)
        if m and current_file:
            results[current_file]["actual"] = m.group(1)
        m = re.search(r"failed to parse.*from '(.*)", stripped)
        if m and current_file:
            results[current_file]["raw_ocr"] = m.group(1).rstrip("'")

    return results


def patch_cpp_boxes(reader, boxes):
    """Patch the C++ source with new box coordinates."""
    with open(CPP_FILE, "r") as f:
        src = f.read()

    if reader == "OpponentHPReader_Doubles":
        # Find init_doubles_boxes() function and patch within it
        def patch_in_doubles(src, slot_idx, vals):
            # Find the init_doubles_boxes function
            fn_match = re.search(r'(void BattleHUDReader::init_doubles_boxes\(\)\{.*?)(\n\})', src, re.DOTALL)
            if not fn_match:
                return src
            fn_body = fn_match.group(0)
            new_body = re.sub(
                rf'(m_opponent_hp_boxes\[{slot_idx}\]\s*=\s*ImageFloatBox\()[\d., ]+(\);)',
                lambda m: f'{m.group(1)}{vals[0]}, {vals[1]}, {vals[2]}, {vals[3]}{m.group(2)}',
                fn_body
            )
            return src.replace(fn_body, new_body)

        if "s0" in boxes:
            src = patch_in_doubles(src, 0, boxes["s0"])
        if "s1" in boxes:
            src = patch_in_doubles(src, 1, boxes["s1"])

    with open(CPP_FILE, "w") as f:
        f.write(src)


def read_cpp_boxes(reader):
    """Read current box coordinates from C++ source."""
    with open(CPP_FILE, "r") as f:
        src = f.read()

    boxes = {}
    if reader == "OpponentHPReader_Doubles":
        # Find init_doubles_boxes function body
        fn_match = re.search(r'void BattleHUDReader::init_doubles_boxes\(\)\{(.*?)\n\}', src, re.DOTALL)
        if fn_match:
            fn_body = fn_match.group(1)
            for idx, slot in [(0, "s0"), (1, "s1")]:
                m = re.search(rf'm_opponent_hp_boxes\[{idx}\]\s*=\s*ImageFloatBox\(([\d., ]+)\)', fn_body)
                if m:
                    boxes[slot] = [float(x.strip()) for x in m.group(1).split(",")]

    return boxes


READER = "OpponentHPReader_Doubles"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence logs

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(build_page().encode())
        elif parsed.path == "/retest":
            params = parse_qs(parsed.query)
            # Parse box params: s0_x, s0_y, s0_w, s0_h, s1_x, ...
            boxes = {}
            for slot in ("s0", "s1"):
                keys = [f"{slot}_{d}" for d in "xywh"]
                if all(k in params for k in keys):
                    boxes[slot] = [float(params[k][0]) for k in keys]

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            # Patch C++ and rebuild
            if boxes:
                patch_cpp_boxes(READER, boxes)

            results = run_regression(READER)
            self.wfile.write(json.dumps(results).encode())
        else:
            self.send_response(404)
            self.end_headers()


def build_page():
    images = load_images(READER)
    boxes = read_cpp_boxes(READER)

    # Build image data
    img_data = []
    for img in images:
        img_data.append({
            "filename": img["filename"],
            "slot": img["slot"],
            "expected": img["expected"],
            "dataUri": img_to_data_uri(img["path"]),
        })

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Crop Tuner — {READER}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d1117; color:#c9d1d9; font-family:'SF Mono',monospace; font-size:13px; padding:16px; }}
h1 {{ color:#58a6ff; margin-bottom:4px; font-size:18px; }}
.controls {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; margin:12px 0; position:sticky; top:0; z-index:10; }}
.box-row {{ display:flex; gap:24px; margin-bottom:8px; align-items:center; }}
.box-row label {{ color:#8b949e; font-size:11px; width:20px; }}
.box-row input[type=number] {{ width:80px; padding:4px 6px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; font-size:13px; font-family:inherit; text-align:center; }}
.box-title {{ font-weight:bold; margin-bottom:6px; }}
.box-title.s0 {{ color:#58a6ff; }}
.box-title.s1 {{ color:#3fb950; }}
.btn {{ padding:6px 16px; border:1px solid #30363d; border-radius:6px; background:#21262d; color:#c9d1d9; cursor:pointer; font-size:13px; font-family:inherit; }}
.btn:hover {{ background:#30363d; }}
.btn-primary {{ background:#238636; border-color:#238636; color:#fff; }}
.btn-primary:hover {{ background:#2ea043; }}
.btn:disabled {{ opacity:0.5; cursor:wait; }}
.status {{ color:#8b949e; font-size:12px; margin-left:12px; }}
.cards {{ margin-top:12px; }}
.card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; margin-bottom:8px; display:flex; gap:12px; align-items:center; }}
.card.pass {{ border-left:3px solid #3fb950; }}
.card.fail {{ border-left:3px solid #f85149; }}
.card-img {{ border-radius:4px; }}
.crop-area {{ display:flex; gap:8px; align-items:center; }}
.crop-area canvas {{ border:2px solid #30363d; border-radius:4px; image-rendering:pixelated; }}
.card-info {{ flex:1; }}
.fname {{ color:#58a6ff; font-size:11px; margin-bottom:2px; }}
.expected {{ color:#3fb950; font-size:12px; }}
.actual {{ font-size:12px; }}
.actual.pass {{ color:#3fb950; }}
.actual.fail {{ color:#f85149; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold; }}
.badge.pass {{ background:#238636; color:#fff; }}
.badge.fail {{ background:#da3633; color:#fff; }}
.summary {{ margin:8px 0; font-size:14px; }}
</style>
</head><body>
<h1>Crop Tuner — {READER}</h1>

<div class="controls">
    <div style="display:flex;gap:32px;">
""" + "".join(f"""
        <div>
            <div class="box-title {slot}">{slot} ({('left' if slot == 's0' else 'right')})</div>
            <div class="box-row">
                <label>x</label><input type="number" step="0.001" id="{slot}_x" value="{boxes.get(slot, [0,0,0,0])[0]:.4f}">
                <label>y</label><input type="number" step="0.001" id="{slot}_y" value="{boxes.get(slot, [0,0,0,0])[1]:.4f}">
                <label>w</label><input type="number" step="0.001" id="{slot}_w" value="{boxes.get(slot, [0,0,0,0])[2]:.4f}">
                <label>h</label><input type="number" step="0.001" id="{slot}_h" value="{boxes.get(slot, [0,0,0,0])[3]:.4f}">
            </div>
        </div>
""" for slot in sorted(boxes.keys())) + f"""
    </div>
    <div style="margin-top:10px;display:flex;align-items:center;">
        <button class="btn" onclick="updateCrops()">Preview</button>
        <button class="btn btn-primary" id="retest-btn" onclick="retest()" style="margin-left:8px;">Retest</button>
        <span class="status" id="status"></span>
        <span class="summary" id="summary" style="margin-left:auto;"></span>
    </div>
</div>

<div class="cards" id="cards"></div>

<script>
const images = {json.dumps(img_data)};
let results = {{}};

function getBoxes() {{
    const boxes = {{}};
    for (const slot of ['s0', 's1']) {{
        const x = document.getElementById(slot + '_x');
        if (!x) continue;
        boxes[slot] = {{
            x: parseFloat(document.getElementById(slot + '_x').value),
            y: parseFloat(document.getElementById(slot + '_y').value),
            w: parseFloat(document.getElementById(slot + '_w').value),
            h: parseFloat(document.getElementById(slot + '_h').value),
        }};
    }}
    return boxes;
}}

function renderCards() {{
    const container = document.getElementById('cards');
    container.innerHTML = '';
    let pass = 0, fail = 0, untested = 0;

    images.forEach((img, idx) => {{
        const r = results[img.filename];
        const passed = r ? r.passed : null;
        if (passed === true) pass++;
        else if (passed === false) fail++;
        else untested++;

        const card = document.createElement('div');
        card.className = 'card' + (passed === true ? ' pass' : passed === false ? ' fail' : '');
        card.id = 'card-' + idx;

        // Thumbnail canvas
        const thumbCanvas = document.createElement('canvas');
        thumbCanvas.width = 480;
        thumbCanvas.height = 270;
        thumbCanvas.className = 'card-img';

        // Crop canvas
        const cropCanvas = document.createElement('canvas');
        cropCanvas.id = 'crop-' + idx;

        // Binarized canvas
        const bwCanvas = document.createElement('canvas');
        bwCanvas.id = 'bw-' + idx;

        const info = document.createElement('div');
        info.className = 'card-info';

        let html = `<div class="fname">${{img.filename}}</div>`;
        html += `<div class="expected">expected: ${{img.expected}}</div>`;
        if (r) {{
            const cls = r.passed ? 'pass' : 'fail';
            html += `<div class="actual ${{cls}}">actual: ${{r.actual || '?'}}</div>`;
            if (r.raw_ocr !== undefined && !r.passed) {{
                html += `<div class="actual fail">raw OCR: "${{r.raw_ocr || '(empty)'}}"</div>`;
            }}
            html += ` <span class="badge ${{cls}}">${{r.passed ? 'PASS' : 'FAIL'}}</span>`;
        }}
        info.innerHTML = html;

        const cropArea = document.createElement('div');
        cropArea.className = 'crop-area';
        cropArea.appendChild(cropCanvas);
        cropArea.appendChild(bwCanvas);

        card.appendChild(thumbCanvas);
        card.appendChild(cropArea);
        card.appendChild(info);
        container.appendChild(card);

        // Draw
        const imgEl = new window.Image();
        imgEl.onload = () => drawCard(idx, imgEl, img.slot);
        imgEl.src = img.dataUri;
    }});

    document.getElementById('summary').innerHTML =
        `<span style="color:#3fb950">${{pass}} pass</span> / ` +
        `<span style="color:#f85149">${{fail}} fail</span>` +
        (untested ? ` / <span style="color:#8b949e">${{untested}} untested</span>` : '');
}}

function drawCard(idx, imgEl, slot) {{
    const boxes = getBoxes();
    const box = boxes[slot];
    if (!box) return;

    const W = imgEl.naturalWidth, H = imgEl.naturalHeight;

    // Thumbnail with box overlay
    const thumbCanvas = document.querySelector('#card-' + idx + ' .card-img');
    const tCtx = thumbCanvas.getContext('2d');
    const scale = Math.min(480 / W, 270 / H);
    const tw = W * scale, th = H * scale;
    thumbCanvas.width = tw; thumbCanvas.height = th;
    tCtx.drawImage(imgEl, 0, 0, tw, th);
    // Draw box
    const color = slot === 's0' ? '#58a6ff' : '#3fb950';
    tCtx.strokeStyle = color;
    tCtx.lineWidth = 2;
    tCtx.strokeRect(box.x * tw, box.y * th, box.w * tw, box.h * th);

    // Crop
    const cx = Math.round(box.x * W), cy = Math.round(box.y * H);
    const cw = Math.round(box.w * W), ch = Math.round(box.h * H);
    if (cw <= 0 || ch <= 0) return;

    const cropCanvas = document.getElementById('crop-' + idx);
    const cropScale = 4;
    cropCanvas.width = cw * cropScale;
    cropCanvas.height = ch * cropScale;
    const cCtx = cropCanvas.getContext('2d');
    cCtx.imageSmoothingEnabled = false;
    cCtx.drawImage(imgEl, cx, cy, cw, ch, 0, 0, cw * cropScale, ch * cropScale);

    // Binarized
    const bwCanvas = document.getElementById('bw-' + idx);
    bwCanvas.width = cw * cropScale;
    bwCanvas.height = ch * cropScale;
    const bCtx = bwCanvas.getContext('2d');
    // First draw at 1:1 to get pixel data
    const tmpCanvas = document.createElement('canvas');
    tmpCanvas.width = cw; tmpCanvas.height = ch;
    const tmpCtx = tmpCanvas.getContext('2d');
    tmpCtx.drawImage(imgEl, cx, cy, cw, ch, 0, 0, cw, ch);
    const imgData = tmpCtx.getImageData(0, 0, cw, ch);
    const d = imgData.data;
    for (let i = 0; i < d.length; i += 4) {{
        const brightness = Math.max(d[i], d[i+1], d[i+2]);
        const val = brightness > 200 ? 0 : 255;
        d[i] = d[i+1] = d[i+2] = val;
    }}
    tmpCtx.putImageData(imgData, 0, 0);
    bCtx.imageSmoothingEnabled = false;
    bCtx.drawImage(tmpCanvas, 0, 0, cw, ch, 0, 0, cw * cropScale, ch * cropScale);
}}

function updateCrops() {{
    images.forEach((img, idx) => {{
        const imgEl = new window.Image();
        imgEl.onload = () => drawCard(idx, imgEl, img.slot);
        imgEl.src = img.dataUri;
    }});
}}

async function retest() {{
    const btn = document.getElementById('retest-btn');
    const status = document.getElementById('status');
    btn.disabled = true;
    status.textContent = 'Building + testing...';

    const boxes = getBoxes();
    const params = new URLSearchParams();
    for (const [slot, box] of Object.entries(boxes)) {{
        params.set(slot + '_x', box.x.toFixed(4));
        params.set(slot + '_y', box.y.toFixed(4));
        params.set(slot + '_w', box.w.toFixed(4));
        params.set(slot + '_h', box.h.toFixed(4));
    }}

    try {{
        const resp = await fetch('/retest?' + params.toString());
        results = await resp.json();
        if (results.error) {{
            status.textContent = 'Error: ' + results.error;
        }} else {{
            const total = Object.keys(results).length;
            const passed = Object.values(results).filter(r => r.passed).length;
            status.textContent = `Done: ${{passed}}/${{total}} passed`;
        }}
    }} catch (e) {{
        status.textContent = 'Error: ' + e.message;
    }}
    btn.disabled = false;
    renderCards();
}}

// Initial render
renderCards();

// Listen for input changes to live-preview
document.querySelectorAll('input[type=number]').forEach(input => {{
    input.addEventListener('input', updateCrops);
}});
</script>
</body></html>"""


def main():
    global READER
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--reader" and i + 1 < len(args):
            READER = args[i + 1]

    port = 8788
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Crop Tuner running at http://localhost:{port}")
    print(f"Reader: {READER}")
    print(f"Press Ctrl+C to stop")

    import webbrowser
    webbrowser.open(f"http://localhost:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
