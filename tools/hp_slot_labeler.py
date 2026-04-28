#!/usr/bin/env python3
"""Quick labeler: assign opponent HP slot (s0/s1) to OpponentHPReader_Doubles test images.

Shows each image with both HP crop regions highlighted. Click the slot button,
then generates rename commands to add the slot to the filename.

Usage: python3 tools/hp_slot_labeler.py
"""
import base64, io, json, os, sys, webbrowser, tempfile
from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(REPO, "CommandLineTests", "PokemonChampions", "OpponentHPReader_Doubles")

# Doubles HP crop boxes [x, y, w, h] normalized
SLOTS = {
    "s0 (left)":  [0.694, 0.116, 0.041, 0.038],
    "s1 (right)": [0.8984, 0.1130, 0.0563, 0.0426],
}
SLOT_COLORS = {"s0 (left)": "#58a6ff", "s1 (right)": "#3fb950"}

def img_to_data_uri(img, fmt="JPEG"):
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=85)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"

def crop_to_data_uri(img, box):
    w, h = img.size
    x0, y0 = int(box[0]*w), int(box[1]*h)
    x1, y1 = x0 + int(box[2]*w), y0 + int(box[3]*h)
    crop = img.crop((x0, y0, x1, y1))
    # Upscale 4x
    crop = crop.resize((crop.width*4, crop.height*4), Image.NEAREST)
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"

def build_html():
    files = sorted(f for f in os.listdir(IMG_DIR) if f.lower().endswith(".png"))

    cards = []
    for f in files:
        path = os.path.join(IMG_DIR, f)
        img = Image.open(path).convert("RGB")

        # Draw overlay boxes on thumbnail
        thumb = img.copy()
        thumb.thumbnail((640, 360))
        draw = ImageDraw.Draw(thumb)
        sx, sy = thumb.width / img.width, thumb.height / img.height
        for name, box in SLOTS.items():
            color = SLOT_COLORS[name]
            x0 = int(box[0] * img.width * sx)
            y0 = int(box[1] * img.height * sy)
            x1 = x0 + int(box[2] * img.width * sx)
            y1 = y0 + int(box[3] * img.height * sy)
            draw.rectangle([x0, y0, x1, y1], outline=color, width=2)

        thumb_uri = img_to_data_uri(thumb)

        # Extract crops
        crop0_uri = crop_to_data_uri(img, SLOTS["s0 (left)"])
        crop1_uri = crop_to_data_uri(img, SLOTS["s1 (right)"])

        # Parse existing HP value from filename
        base = os.path.splitext(f)[0]
        hp_val = base.split("_")[-1]

        cards.append({
            "filename": f,
            "hp": hp_val,
            "thumb": thumb_uri,
            "crop0": crop0_uri,
            "crop1": crop1_uri,
        })

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>HP Slot Labeler</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d1117; color:#c9d1d9; font-family:'SF Mono',monospace; font-size:13px; padding:16px; }}
h1 {{ color:#58a6ff; margin-bottom:4px; }}
.stats {{ color:#8b949e; margin-bottom:16px; }}
.card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; margin-bottom:8px; display:flex; gap:12px; align-items:center; }}
.card.done {{ opacity:0.4; }}
.card img.thumb {{ border-radius:4px; }}
.crops {{ display:flex; flex-direction:column; gap:6px; }}
.crop {{ text-align:center; }}
.crop img {{ border:2px solid #30363d; border-radius:4px; image-rendering:pixelated; }}
.crop-label {{ font-size:10px; color:#8b949e; }}
.info {{ flex:1; }}
.fname {{ color:#58a6ff; font-weight:bold; font-size:12px; margin-bottom:4px; }}
.hp-val {{ color:#f0c040; font-size:14px; margin-bottom:8px; }}
.btns {{ display:flex; gap:6px; flex-wrap:wrap; }}
.btn {{ padding:6px 16px; border:1px solid #30363d; border-radius:6px; background:#21262d; color:#c9d1d9; cursor:pointer; font-size:13px; font-family:inherit; }}
.btn:hover {{ background:#30363d; }}
.btn.s0 {{ border-color:#58a6ff; color:#58a6ff; }}
.btn.s1 {{ border-color:#3fb950; color:#3fb950; }}
.btn.skip {{ border-color:#f85149; color:#f85149; }}
.btn.both {{ border-color:#d29922; color:#d29922; }}
.btn.selected {{ background:#1f6feb; color:#fff; border-color:#1f6feb; }}
.btn.s1.selected {{ background:#238636; border-color:#238636; }}
.btn.both.selected {{ background:#d29922; border-color:#d29922; color:#fff; }}
.btn.skip.selected {{ background:#da3633; border-color:#da3633; }}
.both-inputs {{ display:none; margin-top:6px; gap:8px; align-items:center; }}
.both-inputs.visible {{ display:flex; }}
.both-inputs label {{ font-size:11px; color:#8b949e; }}
.both-inputs input {{ width:50px; padding:3px 6px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; font-size:13px; font-family:inherit; text-align:center; }}
.done-bar {{ position:fixed; bottom:0; left:0; right:0; background:#161b22; border-top:1px solid #30363d; padding:12px 16px; display:flex; justify-content:space-between; align-items:center; z-index:10; }}
.done-bar button {{ padding:8px 24px; background:#238636; color:#fff; border:none; border-radius:6px; cursor:pointer; font-size:14px; font-family:inherit; }}
</style>
</head><body>
<h1>OpponentHPReader_Doubles — Slot Labeler</h1>
<div class="stats">{len(cards)} images · Assign each to s0 (left, <span style="color:#58a6ff">blue</span>) or s1 (right, <span style="color:#3fb950">green</span>)</div>
"""

    for i, c in enumerate(cards):
        html += f"""<div class="card" id="card-{i}">
    <img class="thumb" src="{c['thumb']}" width="640">
    <div class="crops">
        <div class="crop"><img src="{c['crop0']}" title="s0 left"><div class="crop-label" style="color:#58a6ff">s0 (left)</div></div>
        <div class="crop"><img src="{c['crop1']}" title="s1 right"><div class="crop-label" style="color:#3fb950">s1 (right)</div></div>
    </div>
    <div class="info">
        <div class="fname">{c['filename']}</div>
        <div class="hp-val">HP: {c['hp']}%</div>
        <div class="btns">
            <button class="btn s0" onclick="pick({i},'s0')">s0 (left)</button>
            <button class="btn s1" onclick="pick({i},'s1')">s1 (right)</button>
            <button class="btn both" onclick="pickBoth({i})">Both</button>
            <button class="btn skip" onclick="pick({i},'skip')">Skip / Delete</button>
        </div>
        <div class="both-inputs" id="both-{i}">
            <label style="color:#58a6ff">s0 HP%</label><input type="number" min="0" max="100" id="both-s0-{i}" value="{c['hp']}">
            <label style="color:#3fb950">s1 HP%</label><input type="number" min="0" max="100" id="both-s1-{i}" value="{c['hp']}">
            <button class="btn" onclick="confirmBoth({i})" style="padding:3px 12px;font-size:11px;">OK</button>
        </div>
    </div>
</div>
"""

    html += f"""
<div class="done-bar">
    <span id="progress">0 / {len(cards)} labeled</span>
    <button onclick="finish()">Generate Renames</button>
</div>

<script>
const files = {json.dumps([c['filename'] for c in cards])};
const labels = {{}};

function pick(idx, slot) {{
    labels[idx] = {{slot: slot}};
    const card = document.getElementById('card-' + idx);
    card.querySelectorAll('.btn').forEach(b => b.classList.remove('selected'));
    card.querySelector('.btn.' + slot).classList.add('selected');
    card.classList.add('done');
    document.getElementById('both-' + idx).classList.remove('visible');
    document.getElementById('progress').textContent = Object.keys(labels).length + ' / ' + files.length + ' labeled';
    scrollNext(idx);
}}

function pickBoth(idx) {{
    const card = document.getElementById('card-' + idx);
    card.querySelectorAll('.btn').forEach(b => b.classList.remove('selected'));
    card.querySelector('.btn.both').classList.add('selected');
    document.getElementById('both-' + idx).classList.add('visible');
    document.getElementById('both-s0-' + idx).focus();
}}

function confirmBoth(idx) {{
    const hp0 = document.getElementById('both-s0-' + idx).value;
    const hp1 = document.getElementById('both-s1-' + idx).value;
    labels[idx] = {{slot: 'both', hp0: parseInt(hp0), hp1: parseInt(hp1)}};
    const card = document.getElementById('card-' + idx);
    card.classList.add('done');
    document.getElementById('progress').textContent = Object.keys(labels).length + ' / ' + files.length + ' labeled';
    scrollNext(idx);
}}

function scrollNext(idx) {{
    for (let i = idx + 1; i < files.length; i++) {{
        if (!(i in labels)) {{
            document.getElementById('card-' + i).scrollIntoView({{behavior:'smooth', block:'center'}});
            break;
        }}
    }}
}}

function finish() {{
    const lines = [];
    const deletes = [];
    for (const [idx, label] of Object.entries(labels)) {{
        const f = files[idx];
        if (label.slot === 'skip') {{
            deletes.push(f);
            continue;
        }}
        const base = f.replace(/\\.png$/i, '');
        const parts = base.split('_');
        const hp = parts.pop();
        const prefix = parts.join('_');

        if (label.slot === 'both') {{
            // Duplicate: copy to s0 with hp0, rename original to s1 with hp1
            lines.push(`cp "${{f}}" "${{prefix}}_s0_${{label.hp0}}.png"`);
            lines.push(`mv "${{f}}" "${{prefix}}_s1_${{label.hp1}}.png"`);
        }} else {{
            const newName = prefix + '_' + label.slot + '_' + hp + '.png';
            if (f !== newName) lines.push(`mv "${{f}}" "${{newName}}"`);
        }}
    }}

    let output = '#!/bin/bash\\ncd "{IMG_DIR}"\\n\\n';
    if (deletes.length) {{
        output += '# Delete skipped\\n';
        deletes.forEach(f => output += `rm "${{f}}"\\n`);
        output += '\\n';
    }}
    if (lines.length) {{
        output += '# Rename with slot\\n';
        lines.forEach(l => output += l + '\\n');
    }}

    const pre = document.createElement('pre');
    pre.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#161b22;border:2px solid #58a6ff;border-radius:8px;padding:24px;max-height:80vh;overflow:auto;z-index:100;white-space:pre-wrap;font-size:12px;min-width:600px;';
    pre.textContent = output;

    const copyBtn = document.createElement('button');
    copyBtn.textContent = 'Copy to clipboard';
    copyBtn.style.cssText = 'margin-top:12px;padding:6px 16px;background:#238636;color:#fff;border:none;border-radius:6px;cursor:pointer;';
    copyBtn.onclick = () => {{ navigator.clipboard.writeText(output); copyBtn.textContent = 'Copied!'; }};
    pre.appendChild(document.createElement('br'));
    pre.appendChild(copyBtn);

    document.body.appendChild(pre);
}}
</script>
</body></html>"""
    return html

if __name__ == "__main__":
    html = build_html()
    out = os.path.join(tempfile.gettempdir(), "hp_slot_labeler.html")
    with open(out, "w") as f:
        f.write(html)
    print(f"Written to {out}")
    webbrowser.open(f"file://{out}")
