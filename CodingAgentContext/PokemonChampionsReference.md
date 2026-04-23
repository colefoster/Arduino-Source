# Pokémon Champions — Reference Document

Long-lived reference for the Pokémon Champions automation project. Compiled from public sources as of **April 2026** (just after NA launch). All claims are cited; anything not verifiable from an authoritative source is marked **[UNVERIFIED]**.

---

## 1. What is Pokémon Champions?

**Pokémon Champions** is a competitive battle-only spin-off in the Pokémon franchise. It is **not** a mainline RPG — there is no story campaign, overworld exploration, or wild-Pokémon catching in the traditional sense. The game is purpose-built as a battle simulator with official competitive integration.

| Field | Value |
|---|---|
| Developer | **The Pokémon Works** (joint venture of The Pokémon Company and ILCA) — this is their first title |
| Publishers | Nintendo (Switch, worldwide) and The Pokémon Company (iOS/Android) |
| Engine | Unity |
| Platforms | Nintendo Switch (incl. Switch 2 enhancements), iOS/iPadOS, Android |
| Switch Release | **April 8, 2026** (April 7 in North America) |
| Mobile Release | Later in 2026 (exact date TBA) |
| Genre | Turn-based strategy / competitive battler |
| Monetisation | Free-to-start; optional $9.99 Starter Pack; $4.99/mo or $49.99/yr membership; Battle Pass |
| Announcement | Pokémon Presents on **Feb 27, 2025**, alongside Pokémon Legends: Z-A gameplay reveal |

**Core pitch.** Pokémon Champions separates competitive play from the mainline RPGs. It hosts the official VGC circuit starting with the Malaysia Master Ball League (May 9–10, 2026) and Indianapolis Regionals (May 29–31, 2026) — these are the first regionals run on Champions instead of Scarlet/Violet.

Sources:
- [Wikipedia — Pokémon Champions](https://en.wikipedia.org/wiki/Pok%C3%A9mon_Champions)
- [Bulbapedia — Pokémon Champions](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_Champions)
- [Official site — champions.pokemon.com](https://champions.pokemon.com/en-us/)
- [Bulbagarden — Release date / VGC transition](https://bulbagarden.net/threads/pokemon-champions-release-date-announced-alongside-details-on-game-features-vgc-transitions-to-pokemon-champions-from-indianapolis-regionals-in-may.310191/)

---

## 2. Species Roster

### Totals

Reported counts vary by source and by whether alternate forms / Megas are counted separately:

| Source | Count | What is counted |
|---|---|---|
| Game8 / Bulbapedia list | **187 species** | Unique species eligible for battle |
| Game8 roster summary | **+59 Mega Evolution forms** | On top of 187 species → 246 entries |
| PikaChampions team builder | **263 Pokémon** | Species + Megas (different cut) |
| Serebii species database | **~382 entries** | Includes all alternate forms + Megas + regional variants |

Our in-repo Showdown paste / OCR dictionary contains ~315 entries, which falls between the "species + Megas" count (~246) and the "species + Megas + regional forms" count (~382). **[CROSS-CHECK]** that our dictionary includes all regional forms (Alolan, Galarian, Hisuian, Paldean) plus Megas — that would explain the 315 figure.

### Generations represented

Gen I through Gen IX are **all represented**, but the roster is curated — not a National Dex. Strongest representation is from Gen I (Kanto starters, Pikachu, Charizard etc.) and Gen VI/VII/IX where Mega / competitively-iconic species cluster.

### Inclusions / exclusions

- **No Legendaries or Mythicals.** Mewtwo, Rayquaza, Arceus, Zacian, Koraidon, Miraidon etc. are all excluded from the launch roster.
- **Mostly fully-evolved only.** Eviolite strategies built around NFE Pokémon are not possible.
- **Pikachu is the documented exception** to the fully-evolved rule — playable in Ranked/Casual despite not being a final stage.
- All regional starters from Gen I through Gen IX are included (e.g. Paldean starters Meowscarada, Skeledirge, Quaquaval).
- Competitive staples confirmed: Garchomp, Lucario, Hydreigon, Dragapult, Kingambit, Sinistcha, etc.

### Regulation sets

The roster is gated by seasonal "Regulation" sets. The launch regulation is **Regulation M-A** (April 8 – June 17, 2026). More Pokémon are expected to be added with subsequent regulations.

Sources:
- [Serebii — Available Pokémon](https://www.serebii.net/pokemonchampions/pokemon.shtml)
- [Bulbapedia — List of Pokémon in Champions](https://bulbapedia.bulbagarden.net/wiki/List_of_Pok%C3%A9mon_in_Pok%C3%A9mon_Champions)
- [Game8 — Complete roster](https://game8.co/games/Pokemon-Champions/archives/501889)
- [PikaChampions](https://pikachampions.com/)

---

## 3. Battle Formats

Champions supports two primary ranked formats. **Triples** and **Rotation** are **not supported**.

### Singles (BSS-style)

- Bring 6, pick 3 (**3v3 from a team of 6**).
- Known as **BSS** (Battle Stadium Singles) in broader Pokémon competitive parlance.
- Smogon has a dedicated Champions BSS subforum with viability rankings and role compendium (Regulation M-A).

### Doubles (VGC-style)

- Bring 6, pick 4 (**4v4 from a team of 6**).
- This is the **official VGC** format — the format run at all official Championship Series events.

### Ranked ladder structure

Separate ranks for Singles and Doubles — progress in one does not carry to the other. Each format has its own end-of-season rewards.

| Tier | Ranks | Advance threshold | Reward highlights (first-time) |
|---|---|---|---|
| **Poké Ball Tier** | Rank 4 → Rank 1 | 300 VP | Starting tier |
| **Great Ball Tier** | Rank 4 → Rank 1 | 300 VP | 1000 VP, "Great Trainer" title, +5 storage |
| **Ultra Ball Tier** | Rank 4 → Rank 1 | 300 VP | 1000 VP, "Ultra Trainer" title, +5 storage |
| **Master Ball Tier** | Rank 4 → Rank 1 | 300 VP | 1000 VP, "Master Trainer" title, +10 storage |
| **Champion Tier** | Single rank | Unlisted | 20,000 VP for end-of-season retention |

- **Champion Tier** unlocks **one week after each season begins**.
- Win streaks grant bonus VP beyond the base win amount.
- Losing can reduce your rank (demotion is possible).

### Seasons & regulations

- **Regulation M-A** (April 8 – June 17, 2026) is the launch regulation.
- Inside a regulation there are numbered seasons (e.g. Season M-1 sits inside Regulation M-A).
- Regulations change the legal Pokémon pool and mechanics over time.

Sources:
- [Serebii — Ranked Battle](https://www.serebii.net/pokemonchampions/rankedbattle.shtml)
- [Game8 — Ranked Battles guide](https://game8.co/games/Pokemon-Champions/archives/588870)
- [Game8 — Singles vs Doubles](https://game8.co/games/Pokemon-Champions/archives/588873)
- [Smogon — Champions BSS viability rankings](https://www.smogon.com/forums/threads/pokemon-champions-bss-viability-rankings.3780943/)
- [Pokémon Showdown — Champions OU/VGC/BSS formats](https://x.com/PokemonShowdown/status/2042810836268519697)

---

## 4. Mega Evolution

Mega Evolution is a **headline feature** of Pokémon Champions and is enabled in the launch ranked ruleset.

### How it works in battle

- Activated via the **"Mega Evolution button"** in the action menu (**[UNVERIFIED]** whether this is R specifically on Switch — the button has not been publicly named in sources I found).
- Requires the trainer to equip an **Omni Ring** and the Pokémon to hold the corresponding **Mega Stone**.
- **One Mega per battle** per side.
- Once Mega'd, the form is **permanent for the match**, even if the Pokémon is switched out and brought back in.
- The Omni Ring is described as an extensible device — future updates will add **Z-Moves**, **Dynamax / Gigantamax**, and **Terastallization** via the same ring.

### Mega count

**~59 Mega Evolutions** are playable at launch, including 23 brand-new Megas introduced in **Pokémon Legends: Z-A** that receive their first confirmed abilities in Champions.

### Notable new Megas from Z-A

| Mega | New Ability | Effect |
|---|---|---|
| Mega Excadrill | **Piercing Drill** | Contact moves bypass Protect/Detect for 25% damage |
| Mega Scovillain | **Spicy Spray** | Burns any attacker that hits Scovillain with a damaging move |
| Mega Feraligatr | **Dragonize** | Normal-type moves become Dragon-type, +20% power |
| Mega Meganium | **Mega Sol** | Acts as if harsh sunlight were always active |
| Mega Floette (Eternal Flower) | Fairy Aura | Powerful Light of Ruin sweeper |
| Mega Delphox | Levitate | Ground immunity |

### Existing Megas (examples confirmed in roster)

Charizard X/Y, Venusaur, Blastoise, Alakazam, Gengar (Shadow Tag), Garchomp, Lucario, Greninja (Protean), plus dozens of other classic and Z-A Megas. Full list on Game8 / Serebii.

### Champions-only Mega Stones

Some Mega Stones are tied to specific acquisition paths:

- **Chesnaughtite, Delphoxite, Greninjite, Floettite** — earned by depositing a Pokémon from Pokémon Legends: Z-A via Pokémon Home.
- **Glimmoranite, Scovillainite, Drampanite** — purchasable in the in-game Shop.

Sources:
- [Game8 — All Mega Evolutions](https://game8.co/games/Pokemon-Champions/archives/592472)
- [Serebii — Mega Evolution Abilities](https://www.serebii.net/pokemonchampions/megaabilities.shtml)
- [Games.GG — All Megas & Abilities](https://games.gg/pokemon-champions/guides/pokemon-champions-all-mega-evolution-and-abilities/)
- [Kotaku — New Z-A Mega abilities](https://kotaku.com/pokemon-legends-z-a-mega-evolutions-abilities-champions-2000683952)
- [TheGamer — New Mega abilities](https://www.thegamer.com/pokemon-champions-all-new-mega-abilities/)

---

## 5. Items

### Total count

Serebii / Pokémon-Zone report approximately **110 held items** in the Champions meta. Our repo's 106 is close — slight differences are probably due to Mega Stones counted vs uncounted, or a small number of items added post-launch.

### Categories

**Type-boosting (18, one per type):** Black Belt (Fighting), Black Glasses (Dark), Charcoal (Fire), Dragon Fang (Dragon), Fairy Feather (Fairy), Hard Stone (Rock), Magnet (Electric), Metal Coat (Steel), Miracle Seed (Grass), Mystic Water (Water), Never-Melt Ice (Ice), Poison Barb (Poison), Sharp Beak (Flying), Silk Scarf (Normal), Silver Powder (Bug), Soft Sand (Ground), Spell Tag (Ghost), Twisted Spoon (Psychic).

**Survival / utility:** Focus Band, **Focus Sash**, King's Rock, **Leftovers**, Quick Claw, Scope Lens, Shell Bell, **Bright Powder**, White Herb, Choice Scarf, Choice Band, Choice Specs (**[UNVERIFIED]** specific Choice items).

**Species-specific:** Light Ball (boosts Pikachu's Attack and Sp. Atk).

**Mega Stones (~70+):** One per playable Mega, including the Champions-exclusive stones listed in §4.

### Champions-specific support items

- **Type Affinity Tickets** (one per type, 18 total) — boost encounter / recruitment rates for a given type. Earned via Achievements.
- **Teammate Ticket** — permanent recruitment of a Pokémon from the Roster Ranch.
- **Training Ticket** — waives VP cost for stat training.
- **Quick Coupon** — ranch-related speed-up.

These "Tickets" are **new to Champions** and do not exist in mainline games. They are tied to the Roster Ranch / Recruit system (Champions' replacement for catching).

Sources:
- [Serebii — Items](https://www.serebii.net/pokemonchampions/items.shtml)
- [Pokémon Zone — Items](https://www.pokemon-zone.com/champions/items/)
- [Game8 — Items list](https://game8.co/games/Pokemon-Champions/archives/588871)

---

## 6. Abilities

### Total count

Our repo has 135 abilities. The published ability list is largely the mainline Pokémon ability set, **plus four confirmed brand-new abilities** introduced in Champions (all tied to new Z-A Megas):

| Ability | Effect | Holder |
|---|---|---|
| **Piercing Drill** | Contact moves bypass Protect/Detect for 25% damage | Mega Excadrill |
| **Dragonize** | Normal moves → Dragon, +20% power | Mega Feraligatr |
| **Mega Sol** | Treats weather as harsh sunlight for the user's moves | Mega Meganium |
| **Spicy Spray** | Burns any attacker that hits the holder with a damaging move | Mega Scovillain |

### Hospitality

**Hospitality** is **not new to Champions** — it was introduced in Scarlet/Violet DLC (The Teal Mask, 2023) as Sinistcha's signature ability (heals an ally for 25% HP when the user enters battle). It carries over to Champions because Sinistcha is in the roster. Not listed on Serebii's "new abilities" page.

### Status / balance changes to existing abilities

Bulbapedia notes several across-the-board rebalances in Champions that affect abilities indirectly through status mechanics:
- Paralysis: activation chance dropped from 25% → **1/8 (12.5%)**.
- Sleep: duration capped at **2–3 turns** (down from 1–3).
- Freeze: thaw chance raised to **25%/turn**.

Sources:
- [Serebii — New Abilities](https://www.serebii.net/pokemonchampions/newabilities.shtml)
- [Game8 — New Abilities](https://game8.co/games/Pokemon-Champions/archives/589171)
- [Game8 — Abilities list](https://game8.co/games/Pokemon-Champions/archives/590403)
- [Bulbapedia — Piercing Drill](https://bulbapedia.bulbagarden.net/wiki/Piercing_Drill_(Ability))

---

## 7. Moves

### Total count

Our dictionary lists 473 moves. Published sources (Pokémon Zone, PokéBase, Serebii) do not publish a single consolidated count, but the Champions move pool is the **mainline move set minus moves tied to excluded Pokémon / legendaries** — roughly the same order of magnitude.

### No fully-new Champions-only moves documented

No source I found reports **Champions-original** moves. The "unusual" moves in our dictionary (Kowtow Cleave, Matcha Gotcha, etc.) are **existing signature moves** from Pokémon Scarlet/Violet + DLC that are in Champions because their owners (Kingambit, Sinistcha) are on the roster:

| Move | Type | Introduced | Signature of |
|---|---|---|---|
| Kowtow Cleave | Dark | SV base | Kingambit (85 BP, never misses) |
| Matcha Gotcha | Grass | SV Teal Mask DLC | Sinistcha (spread special, heals, 20% burn) |

### Move power rebalances

Bulbapedia notes that Champions **raises the base power of several moves** relative to mainline, e.g. Beak Blast 100 → 120. **[UNVERIFIED]** — no consolidated list of changed moves was found.

### PP values normalised

PP is bucketed to **8 / 12 / 16 / 20** (mapped from mainline 5 / 10 / 15 / 20+).

Sources:
- [Pokémon Zone — Moves](https://www.pokemon-zone.com/champions/moves/)
- [PokéBase — Moves](https://pokebase.app/pokemon-champions/moves)
- [Bulbapedia — Matcha Gotcha](https://bulbapedia.bulbagarden.net/wiki/Matcha_Gotcha_(move))
- [Game8 — Matcha Gotcha](https://game8.co/games/Pokemon-Champions/archives/593322)

---

## 8. UI and Game Flow

**Champions is menu-based, not world-based.** There is no overworld hub like LGPE or Scarlet/Violet — navigation is pure UI screens, much closer in spirit to Pokémon Showdown than to a mainline game.

### Confirmed screens / flow

The screens we already automate against (and which are confirmed by sources):

1. **Main Menu** — selects mode (Ranked Battles / Casual Battles / Private Battles / Online Tournament).
2. **Battle format selector** — Singles or Doubles (separate ladders).
3. **Team registration** — players build teams of 6.
4. **Team preview** — before each match both players see each other's team of 6. Player then picks 3 (Singles) or 4 (Doubles).
5. **In-battle UI** — action menu (Fight / Pokémon / Bag / Run where applicable), move select, HUD with HP bars, scrolling battle log, Mega Evolution toggle button.

### Team slot counts

- **Default: 3 team slots** per user (not 5 — this is different from what our tooling assumed).
- Paid membership ($4.99/mo or $49.99/yr) expands slots.
- Players use **Replica Teams / rental codes** to save up to ~10 additional lineups as a workaround.

**ACTION for automation:** if our code assumes "5 team slots", **re-check** against actual post-launch UI. Membership users and rental-code workflows may change the slot count visible on screen.

### Other screens to know about

- **Recruit menu** — transfers Pokémon from Pokémon Home (Pokémon "visit" Champions; do not permanently migrate; cannot return if originated in Champions).
- **Roster Ranch** — Champions' recruit/training hub. Uses Teammate Tickets, Training Tickets, Quick Coupons.
- **Frontier Shop** — VP spending on held items, clothing, etc.
- **Battle Data menu** — in-game usage stats / opponent teams viewer.
- **Music Selection** — players can choose battle BGM from Champions or older Pokémon titles.

### Battle mechanics UI-relevant

- All Pokémon are **level 50**.
- IVs are locked at 31.
- EVs replaced by **Stat Points** (extra point available beyond mainline EV cap).
- Nature alignments via **Mints** persist from Home.
- Dual-weak/resist shown explicitly as "Extremely/Mostly Effective / Ineffective" indicators.
- Stat boost/drop messages resolve simultaneously for both sides.

Sources:
- [Champions.pokemon.com — Gameplay](https://champions.pokemon.com/en-us/gameplay/)
- [Bulbapedia — Pokémon Champions](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_Champions)
- [Game8 — Beginner's guide](https://game8.co/games/Pokemon-Champions/archives/588876)
- [Games.GG — Team slots](https://games.gg/pokemon-champions/guides/pokemon-champions-how-to-get-more-free-team-slots/)

---

## 9. Release Status (as of April 2026)

- **Launched on Nintendo Switch: April 8, 2026 global** (April 7 in NA due to time zones).
- Mobile (iOS / Android) launch expected **later in 2026**; no specific date published.
- **Regulation M-A** is live through **June 17, 2026**. A new regulation is expected to follow, likely expanding the roster.
- Reception has been **mixed**: Metacritic 66/100 (23 reviews), 42% recommended on OpenCritic. Critics flagged bugs and balance issues at launch. A representative quote: "simultaneously the most accessible and flawed competitive Pokémon has ever been."
- The VGC circuit officially transitions to Champions at the **Malaysia MBL (May 9–10)** and **Indianapolis Regionals (May 29–31, 2026)**.

Sources:
- [Wikipedia — Pokémon Champions](https://en.wikipedia.org/wiki/Pok%C3%A9mon_Champions)
- [Bulbagarden — Release announcement](https://bulbagarden.net/threads/pokemon-champions-release-date-announced-alongside-details-on-game-features-vgc-transitions-to-pokemon-champions-from-indianapolis-regionals-in-may.310191/)

---

## 10. Community Tools & Data Sources

These are third-party tools we could potentially tap for roster / item / move data. None is an official public API — all would require scraping or community cooperation.

| Site | URL | What it offers | Notes for our project |
|---|---|---|---|
| **Pikalytics — Champions** | https://www.pikalytics.com/champions | Usage rankings, per-Pokémon pages, VGC team builder | Probably the best scraping target for usage stats |
| **ChampionsMeta** | https://championsmeta.io | Meta analysis, team builder, 4,415-team database (as of Apr–Jun 2026) | Data-rich; team builder at /builder |
| **Champions Lab** | https://championslab.xyz | 2,376 teams from ladder + 44 tournaments; team builder, battle sim, meta analysis | Includes battle simulator |
| **PikaChampions** | https://pikachampions.com | Full 263-Pokémon roster + Megas, Champions-specific learnsets, SP training calc, type coverage, match log, PokePaste I/O, Firebase team sync | **Strong candidate** for roster/learnset data mirror |
| **Pokémon Zone** | https://www.pokemon-zone.com/champions/ | Item/move/team core pages with tournament usage % | Clean per-item pages |
| **PokéBase** | https://pokebase.app/pokemon-champions | Team builder + usage stats per Pokémon | Includes moves/abilities/items breakdowns |
| **Game8** | https://game8.co/games/Pokemon-Champions/ | Damage calc, team builder, guides, exhaustive tier lists | Best for narrative guides |
| **Serebii** | https://www.serebii.net/pokemonchampions/ | Authoritative data dumps (Pokémon, items, abilities, moves, rules) | **Primary authoritative source** for factual data |
| **Bulbapedia** | https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_Champions | Wiki-style comprehensive article | Best for mechanics writeups |
| **Pokémon Showdown** | https://play.pokemonshowdown.com | Official "Champions OU / VGC / BSS" formats added post-launch | **Best** for automated battle-data ingest; likely has JSON `learnsets.ts` / `moves.ts` / `abilities.ts` for Champions |
| **Smogon — Champions BSS** | https://www.smogon.com/forums/ | Viability rankings, role compendium | Competitive analysis |

**Recommendation for our codebase:** Pokémon Showdown's open-source data files (github.com/smogon/pokemon-showdown — Champions formats added per their Twitter) are likely the cleanest machine-readable source of truth for species / moves / items / abilities at the data-file level. Worth checking as a drop-in replacement for any hand-curated dictionaries we maintain.

---

## Appendix A — Discrepancies to watch

| Claim in our codebase | What sources say | Action |
|---|---|---|
| "5 team slots per user" | Default is **3**. Membership / rental workaround unlocks more. | Re-check against current UI |
| "315 species in OCR dictionary" | Sources: 187 species / 246 species+Megas / 263 species+Megas alt / 382 species+all forms | Confirm which count we're matching against |
| "106 items" | Published pool ~110 | Confirm we aren't missing Mega Stones or new Tickets |
| "135 abilities" | Four new Champions abilities exist (Piercing Drill, Dragonize, Mega Sol, Spicy Spray); rest are mainline | Confirm all four are in our dictionary |
| "473 moves" | No new Champions-only moves documented. Some BP/PP rebalances. | Low risk — our list is likely the mainline set |
| "Hospitality is Champions-new" | **False** — Hospitality is from SV Teal Mask (2023), Sinistcha's ability | Correct any internal notes |

## Appendix B — Key mechanical changes vs mainline

- All Pokémon are **level 50**.
- All Pokémon have **31 IVs**.
- **Stat Points** replace EVs; a single extra point is available beyond mainline EV caps.
- **Paralysis**: 12.5% activation (down from 25%).
- **Sleep**: 2–3 turn duration.
- **Freeze**: 25% per-turn thaw rate.
- **PP bucketing**: 8 / 12 / 16 / 20.
- Type effectiveness prompts explicitly describe dual-resist / dual-weak cases.
- Stat changes resolve simultaneously on both Pokémon.

---

*Last updated: 2026-04-22. Contributors should update the "Release Status" and "Regulation" sections when new regulation sets drop.*
