#!/usr/bin/env python3
"""
Build a HUD-pill atlas from manifest-labeled BattleHUDReader frames.

For each labeled frame in test_images/{action_menu,move_select}, extract the 4
HUD pill crops (opp_0, opp_1, own_0, own_1), label them with the corresponding
manifest species, and accumulate per-(side, species) reference crops.

Outputs:
  data/hud_pill_atlas/refs/<side>__<species>__<frame>__slot<i>.png
                             - 50x50 RGB crop, one per labeled instance
  data/hud_pill_atlas/index.json
                             - {(side, species): {refs:[...], count:N}}
                             Used by the dashboard view + the C++ matcher.

The matcher consumes the per-species AVERAGED reference (computed on demand
from the refs in index.json) and does plain RGB-RMSD vs each query crop.
On a leave-one-frame-out eval (137 samples, 13 species), this beats the
canonical Bulbapedia atlas by ~70pp top-1.

Re-run after every batch of new labeled frames to grow the atlas.
"""
import json, glob, os, shutil, sys
from collections import defaultdict
from pathlib import Path
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
TEST_IMAGES = REPO / "test_images"
OUT_DIR = REPO / "data" / "hud_pill_atlas"
REFS_DIR = OUT_DIR / "refs"
INDEX_PATH = OUT_DIR / "index.json"

#  Pill ICON regions (the sprite-bearing rectangle, NOT the name text bar).
#  Tuned 2026-05-06: opp shifted right 1px + top up 1px + bottom down ~4px;
#  own top up ~6px to capture the upper portion of the icon clipped at default.
#  1 px on 1920x1080 ≈ 0.00052 in x and 0.00093 in y.
#  Normalized: uniform 108x96 px (≈0.0563 x 0.0889) per slot, plus uniform
#  y per side (slot 0 and 1 share the same vertical strip). x kept per-slot
#  since the two pills sit at different horizontal positions on each side.
PILL_BOXES = {
    "opp_0": (0.5680, 0.0499, 0.0563, 0.0889),
    "opp_1": (0.7724, 0.0499, 0.0563, 0.0889),
    "own_0": (0.0245, 0.8718, 0.0563, 0.0889),
    "own_1": (0.2307, 0.8718, 0.0563, 0.0889),
}

CROP_SIZE = (50, 50)


def slug_norm(s: str) -> str:
    """Lowercase + strip; do NOT collapse mega/shiny variants. Each visual
    variant gets its own atlas entry — averaging gengar + gengar-mega
    yields a blend that matches neither well."""
    return (s or "").lower().strip()


def slot_box_name(slot: str):
    """slot 'opp_0' -> ('opp', 0)."""
    side, idx = slot.split("_")
    return side, int(idx)


def collect_samples():
    """Walk action_menu + move_select manifests, return list of
    (side, species, frame_path, frame_name, slot_idx, box_coords)."""
    samples = []
    for screen in ("action_menu", "move_select"):
        manifest_path = TEST_IMAGES / screen / "manifest.json"
        if not manifest_path.exists(): continue
        manifest = json.loads(manifest_path.read_text())
        for fname, entry in manifest.items():
            if not isinstance(entry, dict): continue
            bhr = entry.get("BattleHUDReader") or {}
            opp = bhr.get("opponent_species") or []
            own = bhr.get("own_species") or []
            for side, species_list in (("opp", opp), ("own", own)):
                for i in range(2):
                    sp = species_list[i] if i < len(species_list) else ""
                    if not sp: continue
                    slot = f"{side}_{i}"
                    box = PILL_BOXES.get(slot)
                    if not box: continue
                    samples.append({
                        "side": side, "species": slug_norm(sp),
                        "frame_path": str(TEST_IMAGES / screen / fname),
                        "frame": fname, "slot": i, "slot_name": slot,
                        "box": list(box),
                    })
    return samples


def extract_and_write(sample, out_dir):
    img = Image.open(sample["frame_path"]).convert("RGB")
    W, H = img.size
    x, y, w, h = sample["box"]
    box = (int(x*W), int(y*H), int((x+w)*W), int((y+h)*H))
    crop = img.crop(box).resize(CROP_SIZE)
    frame_id = sample["frame"].replace(".png", "")
    name = f'{sample["side"]}__{sample["species"]}__{frame_id}__slot{sample["slot"]}.png'
    out = out_dir / name
    crop.save(out)
    return name


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    REFS_DIR.mkdir(parents=True, exist_ok=True)

    samples = collect_samples()
    print(f"Found {len(samples)} labeled HUD-pill samples.")

    by_key = defaultdict(list)  # (side, species) -> [ref filenames]
    for s in samples:
        try:
            ref_name = extract_and_write(s, REFS_DIR)
            by_key[(s["side"], s["species"])].append({
                "ref": ref_name,
                "source_frame": s["frame"],
                "slot": s["slot"],
            })
        except Exception as e:
            print(f"  ERR {s['frame']} {s['slot_name']}: {e}", file=sys.stderr)

    index = {}
    for (side, sp), refs in sorted(by_key.items()):
        index.setdefault(side, {})[sp] = {
            "count": len(refs),
            "refs": refs,
            "box": list(PILL_BOXES[f"{side}_0"]),  # nominal
        }

    INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {INDEX_PATH}")
    print("\nPer-side coverage:")
    for side in ("opp", "own"):
        species = index.get(side, {})
        total_refs = sum(v["count"] for v in species.values())
        print(f"  {side}: {len(species)} species, {total_refs} reference crops")
        thin = [(sp, v["count"]) for sp, v in species.items() if v["count"] < 3]
        if thin:
            print(f"    thin (<3 refs):", ", ".join(f"{sp}({c})" for sp, c in thin))


if __name__ == "__main__":
    main()
