# Battle Sim v2 — Format-Specific Improvements

## Problem
Search engine picks worse moves than raw model (-7.2% lift) because the sim
produces unrealistic board states. The winrate model evaluates garbage states
and misleads the search.

## Champions VGC Format Context
This is a Mega Evolution format with ~70 custom mega stones, Fairy Aura as the
#1 ability (5040 usage), and type-boosting items dominant over Choice/Life Orb.

## Priority 1: Damage Modifiers (biggest accuracy impact)

### 1a. Fairy Aura / Dark Aura (global auras)
- Fairy Aura: 1.33x to ALL Fairy-type moves on the field (both sides)
- Dark Aura: 1.33x to ALL Dark-type moves on the field
- Check if any Pokemon on either side has the ability, apply globally
- Fairy Aura alone affects ~30% of all games in this format

### 1b. Type-boosting items
The most common held items in this format. Each gives 1.2x to one type:
- Mystic Water (Water), Charcoal (Fire), Fairy Feather (Fairy)
- Black Glasses (Dark), Spell Tag (Ghost), Sharp Beak (Flying)
- Dragon Fang (Dragon), Magnet (Electric), Miracle Seed (Grass)
- Poison Barb (Poison), Silk Scarf (Normal), Hard Stone (Rock)
- Soft Sand (Ground), Never-Melt Ice (Ice), Twisted Spoon (Psychic)
- Metal Coat (Steel)
- Implementation: dict mapping item name → boosted type, multiply by 1.2

### 1c. Mega Evolution stat changes
When a Pokemon mega evolves, its base stats change. The sim currently uses
pre-mega stats. Need to look up mega base stats from the species features
(e.g., "Charizard-Mega-Y" has different stats than "Charizard").
- Already handled IF the species name includes "-Mega" — check that
  feature_tables has entries for mega forms

### 1d. Adaptability
STAB = 2.0x instead of 1.5x. Simple check on user's ability.

### 1e. Pixilate / Aerilate / Refrigerate / Galvanize
Normal-type moves become Fairy/Flying/Ice/Electric + 1.2x boost.
- Check user ability, if move is Normal type, change to the new type + 1.2x
- Pixilate is 114 usage (significant)

## Priority 2: Defensive Modifiers

### 2a. Resist berries (damage-halving)
Single-use berries that halve super-effective damage of a specific type:
- Chople (Fighting), Colbur (Dark), Occa (Fire), Shuca (Ground)
- Passho (Water), Roseli (Fairy), Yache (Ice), Charti (Rock)
- Kebia (Poison), Kasib (Ghost), Coba (Flying), Rindo (Grass)
- Babiri (Steel), Haban (Dragon), Wacan (Electric), Payapa (Psychic)
- Chilan (Normal — halves Normal damage)
- Implementation: dict mapping berry → type it resists. If target holds it
  and the move is that type AND super effective, multiply by 0.5.
  Note: we can't track consumption in 1-ply, so assume it's always active.

### 2b. Focus Sash
Survive any hit at 1 HP when at full HP. 2111 usage.
- If target.hp_frac == 1.0 and damage would KO, set hp_frac = 0.01 instead

### 2c. Sitrus Berry
Heal 25% when HP drops below 50%. 3178 usage (most common item).
- After damage, if hp_frac < 0.5 and was >= 0.5 before, add 0.25

## Priority 3: Key Abilities

### 3a. Intimidate (on switch-in)
-1 atk to all opponents when this Pokemon switches in. 2327 usage.
- In `_execute_switch`, if the new active has Intimidate, apply -1 atk boost
  to all opposing active Pokemon

### 3b. Levitate
Immune to Ground-type moves. 342 usage.
- In `_calc_damage`, if target has Levitate and move type is Ground, return 0

### 3c. Lightning Rod / Storm Drain / Water Absorb / Volt Absorb / Sap Sipper / Flash Fire / Motor Drive
Type immunities from abilities:
- Lightning Rod: immune to Electric (draws attacks in doubles)
- Storm Drain: immune to Water
- Water Absorb: immune to Water
- Volt Absorb: immune to Electric
- Sap Sipper: immune to Grass
- Flash Fire: immune to Fire
- Motor Drive: immune to Electric
- Implementation: dict mapping ability → immune type. Check in _calc_damage.

### 3d. Weather setters
Set weather on switch-in:
- Drizzle → Rain, Drought → Sun, Sand Stream → Sand, Snow Warning → Snow
- In `_execute_switch`, if new active has these, set field weather

### 3e. Speed Boost
+1 spe at end of turn. 517 usage.
- Apply after all actions resolve (end-of-turn phase)

### 3f. Mold Breaker
Ignores target's defensive abilities. 1186 usage.
- When user has Mold Breaker, skip Levitate/type-immunity checks on target

## Priority 4: Choice Scarf
1.5x speed but locked to first move used. 510 usage.
- In `_effective_speed`, if Pokemon holds Choice Scarf, multiply by 1.5

## Priority 5: Stat-changing moves
Currently all status moves are no-ops. Add the common ones:
- Swords Dance: +2 atk
- Nasty Plot: +2 spa  
- Tailwind: set tailwind for 4 turns
- Trick Room: toggle trick room
- Protect: already handled
- Fake Out: priority +3, flinch (skip target's action this turn)

## Implementation Order
1. Type-boosting items (simple dict lookup, huge coverage)
2. Fairy Aura / Dark Aura (affects ~30% of games)
3. Ability-based immunities (Levitate, Lightning Rod, etc.)
4. Resist berries (common defensive items)
5. Focus Sash + Sitrus Berry
6. Intimidate on switch
7. Adaptability + Pixilate
8. Choice Scarf speed
9. Weather setters on switch
10. Stat-changing moves (Swords Dance, Tailwind, Trick Room)
11. Speed Boost end-of-turn
12. Mold Breaker
