#!/usr/bin/env python3
"""
Generate a C++ lookup header for AbilityItemReader from
data/ps_data/{abilities,items}.json.

For each ability/item, the table maps the slugified display name
("Rough Skin" -> "rough-skin") to its kind ("ability" or "item"). The
reader OCRs text like "Garchomp's Rough Skin!", parses out the
"name" half, slugifies it, and looks up the kind here.

Output: SerialPrograms/Source/PokemonChampions/Inference/
        PokemonChampions_AbilityItemTable_Generated.cpp
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PS_DATA = REPO / "data/ps_data"
OUT = REPO / "SerialPrograms/Source/PokemonChampions/Inference/PokemonChampions_AbilityItemTable_Generated.cpp"


def slugify(name: str) -> str:
    """'Rough Skin' -> 'rough-skin'; 'Choice Specs' -> 'choice-specs'."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def collect():
    entries = []  # (slug, kind, display)
    seen = {}    # slug -> kind (for collision detection)

    abilities = json.loads((PS_DATA / "abilities.json").read_text())
    for key, info in abilities.items():
        if info.get("isNonstandard"):
            continue
        display = info.get("name", "")
        if not display:
            continue
        slug = slugify(display)
        if not slug or slug in seen:
            continue
        seen[slug] = "ability"
        entries.append((slug, "ability", display))

    items = json.loads((PS_DATA / "items.json").read_text())
    for key, info in items.items():
        if info.get("isNonstandard"):
            continue
        display = info.get("name", "")
        if not display:
            continue
        slug = slugify(display)
        if not slug or slug in seen:
            # Ability + item with same slugged name (rare). Keep ability;
            # log skip.
            print(f"  collision skip: {slug!r} (ability had {display!r})")
            continue
        seen[slug] = "item"
        entries.append((slug, "item", display))

    return sorted(entries, key=lambda e: e[0])


def emit(entries):
    lines = []
    lines.append("//  AUTO-GENERATED. Do not edit.")
    lines.append("//  Regen: python3 tools/generate_ability_item_table.py")
    lines.append("")
    lines.append('#include "PokemonChampions_AbilityItemTable.h"')
    lines.append("")
    lines.append("#include <unordered_map>")
    lines.append("#include <vector>")
    lines.append("#include <string>")
    lines.append("#include <algorithm>")
    lines.append("")
    lines.append("namespace PokemonAutomation{")
    lines.append("namespace NintendoSwitch{")
    lines.append("namespace PokemonChampions{")
    lines.append("")
    lines.append("namespace{")
    lines.append("//  slug -> kind ('ability' or 'item').")
    lines.append("//  Generated from data/ps_data/abilities.json + items.json.")
    lines.append("const std::unordered_map<std::string, AbilityItemKind>& table(){")
    lines.append("    static const std::unordered_map<std::string, AbilityItemKind> t = {")
    for slug, kind, display in entries:
        kind_enum = "AbilityItemKind::ABILITY" if kind == "ability" else "AbilityItemKind::ITEM"
        # escape the slug — slugs are ASCII a-z0-9-, no escapes needed
        lines.append(f'        {{"{slug}", {kind_enum}}}, // {display}')
    lines.append("    };")
    lines.append("    return t;")
    lines.append("}")
    lines.append("}  //  anon namespace")
    lines.append("")
    lines.append("AbilityItemKind lookup_ability_item_kind(const std::string& slug){")
    lines.append("    const auto& t = table();")
    lines.append("    auto it = t.find(slug);")
    lines.append("    if (it == t.end()) return AbilityItemKind::UNKNOWN;")
    lines.append("    return it->second;")
    lines.append("}")
    lines.append("")
    lines.append("//  Cap distance computation early. For long slugs this is fast enough")
    lines.append("//  for a 563-entry table (one read), and we'd rather a O(N) scan than")
    lines.append("//  maintain a separate trie/BK-tree.")
    lines.append("static size_t levenshtein(const std::string& a, const std::string& b, size_t cap){")
    lines.append("    size_t la = a.size(), lb = b.size();")
    lines.append("    if (la > lb + cap || lb > la + cap) return cap + 1;")
    lines.append("    std::vector<size_t> prev(lb + 1), cur(lb + 1);")
    lines.append("    for (size_t j = 0; j <= lb; j++) prev[j] = j;")
    lines.append("    for (size_t i = 1; i <= la; i++){")
    lines.append("        cur[0] = i;")
    lines.append("        size_t row_min = cur[0];")
    lines.append("        for (size_t j = 1; j <= lb; j++){")
    lines.append("            size_t cost = (a[i-1] == b[j-1]) ? 0 : 1;")
    lines.append("            cur[j] = std::min({prev[j] + 1, cur[j-1] + 1, prev[j-1] + cost});")
    lines.append("            row_min = std::min(row_min, cur[j]);")
    lines.append("        }")
    lines.append("        if (row_min > cap) return cap + 1;")
    lines.append("        std::swap(prev, cur);")
    lines.append("    }")
    lines.append("    return prev[lb];")
    lines.append("}")
    lines.append("")
    lines.append("AbilityItemKind fuzzy_lookup_ability_item_kind(")
    lines.append("    const std::string& slug, std::string* corrected_out, size_t max_distance")
    lines.append("){")
    lines.append("    const auto& t = table();")
    lines.append("    size_t best = max_distance + 1;")
    lines.append("    const std::string* best_slug = nullptr;")
    lines.append("    AbilityItemKind best_kind = AbilityItemKind::UNKNOWN;")
    lines.append("    for (const auto& kv : t){")
    lines.append("        size_t d = levenshtein(slug, kv.first, best);")
    lines.append("        if (d < best){")
    lines.append("            best = d;")
    lines.append("            best_slug = &kv.first;")
    lines.append("            best_kind = kv.second;")
    lines.append("            if (d == 0) break;")
    lines.append("        }")
    lines.append("    }")
    lines.append("    if (best_slug && corrected_out) *corrected_out = *best_slug;")
    lines.append("    return best_kind == AbilityItemKind::UNKNOWN ? AbilityItemKind::UNKNOWN : best_kind;")
    lines.append("}")
    lines.append("")
    lines.append("size_t ability_item_table_size(){ return table().size(); }")
    lines.append("")
    lines.append("}}}")
    return "\n".join(lines) + "\n"


def main():
    entries = collect()
    print(f"emitting {len(entries)} entries to {OUT}")
    OUT.write_text(emit(entries))


if __name__ == "__main__":
    main()
