"""Drive Layer 2 encoding (parsed parquet -> encoded .pt shards).

Bootstraps vocabs on first use, encodes both meta-on and meta-off modes for
every parsed bucket. Idempotent: re-encodes only buckets whose .pt is missing
or older than the parsed parquet.

Usage:
    python scripts/run_layer2_encode.py                              # both modes, default version
    python scripts/run_layer2_encode.py --modes meta-on               # one mode
    python scripts/run_layer2_encode.py --encoding-version v3         # default
    python scripts/run_layer2_encode.py --rebuild-vocabs              # rescan + save
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.vgc_model.data.encode_runner import (
    bootstrap_vocabs,
    run_all_encoding,
)
from src.vgc_model.data.encoder import Encoder
from src.vgc_model.data.vocab import Vocabs


DEFAULT_PARSED_ROOT = PROJECT_ROOT / "data" / "parsed"
DEFAULT_ENCODED_ROOT = PROJECT_ROOT / "data" / "encoded"
DEFAULT_VOCAB_DIR = PROJECT_ROOT / "data" / "vocab"


def get_or_build_vocabs(
    parsed_root: Path, fmt: str, vocab_dir: Path, rebuild: bool,
) -> Vocabs:
    expected = vocab_dir / "species.json"
    if not rebuild and expected.exists():
        v = Vocabs.load(vocab_dir)
        v.freeze_all()
        return v
    print(f"Bootstrapping vocabs from {parsed_root}/{fmt} ...", flush=True)
    started = time.time()
    v = bootstrap_vocabs(parsed_root, fmt)
    v.save(vocab_dir)
    print(
        f"  vocabs built in {time.time()-started:.1f}s — "
        f"species:{len(v.species)} moves:{len(v.moves)} abilities:{len(v.abilities)} "
        f"items:{len(v.items)} status:{len(v.status)} weather:{len(v.weather)} "
        f"terrain:{len(v.terrain)}",
        flush=True,
    )
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsed-root", type=Path, default=DEFAULT_PARSED_ROOT)
    ap.add_argument("--encoded-root", type=Path, default=DEFAULT_ENCODED_ROOT)
    ap.add_argument("--vocab-dir", type=Path, default=DEFAULT_VOCAB_DIR)
    ap.add_argument("--format", default="gen9championsvgc2026regma")
    ap.add_argument("--encoding-version", default="v3")
    ap.add_argument(
        "--modes", nargs="+", default=["meta-on", "meta-off"],
        choices=["meta-on", "meta-off"],
    )
    ap.add_argument("--rebuild-vocabs", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    vocabs = get_or_build_vocabs(
        args.parsed_root, args.format, args.vocab_dir, args.rebuild_vocabs,
    )

    overall_start = time.time()
    grand = {"buckets": 0, "fresh": 0, "samples": 0}
    for mode in args.modes:
        encoder = Encoder(vocabs, mode=mode)  # type: ignore[arg-type]
        result = run_all_encoding(
            parsed_root=args.parsed_root,
            encoded_root=args.encoded_root,
            fmt=args.format,
            encoding_version=args.encoding_version,
            mode=mode,  # type: ignore[arg-type]
            encoder=encoder,
            force=args.force,
            limit=args.limit,
        )
        if not args.quiet:
            print(
                f"[{args.encoding_version}/{mode}] buckets={result['buckets']} "
                f"fresh={result['fresh']} samples={result['samples']} "
                f"took={result['took_sec']:.1f}s"
            )
        for k in ("buckets", "fresh", "samples"):
            grand[k] += result[k]

    overall_elapsed = time.time() - overall_start
    print(
        f"\nTOTAL ({overall_elapsed:.1f}s): "
        f"buckets={grand['buckets']} fresh={grand['fresh']} samples={grand['samples']}"
    )


if __name__ == "__main__":
    main()
