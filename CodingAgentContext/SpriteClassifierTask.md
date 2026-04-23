# Task: Opponent Team Sprite Classifier — identify opponent's 6 Pokémon from team preview

## Goal

Identify all 6 opponent Pokémon species from the **pre-battle team preview screen** (the "bring-6, pick-4" stage in Doubles), where opposing Pokémon are shown as **sprites only — no names**.

Success metric: when entering battle, `BattleStateTracker.m_opp_team` is populated with all 6 species slugs, so the AI has full opponent information from turn 1 instead of learning species one at a time as they switch in.

---

## Context

### What's already done

- **Own team scanning** (Team Scanner task, complete): we already know our own 6 Pokémon before matchmaking via the "Moves & More" grid.
- **Opponent HUD reading** (existing): `BattleHUDReader::read_opponent_species()` already reads opponent species from the battle HUD as they switch in.
- **Sprite matching infrastructure** exists and is battle-tested in other games.

### What's missing

- The team preview screen shows **sprites without names** for both teams, and reading them would give us opponent species **before turn 1**, enabling:
  - Lead prediction
  - Coverage analysis ("my Kingambit fears his Lucario-Mega — switch in Garchomp first")
  - Threat assessment from the first action

---

## Existing infrastructure we can reuse

### Image-matching classes (in `CommonTools/ImageMatch/`)

| Class | Use case | Notes |
|---|---|---|
| `ExactImageDictionaryMatcher` | Template match against a named dictionary | RMSD with brightness compensation |
| `CroppedImageDictionaryMatcher` | As above, with auto-cropping of input | Subclasses implement `get_crop_candidates()` |
| `SilhouetteDictionaryMatcher` | Alpha-mask-aware matching | Used in SV Tera silhouette reading |
| `WeightedExactImageMatcher` | Variant weighting RMSD by stddev | For sprites with lots of flat background |

### Sprite database format (proven in SwSh, SV, LA, Home)

```
Resources/PokemonChampions/
  PokemonSprites.png      -- atlas: all species in a grid
  PokemonSprites.json     -- {"spriteWidth":N, "spriteHeight":N,
                             "spriteLocations":{"kingambit":{"top":Y,"left":X},...}}
```

Loaded via `SpriteDatabase(png_path, json_path)` constructor.

### Closest prior art

- **`PokemonSpriteMatcherCropped`** (SwSh) — best fit. Auto-crops via Euclidean distance to background color, matches cropped input against dictionary.
- **`PokeballSpriteMatcher`** (Home) — cleanest integration pattern: constructor loads templates once, `read_ball(image)` per-frame.

### What the codebase does NOT have

- **No sprite extraction script** from in-game captures. We'd need to build one (or do it by hand).
- **No perceptual hashing** — the codebase relies on RMSD template matching. Good for us; sprites are rendered consistently, so RMSD will work well.

---

## Proposed phases

### Phase 1 — Screen capture & coordinate measurement

**Blocker:** we need a team preview screenshot. Screenshots 457 / 419 / 477 / 800 / 816 / 713 don't cover this screen.

Actions:
1. Capture a team preview screenshot during normal gameplay (auto-screenshot via `DetectorTest`).
2. Use `tools/pixel_inspector.py --measure` to define the 6 own + 6 opp sprite boxes (12 measurements).
3. Add a color-gate region for screen detection (background color or a stable UI element).

**Output:** 12 `ImageFloatBox` coordinates + detector color gate, saved to `tools/box_definitions.json`.

---

### Phase 2 — Sprite database bootstrap (the hard part)

We need **one canonical reference sprite per species** (~315 species in the Champions roster) in the atlas PNG. Options, ranked by effort:

#### Option A — Auto-bootstrap during gameplay *(recommended)*

Build a capture mode that runs alongside AutoLadder:

- **Trigger:** on the team preview screen, crop each of the 12 sprite regions.
- **Label:** during the subsequent battle, match each sprite to a species via `BattleHUDReader::read_opponent_species()` as Pokémon switch in.
- **Correlate:** store `(sprite_image, species_slug)` pairs in a labelled cache directory.
- **Dedup:** keep the highest-confidence exemplar per species.

After N battles, we have a self-assembled sprite database. Cold start is slow (~50 games to cover 315 species if each battle reveals ~4-6 new species). Can be accelerated by cherry-picking battles against common meta Pokémon.

#### Option B — Manual seed from Moves & More

The Moves & More tab shows small sprites next to each Pokémon card along with the species name (readable via existing OCR). We could batch-scan many teams' Moves & More pages and auto-extract (sprite, species) pairs.

- **Pro:** fast — cycle through team builds, read species names as ground truth.
- **Con:** Moves & More sprite pose/scale **may differ** from team preview sprite. Need to verify. If they differ, this bootstrap won't transfer.

#### Option C — Rip from game assets

If Pokémon Champions uses packaged sprite files (e.g. Unity assetbundles), we could extract them directly. Out of scope for this repo and probably against TOS.

#### Recommendation

**Option A is the robust path.** Infrastructure work:

- New program `SpriteCapture` (or mode added to `DetectorTest`): save opponent sprites labeled with species as they're revealed.
- New Python script `tools/build_sprite_atlas.py`: consume the cache directory, produce `PokemonSprites.png` + `PokemonSprites.json`.
- Ship an initial atlas covering the top ~50 meta species to make the feature useful on day one. Grow it over time.

---

### Phase 3 — Sprite matcher class

New file: `PokemonChampions/Inference/PokemonChampions_SpriteMatcher.h/.cpp`

```cpp
class PokemonChampionsSpriteMatcher : public CroppedImageDictionaryMatcher {
public:
    static const PokemonChampionsSpriteMatcher& instance();
    std::string match(const ImageViewRGB32& cropped, double& confidence_out) const;
protected:
    std::vector<ImagePixelBox> get_crop_candidates(...) const override;
private:
    PokemonChampionsSpriteMatcher();   // loads PokemonSprites.{png,json}
};
```

Interface mirrors `PokeballSpriteMatcher` (Home). Threshold tuning uses whatever `alpha_spread` / Euclidean values the bootstrap data validates against.

---

### Phase 4 — Team preview reader + detector

New files: `PokemonChampions_TeamPreviewDetector.h/.cpp`, `PokemonChampions_TeamPreviewReader.h/.cpp`.

`TeamPreviewDetector` — color-gate on a stable UI region confirming we're on this screen.

`TeamPreviewReader`:

```cpp
struct TeamPreview {
    std::array<std::string, 6> own_species;     // our team's sprite-inferred species
    std::array<std::string, 6> opp_species;     // opponent's — the valuable part
};

class TeamPreviewReader {
public:
    void make_overlays(VideoOverlaySet&) const;
    TeamPreview read(Logger&, const ImageViewRGB32&) const;
private:
    std::array<ImageFloatBox, 6> m_own_sprites;
    std::array<ImageFloatBox, 6> m_opp_sprites;
};
```

For each of the 12 boxes: crop → `PokemonChampionsSpriteMatcher::match()` → store slug.

---

### Phase 5 — AutoLadder integration

Wire between existing `enter_matchmaking()` and `wait_for_battle_start()`:

```cpp
// New step after matchmaking finds opponent
void scan_opponent_from_preview(env, context) {
    TeamPreviewWatcher watcher;
    if (wait_until(env, 5s, {watcher}) < 0) return;
    TeamPreview preview = TeamPreviewReader().read(env.console, snapshot);
    m_state_tracker.set_opp_team_preview(preview.opp_species);
}
```

Add `BattleStateTracker::set_opp_team_preview(std::array<std::string, 6>)` which populates `m_opp_team[].species` without marking them as "seen" (they're not on-field yet).

---

## Risk assessment

| Risk | Severity | Mitigation |
|---|---|---|
| Sprite database bootstrap is slow (many games needed) | Medium | Ship progressive coverage; each correctly-matched sprite helps future games |
| Sprite appearance differs between team preview and HUD | High | Verify against a screenshot before committing to Option A; if different, need separate matchers |
| Sprites animate (breathing, eye blinks) and match fails | Medium | Use multi-frame reference or average frame; fallback: `SilhouetteDictionaryMatcher` |
| Mega-evolved sprites look different from base forms | High | Separate slugs for `kingambit-mega` etc. — already how the OCR dictionary handles it |
| 315 sprites × RMSD is slow on team preview | Low | CPU profiled well in SwSh (<100ms); subset matching available |
| Team preview time-limited (~30s to lock in) | Low | Do sprite classification in parallel with own-team pick animation |

---

## Dependencies / open questions before starting

1. **Need a team preview screenshot** to measure coordinates. Can be captured next time ColePC is in a doubles match, queued until "Preparing for Battle".
2. **Verify if Moves & More sprites == team preview sprites** (visual inspection). Determines whether Option B bootstrap is viable.
3. **Decide on cold-start behavior** — what happens when we encounter an un-databased sprite? Log unknown, fall back to HUD-driven reveal? Probably yes.
4. **Where to store the growing sprite cache** — committed to the repo (simple, but PNGs bloat git history) or kept local (tools/sprite_cache/ in .gitignore)?

---

## Proposed first-pass deliverable (1-2 sessions of work)

1. Capture team preview screenshot, measure 12 boxes via `--measure`.
2. `TeamPreviewDetector` (color-gate only, no reader yet).
3. Auto-capture mode in AutoLadder: save cropped opponent sprites + HUD-revealed species to `data/sprite_cache/`.
4. After 10+ battles worth of captures, build v1 atlas covering whatever species we've seen.
5. `PokemonChampionsSpriteMatcher` + `TeamPreviewReader` using v1 atlas.
6. Wire into AutoLadder; fall back gracefully to HUD-reveal when unknown sprite.

Phase 1-3 can proceed before Phase 5 is reached.

---

## Not doing now

- Opponent item detection from preview (items aren't shown on the preview screen — same gap as own-team scanning).
- Shiny detection (different problem, different matcher).
- Item/move changes between matchups (dynamic content not on the preview).
