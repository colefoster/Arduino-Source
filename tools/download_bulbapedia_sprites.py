#!/usr/bin/env python3
"""
Download Pokemon Champions menu sprites from Bulbagarden Archives.

Uses the MediaWiki API to list Category:Champions_menu_sprites and
fetch direct URLs in bulk, then downloads each PNG via cloudscraper
(bypasses CloudFlare challenge).

Usage:
  pip install cloudscraper
  python3 tools/download_bulbapedia_sprites.py            (download all)
  python3 tools/download_bulbapedia_sprites.py --list     (just list)
  python3 tools/download_bulbapedia_sprites.py --limit 20 (first 20)
"""

import os
import sys
import time

import cloudscraper


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(REPO_ROOT, "data", "sprite_reference")

API_URL = "https://archives.bulbagarden.net/w/api.php"
CATEGORY = "Category:Champions menu sprites"


def make_scraper():
    s = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'darwin', 'mobile': False}
    )
    return s


def list_all_files(scraper):
    """Use the API to enumerate files with imageinfo (URL + dimensions) in one pass."""
    items = []
    cont = {}
    while True:
        params = {
            'action': 'query',
            'format': 'json',
            'generator': 'categorymembers',
            'gcmtitle': CATEGORY,
            'gcmlimit': '500',
            'gcmtype': 'file',
            'prop': 'imageinfo',
            'iiprop': 'url|size',
        }
        params.update(cont)
        r = scraper.get(API_URL, params=params)
        r.raise_for_status()
        data = r.json()

        pages = data.get('query', {}).get('pages', {})
        for page in pages.values():
            title = page['title']                        # e.g. "File:Menu CP 0003.png"
            filename = title.split(':', 1)[1].replace(' ', '_')  # "Menu_CP_0003.png"
            ii = page.get('imageinfo', [{}])[0]
            url = ii.get('url')
            if url:
                items.append({
                    'filename': filename,
                    'url': url,
                    'width': ii.get('width'),
                    'height': ii.get('height'),
                    'size': ii.get('size'),
                })
        if 'continue' not in data:
            break
        cont = data['continue']
        time.sleep(0.2)
    # Sort for deterministic order
    items.sort(key=lambda x: x['filename'])
    return items


def download(scraper, item, out_path):
    r = scraper.get(item['url'])
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    if not r.content.startswith(b'\x89PNG'):
        return False, "not a PNG"
    with open(out_path, 'wb') as f:
        f.write(r.content)
    return True, f"{len(r.content)}B {item['width']}x{item['height']}"


def main():
    limit = None
    list_only = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--list':
            list_only = True
        elif args[i] == '--limit' and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 1
        i += 1

    os.makedirs(OUT_DIR, exist_ok=True)
    scraper = make_scraper()

    print("Querying MediaWiki API...")
    items = list_all_files(scraper)
    print(f"Discovered {len(items)} files in {CATEGORY}.\n")

    if list_only:
        for it in items:
            print(f"  {it['filename']}  {it['width']}x{it['height']}  {it['size']}B")
        return

    if limit:
        items = items[:limit]
        print(f"Limiting to first {limit}.\n")

    ok = skipped = 0
    failed = []
    for i, it in enumerate(items):
        out = os.path.join(OUT_DIR, it['filename'])
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            skipped += 1
            continue
        print(f"[{i+1}/{len(items)}] {it['filename']}... ", end='', flush=True)
        try:
            success, msg = download(scraper, it, out)
            print(msg if success else f"FAIL ({msg})")
            if success:
                ok += 1
            else:
                failed.append((it['filename'], msg))
        except Exception as e:
            print(f"EXC ({e})")
            failed.append((it['filename'], str(e)))
        time.sleep(0.2)

    print()
    print(f"Downloaded: {ok}, Skipped (cached): {skipped}, Failed: {len(failed)}")
    if failed:
        print("Failures:")
        for fn, msg in failed:
            print(f"  {fn}: {msg}")
    print(f"\nOutput: {OUT_DIR}")


if __name__ == "__main__":
    main()
