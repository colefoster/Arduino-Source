//  AUTO-GENERATED. Do not edit.
//  Regen: python3 tools/generate_ability_item_table.py

#include "PokemonChampions_AbilityItemTable.h"

#include <unordered_map>
#include <vector>
#include <string>
#include <algorithm>

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{

namespace{
//  slug -> kind ('ability' or 'item').
//  Generated from data/ps_data/abilities.json + items.json.
const std::unordered_map<std::string, AbilityItemKind>& table(){
    static const std::unordered_map<std::string, AbilityItemKind> t = {
        {"ability-shield", AbilityItemKind::ITEM}, // Ability Shield
        {"absorb-bulb", AbilityItemKind::ITEM}, // Absorb Bulb
        {"adamant-crystal", AbilityItemKind::ITEM}, // Adamant Crystal
        {"adamant-orb", AbilityItemKind::ITEM}, // Adamant Orb
        {"adaptability", AbilityItemKind::ABILITY}, // Adaptability
        {"adrenaline-orb", AbilityItemKind::ITEM}, // Adrenaline Orb
        {"aerilate", AbilityItemKind::ABILITY}, // Aerilate
        {"aftermath", AbilityItemKind::ABILITY}, // Aftermath
        {"aguav-berry", AbilityItemKind::ITEM}, // Aguav Berry
        {"air-balloon", AbilityItemKind::ITEM}, // Air Balloon
        {"air-lock", AbilityItemKind::ABILITY}, // Air Lock
        {"analytic", AbilityItemKind::ABILITY}, // Analytic
        {"anger-point", AbilityItemKind::ABILITY}, // Anger Point
        {"anger-shell", AbilityItemKind::ABILITY}, // Anger Shell
        {"anticipation", AbilityItemKind::ABILITY}, // Anticipation
        {"apicot-berry", AbilityItemKind::ITEM}, // Apicot Berry
        {"arena-trap", AbilityItemKind::ABILITY}, // Arena Trap
        {"armor-tail", AbilityItemKind::ABILITY}, // Armor Tail
        {"aroma-veil", AbilityItemKind::ABILITY}, // Aroma Veil
        {"as-one-glastrier", AbilityItemKind::ABILITY}, // As One (Glastrier)
        {"as-one-spectrier", AbilityItemKind::ABILITY}, // As One (Spectrier)
        {"aspear-berry", AbilityItemKind::ITEM}, // Aspear Berry
        {"assault-vest", AbilityItemKind::ITEM}, // Assault Vest
        {"aura-break", AbilityItemKind::ABILITY}, // Aura Break
        {"auspicious-armor", AbilityItemKind::ITEM}, // Auspicious Armor
        {"babiri-berry", AbilityItemKind::ITEM}, // Babiri Berry
        {"bad-dreams", AbilityItemKind::ABILITY}, // Bad Dreams
        {"ball-fetch", AbilityItemKind::ABILITY}, // Ball Fetch
        {"battery", AbilityItemKind::ABILITY}, // Battery
        {"battle-armor", AbilityItemKind::ABILITY}, // Battle Armor
        {"battle-bond", AbilityItemKind::ABILITY}, // Battle Bond
        {"beads-of-ruin", AbilityItemKind::ABILITY}, // Beads of Ruin
        {"beast-ball", AbilityItemKind::ITEM}, // Beast Ball
        {"beast-boost", AbilityItemKind::ABILITY}, // Beast Boost
        {"berry-sweet", AbilityItemKind::ITEM}, // Berry Sweet
        {"berserk", AbilityItemKind::ABILITY}, // Berserk
        {"big-nugget", AbilityItemKind::ITEM}, // Big Nugget
        {"big-pecks", AbilityItemKind::ABILITY}, // Big Pecks
        {"big-root", AbilityItemKind::ITEM}, // Big Root
        {"binding-band", AbilityItemKind::ITEM}, // Binding Band
        {"black-belt", AbilityItemKind::ITEM}, // Black Belt
        {"black-glasses", AbilityItemKind::ITEM}, // Black Glasses
        {"black-sludge", AbilityItemKind::ITEM}, // Black Sludge
        {"blaze", AbilityItemKind::ABILITY}, // Blaze
        {"blunder-policy", AbilityItemKind::ITEM}, // Blunder Policy
        {"booster-energy", AbilityItemKind::ITEM}, // Booster Energy
        {"bottle-cap", AbilityItemKind::ITEM}, // Bottle Cap
        {"bright-powder", AbilityItemKind::ITEM}, // Bright Powder
        {"bulletproof", AbilityItemKind::ABILITY}, // Bulletproof
        {"cell-battery", AbilityItemKind::ITEM}, // Cell Battery
        {"charcoal", AbilityItemKind::ITEM}, // Charcoal
        {"charti-berry", AbilityItemKind::ITEM}, // Charti Berry
        {"cheek-pouch", AbilityItemKind::ABILITY}, // Cheek Pouch
        {"cheri-berry", AbilityItemKind::ITEM}, // Cheri Berry
        {"chesto-berry", AbilityItemKind::ITEM}, // Chesto Berry
        {"chilan-berry", AbilityItemKind::ITEM}, // Chilan Berry
        {"chilling-neigh", AbilityItemKind::ABILITY}, // Chilling Neigh
        {"chipped-pot", AbilityItemKind::ITEM}, // Chipped Pot
        {"chlorophyll", AbilityItemKind::ABILITY}, // Chlorophyll
        {"choice-band", AbilityItemKind::ITEM}, // Choice Band
        {"choice-scarf", AbilityItemKind::ITEM}, // Choice Scarf
        {"choice-specs", AbilityItemKind::ITEM}, // Choice Specs
        {"chople-berry", AbilityItemKind::ITEM}, // Chople Berry
        {"clear-amulet", AbilityItemKind::ITEM}, // Clear Amulet
        {"clear-body", AbilityItemKind::ABILITY}, // Clear Body
        {"cloud-nine", AbilityItemKind::ABILITY}, // Cloud Nine
        {"clover-sweet", AbilityItemKind::ITEM}, // Clover Sweet
        {"coba-berry", AbilityItemKind::ITEM}, // Coba Berry
        {"colbur-berry", AbilityItemKind::ITEM}, // Colbur Berry
        {"color-change", AbilityItemKind::ABILITY}, // Color Change
        {"comatose", AbilityItemKind::ABILITY}, // Comatose
        {"commander", AbilityItemKind::ABILITY}, // Commander
        {"competitive", AbilityItemKind::ABILITY}, // Competitive
        {"compound-eyes", AbilityItemKind::ABILITY}, // Compound Eyes
        {"contrary", AbilityItemKind::ABILITY}, // Contrary
        {"cornerstone-mask", AbilityItemKind::ITEM}, // Cornerstone Mask
        {"corrosion", AbilityItemKind::ABILITY}, // Corrosion
        {"costar", AbilityItemKind::ABILITY}, // Costar
        {"cotton-down", AbilityItemKind::ABILITY}, // Cotton Down
        {"covert-cloak", AbilityItemKind::ITEM}, // Covert Cloak
        {"cracked-pot", AbilityItemKind::ITEM}, // Cracked Pot
        {"cud-chew", AbilityItemKind::ABILITY}, // Cud Chew
        {"curious-medicine", AbilityItemKind::ABILITY}, // Curious Medicine
        {"cursed-body", AbilityItemKind::ABILITY}, // Cursed Body
        {"custap-berry", AbilityItemKind::ITEM}, // Custap Berry
        {"cute-charm", AbilityItemKind::ABILITY}, // Cute Charm
        {"damp", AbilityItemKind::ABILITY}, // Damp
        {"damp-rock", AbilityItemKind::ITEM}, // Damp Rock
        {"dancer", AbilityItemKind::ABILITY}, // Dancer
        {"dark-aura", AbilityItemKind::ABILITY}, // Dark Aura
        {"dauntless-shield", AbilityItemKind::ABILITY}, // Dauntless Shield
        {"dawn-stone", AbilityItemKind::ITEM}, // Dawn Stone
        {"dazzling", AbilityItemKind::ABILITY}, // Dazzling
        {"defeatist", AbilityItemKind::ABILITY}, // Defeatist
        {"defiant", AbilityItemKind::ABILITY}, // Defiant
        {"delta-stream", AbilityItemKind::ABILITY}, // Delta Stream
        {"desolate-land", AbilityItemKind::ABILITY}, // Desolate Land
        {"destiny-knot", AbilityItemKind::ITEM}, // Destiny Knot
        {"disguise", AbilityItemKind::ABILITY}, // Disguise
        {"dive-ball", AbilityItemKind::ITEM}, // Dive Ball
        {"download", AbilityItemKind::ABILITY}, // Download
        {"draco-plate", AbilityItemKind::ITEM}, // Draco Plate
        {"dragon-fang", AbilityItemKind::ITEM}, // Dragon Fang
        {"dragon-s-maw", AbilityItemKind::ABILITY}, // Dragon's Maw
        {"dragon-scale", AbilityItemKind::ITEM}, // Dragon Scale
        {"dragonize", AbilityItemKind::ABILITY}, // Dragonize
        {"dread-plate", AbilityItemKind::ITEM}, // Dread Plate
        {"dream-ball", AbilityItemKind::ITEM}, // Dream Ball
        {"drizzle", AbilityItemKind::ABILITY}, // Drizzle
        {"drought", AbilityItemKind::ABILITY}, // Drought
        {"dry-skin", AbilityItemKind::ABILITY}, // Dry Skin
        {"dubious-disc", AbilityItemKind::ITEM}, // Dubious Disc
        {"dusk-ball", AbilityItemKind::ITEM}, // Dusk Ball
        {"dusk-stone", AbilityItemKind::ITEM}, // Dusk Stone
        {"early-bird", AbilityItemKind::ABILITY}, // Early Bird
        {"earth-eater", AbilityItemKind::ABILITY}, // Earth Eater
        {"earth-plate", AbilityItemKind::ITEM}, // Earth Plate
        {"effect-spore", AbilityItemKind::ABILITY}, // Effect Spore
        {"eject-button", AbilityItemKind::ITEM}, // Eject Button
        {"eject-pack", AbilityItemKind::ITEM}, // Eject Pack
        {"electirizer", AbilityItemKind::ITEM}, // Electirizer
        {"electric-seed", AbilityItemKind::ITEM}, // Electric Seed
        {"electric-surge", AbilityItemKind::ABILITY}, // Electric Surge
        {"electromorphosis", AbilityItemKind::ABILITY}, // Electromorphosis
        {"embody-aspect-cornerstone", AbilityItemKind::ABILITY}, // Embody Aspect (Cornerstone)
        {"embody-aspect-hearthflame", AbilityItemKind::ABILITY}, // Embody Aspect (Hearthflame)
        {"embody-aspect-teal", AbilityItemKind::ABILITY}, // Embody Aspect (Teal)
        {"embody-aspect-wellspring", AbilityItemKind::ABILITY}, // Embody Aspect (Wellspring)
        {"emergency-exit", AbilityItemKind::ABILITY}, // Emergency Exit
        {"enigma-berry", AbilityItemKind::ITEM}, // Enigma Berry
        {"eviolite", AbilityItemKind::ITEM}, // Eviolite
        {"expert-belt", AbilityItemKind::ITEM}, // Expert Belt
        {"fairy-aura", AbilityItemKind::ABILITY}, // Fairy Aura
        {"fairy-feather", AbilityItemKind::ITEM}, // Fairy Feather
        {"fast-ball", AbilityItemKind::ITEM}, // Fast Ball
        {"figy-berry", AbilityItemKind::ITEM}, // Figy Berry
        {"filter", AbilityItemKind::ABILITY}, // Filter
        {"fire-stone", AbilityItemKind::ITEM}, // Fire Stone
        {"fist-plate", AbilityItemKind::ITEM}, // Fist Plate
        {"flame-body", AbilityItemKind::ABILITY}, // Flame Body
        {"flame-orb", AbilityItemKind::ITEM}, // Flame Orb
        {"flame-plate", AbilityItemKind::ITEM}, // Flame Plate
        {"flare-boost", AbilityItemKind::ABILITY}, // Flare Boost
        {"flash-fire", AbilityItemKind::ABILITY}, // Flash Fire
        {"float-stone", AbilityItemKind::ITEM}, // Float Stone
        {"flower-gift", AbilityItemKind::ABILITY}, // Flower Gift
        {"flower-sweet", AbilityItemKind::ITEM}, // Flower Sweet
        {"flower-veil", AbilityItemKind::ABILITY}, // Flower Veil
        {"fluffy", AbilityItemKind::ABILITY}, // Fluffy
        {"focus-band", AbilityItemKind::ITEM}, // Focus Band
        {"focus-sash", AbilityItemKind::ITEM}, // Focus Sash
        {"forecast", AbilityItemKind::ABILITY}, // Forecast
        {"forewarn", AbilityItemKind::ABILITY}, // Forewarn
        {"friend-ball", AbilityItemKind::ITEM}, // Friend Ball
        {"friend-guard", AbilityItemKind::ABILITY}, // Friend Guard
        {"frisk", AbilityItemKind::ABILITY}, // Frisk
        {"full-metal-body", AbilityItemKind::ABILITY}, // Full Metal Body
        {"fur-coat", AbilityItemKind::ABILITY}, // Fur Coat
        {"galarica-cuff", AbilityItemKind::ITEM}, // Galarica Cuff
        {"galarica-wreath", AbilityItemKind::ITEM}, // Galarica Wreath
        {"gale-wings", AbilityItemKind::ABILITY}, // Gale Wings
        {"galvanize", AbilityItemKind::ABILITY}, // Galvanize
        {"ganlon-berry", AbilityItemKind::ITEM}, // Ganlon Berry
        {"gluttony", AbilityItemKind::ABILITY}, // Gluttony
        {"gold-bottle-cap", AbilityItemKind::ITEM}, // Gold Bottle Cap
        {"good-as-gold", AbilityItemKind::ABILITY}, // Good as Gold
        {"gooey", AbilityItemKind::ABILITY}, // Gooey
        {"gorilla-tactics", AbilityItemKind::ABILITY}, // Gorilla Tactics
        {"grass-pelt", AbilityItemKind::ABILITY}, // Grass Pelt
        {"grassy-seed", AbilityItemKind::ITEM}, // Grassy Seed
        {"grassy-surge", AbilityItemKind::ABILITY}, // Grassy Surge
        {"great-ball", AbilityItemKind::ITEM}, // Great Ball
        {"grepa-berry", AbilityItemKind::ITEM}, // Grepa Berry
        {"grim-neigh", AbilityItemKind::ABILITY}, // Grim Neigh
        {"grip-claw", AbilityItemKind::ITEM}, // Grip Claw
        {"griseous-core", AbilityItemKind::ITEM}, // Griseous Core
        {"griseous-orb", AbilityItemKind::ITEM}, // Griseous Orb
        {"guard-dog", AbilityItemKind::ABILITY}, // Guard Dog
        {"gulp-missile", AbilityItemKind::ABILITY}, // Gulp Missile
        {"guts", AbilityItemKind::ABILITY}, // Guts
        {"haban-berry", AbilityItemKind::ITEM}, // Haban Berry
        {"hadron-engine", AbilityItemKind::ABILITY}, // Hadron Engine
        {"hard-stone", AbilityItemKind::ITEM}, // Hard Stone
        {"harvest", AbilityItemKind::ABILITY}, // Harvest
        {"heal-ball", AbilityItemKind::ITEM}, // Heal Ball
        {"healer", AbilityItemKind::ABILITY}, // Healer
        {"hearthflame-mask", AbilityItemKind::ITEM}, // Hearthflame Mask
        {"heat-rock", AbilityItemKind::ITEM}, // Heat Rock
        {"heatproof", AbilityItemKind::ABILITY}, // Heatproof
        {"heavy-ball", AbilityItemKind::ITEM}, // Heavy Ball
        {"heavy-duty-boots", AbilityItemKind::ITEM}, // Heavy-Duty Boots
        {"heavy-metal", AbilityItemKind::ABILITY}, // Heavy Metal
        {"hondew-berry", AbilityItemKind::ITEM}, // Hondew Berry
        {"honey-gather", AbilityItemKind::ABILITY}, // Honey Gather
        {"hospitality", AbilityItemKind::ABILITY}, // Hospitality
        {"huge-power", AbilityItemKind::ABILITY}, // Huge Power
        {"hunger-switch", AbilityItemKind::ABILITY}, // Hunger Switch
        {"hustle", AbilityItemKind::ABILITY}, // Hustle
        {"hydration", AbilityItemKind::ABILITY}, // Hydration
        {"hyper-cutter", AbilityItemKind::ABILITY}, // Hyper Cutter
        {"iapapa-berry", AbilityItemKind::ITEM}, // Iapapa Berry
        {"ice-body", AbilityItemKind::ABILITY}, // Ice Body
        {"ice-face", AbilityItemKind::ABILITY}, // Ice Face
        {"ice-scales", AbilityItemKind::ABILITY}, // Ice Scales
        {"ice-stone", AbilityItemKind::ITEM}, // Ice Stone
        {"icicle-plate", AbilityItemKind::ITEM}, // Icicle Plate
        {"icy-rock", AbilityItemKind::ITEM}, // Icy Rock
        {"illuminate", AbilityItemKind::ABILITY}, // Illuminate
        {"illusion", AbilityItemKind::ABILITY}, // Illusion
        {"immunity", AbilityItemKind::ABILITY}, // Immunity
        {"imposter", AbilityItemKind::ABILITY}, // Imposter
        {"infiltrator", AbilityItemKind::ABILITY}, // Infiltrator
        {"innards-out", AbilityItemKind::ABILITY}, // Innards Out
        {"inner-focus", AbilityItemKind::ABILITY}, // Inner Focus
        {"insect-plate", AbilityItemKind::ITEM}, // Insect Plate
        {"insomnia", AbilityItemKind::ABILITY}, // Insomnia
        {"intimidate", AbilityItemKind::ABILITY}, // Intimidate
        {"intrepid-sword", AbilityItemKind::ABILITY}, // Intrepid Sword
        {"iron-ball", AbilityItemKind::ITEM}, // Iron Ball
        {"iron-barbs", AbilityItemKind::ABILITY}, // Iron Barbs
        {"iron-fist", AbilityItemKind::ABILITY}, // Iron Fist
        {"iron-plate", AbilityItemKind::ITEM}, // Iron Plate
        {"jaboca-berry", AbilityItemKind::ITEM}, // Jaboca Berry
        {"justified", AbilityItemKind::ABILITY}, // Justified
        {"kasib-berry", AbilityItemKind::ITEM}, // Kasib Berry
        {"kebia-berry", AbilityItemKind::ITEM}, // Kebia Berry
        {"kee-berry", AbilityItemKind::ITEM}, // Kee Berry
        {"keen-eye", AbilityItemKind::ABILITY}, // Keen Eye
        {"kelpsy-berry", AbilityItemKind::ITEM}, // Kelpsy Berry
        {"king-s-rock", AbilityItemKind::ITEM}, // King's Rock
        {"klutz", AbilityItemKind::ABILITY}, // Klutz
        {"lagging-tail", AbilityItemKind::ITEM}, // Lagging Tail
        {"lansat-berry", AbilityItemKind::ITEM}, // Lansat Berry
        {"leaf-guard", AbilityItemKind::ABILITY}, // Leaf Guard
        {"leaf-stone", AbilityItemKind::ITEM}, // Leaf Stone
        {"leftovers", AbilityItemKind::ITEM}, // Leftovers
        {"leppa-berry", AbilityItemKind::ITEM}, // Leppa Berry
        {"level-ball", AbilityItemKind::ITEM}, // Level Ball
        {"levitate", AbilityItemKind::ABILITY}, // Levitate
        {"libero", AbilityItemKind::ABILITY}, // Libero
        {"liechi-berry", AbilityItemKind::ITEM}, // Liechi Berry
        {"life-orb", AbilityItemKind::ITEM}, // Life Orb
        {"light-ball", AbilityItemKind::ITEM}, // Light Ball
        {"light-clay", AbilityItemKind::ITEM}, // Light Clay
        {"light-metal", AbilityItemKind::ABILITY}, // Light Metal
        {"lightning-rod", AbilityItemKind::ABILITY}, // Lightning Rod
        {"limber", AbilityItemKind::ABILITY}, // Limber
        {"lingering-aroma", AbilityItemKind::ABILITY}, // Lingering Aroma
        {"liquid-ooze", AbilityItemKind::ABILITY}, // Liquid Ooze
        {"liquid-voice", AbilityItemKind::ABILITY}, // Liquid Voice
        {"loaded-dice", AbilityItemKind::ITEM}, // Loaded Dice
        {"long-reach", AbilityItemKind::ABILITY}, // Long Reach
        {"love-ball", AbilityItemKind::ITEM}, // Love Ball
        {"love-sweet", AbilityItemKind::ITEM}, // Love Sweet
        {"lum-berry", AbilityItemKind::ITEM}, // Lum Berry
        {"luminous-moss", AbilityItemKind::ITEM}, // Luminous Moss
        {"lure-ball", AbilityItemKind::ITEM}, // Lure Ball
        {"lustrous-globe", AbilityItemKind::ITEM}, // Lustrous Globe
        {"lustrous-orb", AbilityItemKind::ITEM}, // Lustrous Orb
        {"luxury-ball", AbilityItemKind::ITEM}, // Luxury Ball
        {"magic-bounce", AbilityItemKind::ABILITY}, // Magic Bounce
        {"magic-guard", AbilityItemKind::ABILITY}, // Magic Guard
        {"magician", AbilityItemKind::ABILITY}, // Magician
        {"magma-armor", AbilityItemKind::ABILITY}, // Magma Armor
        {"magmarizer", AbilityItemKind::ITEM}, // Magmarizer
        {"magnet", AbilityItemKind::ITEM}, // Magnet
        {"magnet-pull", AbilityItemKind::ABILITY}, // Magnet Pull
        {"mago-berry", AbilityItemKind::ITEM}, // Mago Berry
        {"malicious-armor", AbilityItemKind::ITEM}, // Malicious Armor
        {"maranga-berry", AbilityItemKind::ITEM}, // Maranga Berry
        {"marvel-scale", AbilityItemKind::ABILITY}, // Marvel Scale
        {"master-ball", AbilityItemKind::ITEM}, // Master Ball
        {"masterpiece-teacup", AbilityItemKind::ITEM}, // Masterpiece Teacup
        {"meadow-plate", AbilityItemKind::ITEM}, // Meadow Plate
        {"mega-launcher", AbilityItemKind::ABILITY}, // Mega Launcher
        {"mega-sol", AbilityItemKind::ABILITY}, // Mega Sol
        {"mental-herb", AbilityItemKind::ITEM}, // Mental Herb
        {"merciless", AbilityItemKind::ABILITY}, // Merciless
        {"metal-alloy", AbilityItemKind::ITEM}, // Metal Alloy
        {"metal-coat", AbilityItemKind::ITEM}, // Metal Coat
        {"metronome", AbilityItemKind::ITEM}, // Metronome
        {"micle-berry", AbilityItemKind::ITEM}, // Micle Berry
        {"mimicry", AbilityItemKind::ABILITY}, // Mimicry
        {"mind-plate", AbilityItemKind::ITEM}, // Mind Plate
        {"mind-s-eye", AbilityItemKind::ABILITY}, // Mind's Eye
        {"minus", AbilityItemKind::ABILITY}, // Minus
        {"miracle-seed", AbilityItemKind::ITEM}, // Miracle Seed
        {"mirror-armor", AbilityItemKind::ABILITY}, // Mirror Armor
        {"mirror-herb", AbilityItemKind::ITEM}, // Mirror Herb
        {"misty-seed", AbilityItemKind::ITEM}, // Misty Seed
        {"misty-surge", AbilityItemKind::ABILITY}, // Misty Surge
        {"mold-breaker", AbilityItemKind::ABILITY}, // Mold Breaker
        {"moody", AbilityItemKind::ABILITY}, // Moody
        {"moon-ball", AbilityItemKind::ITEM}, // Moon Ball
        {"moon-stone", AbilityItemKind::ITEM}, // Moon Stone
        {"motor-drive", AbilityItemKind::ABILITY}, // Motor Drive
        {"moxie", AbilityItemKind::ABILITY}, // Moxie
        {"multiscale", AbilityItemKind::ABILITY}, // Multiscale
        {"multitype", AbilityItemKind::ABILITY}, // Multitype
        {"mummy", AbilityItemKind::ABILITY}, // Mummy
        {"muscle-band", AbilityItemKind::ITEM}, // Muscle Band
        {"mycelium-might", AbilityItemKind::ABILITY}, // Mycelium Might
        {"mystic-water", AbilityItemKind::ITEM}, // Mystic Water
        {"natural-cure", AbilityItemKind::ABILITY}, // Natural Cure
        {"nest-ball", AbilityItemKind::ITEM}, // Nest Ball
        {"net-ball", AbilityItemKind::ITEM}, // Net Ball
        {"neuroforce", AbilityItemKind::ABILITY}, // Neuroforce
        {"neutralizing-gas", AbilityItemKind::ABILITY}, // Neutralizing Gas
        {"never-melt-ice", AbilityItemKind::ITEM}, // Never-Melt Ice
        {"no-guard", AbilityItemKind::ABILITY}, // No Guard
        {"normal-gem", AbilityItemKind::ITEM}, // Normal Gem
        {"normalize", AbilityItemKind::ABILITY}, // Normalize
        {"oblivious", AbilityItemKind::ABILITY}, // Oblivious
        {"occa-berry", AbilityItemKind::ITEM}, // Occa Berry
        {"opportunist", AbilityItemKind::ABILITY}, // Opportunist
        {"oran-berry", AbilityItemKind::ITEM}, // Oran Berry
        {"orichalcum-pulse", AbilityItemKind::ABILITY}, // Orichalcum Pulse
        {"oval-stone", AbilityItemKind::ITEM}, // Oval Stone
        {"overcoat", AbilityItemKind::ABILITY}, // Overcoat
        {"overgrow", AbilityItemKind::ABILITY}, // Overgrow
        {"own-tempo", AbilityItemKind::ABILITY}, // Own Tempo
        {"parental-bond", AbilityItemKind::ABILITY}, // Parental Bond
        {"passho-berry", AbilityItemKind::ITEM}, // Passho Berry
        {"pastel-veil", AbilityItemKind::ABILITY}, // Pastel Veil
        {"payapa-berry", AbilityItemKind::ITEM}, // Payapa Berry
        {"pecha-berry", AbilityItemKind::ITEM}, // Pecha Berry
        {"perish-body", AbilityItemKind::ABILITY}, // Perish Body
        {"persim-berry", AbilityItemKind::ITEM}, // Persim Berry
        {"petaya-berry", AbilityItemKind::ITEM}, // Petaya Berry
        {"pickpocket", AbilityItemKind::ABILITY}, // Pickpocket
        {"pickup", AbilityItemKind::ABILITY}, // Pickup
        {"piercing-drill", AbilityItemKind::ABILITY}, // Piercing Drill
        {"pixie-plate", AbilityItemKind::ITEM}, // Pixie Plate
        {"pixilate", AbilityItemKind::ABILITY}, // Pixilate
        {"plus", AbilityItemKind::ABILITY}, // Plus
        {"poison-barb", AbilityItemKind::ITEM}, // Poison Barb
        {"poison-heal", AbilityItemKind::ABILITY}, // Poison Heal
        {"poison-point", AbilityItemKind::ABILITY}, // Poison Point
        {"poison-puppeteer", AbilityItemKind::ABILITY}, // Poison Puppeteer
        {"poison-touch", AbilityItemKind::ABILITY}, // Poison Touch
        {"poke-ball", AbilityItemKind::ITEM}, // Poke Ball
        {"pomeg-berry", AbilityItemKind::ITEM}, // Pomeg Berry
        {"power-anklet", AbilityItemKind::ITEM}, // Power Anklet
        {"power-band", AbilityItemKind::ITEM}, // Power Band
        {"power-belt", AbilityItemKind::ITEM}, // Power Belt
        {"power-bracer", AbilityItemKind::ITEM}, // Power Bracer
        {"power-construct", AbilityItemKind::ABILITY}, // Power Construct
        {"power-herb", AbilityItemKind::ITEM}, // Power Herb
        {"power-lens", AbilityItemKind::ITEM}, // Power Lens
        {"power-of-alchemy", AbilityItemKind::ABILITY}, // Power of Alchemy
        {"power-spot", AbilityItemKind::ABILITY}, // Power Spot
        {"power-weight", AbilityItemKind::ITEM}, // Power Weight
        {"prankster", AbilityItemKind::ABILITY}, // Prankster
        {"premier-ball", AbilityItemKind::ITEM}, // Premier Ball
        {"pressure", AbilityItemKind::ABILITY}, // Pressure
        {"pretty-feather", AbilityItemKind::ITEM}, // Pretty Feather
        {"primordial-sea", AbilityItemKind::ABILITY}, // Primordial Sea
        {"prism-armor", AbilityItemKind::ABILITY}, // Prism Armor
        {"prism-scale", AbilityItemKind::ITEM}, // Prism Scale
        {"propeller-tail", AbilityItemKind::ABILITY}, // Propeller Tail
        {"protean", AbilityItemKind::ABILITY}, // Protean
        {"protective-pads", AbilityItemKind::ITEM}, // Protective Pads
        {"protector", AbilityItemKind::ITEM}, // Protector
        {"protosynthesis", AbilityItemKind::ABILITY}, // Protosynthesis
        {"psychic-seed", AbilityItemKind::ITEM}, // Psychic Seed
        {"psychic-surge", AbilityItemKind::ABILITY}, // Psychic Surge
        {"punching-glove", AbilityItemKind::ITEM}, // Punching Glove
        {"punk-rock", AbilityItemKind::ABILITY}, // Punk Rock
        {"pure-power", AbilityItemKind::ABILITY}, // Pure Power
        {"purifying-salt", AbilityItemKind::ABILITY}, // Purifying Salt
        {"qualot-berry", AbilityItemKind::ITEM}, // Qualot Berry
        {"quark-drive", AbilityItemKind::ABILITY}, // Quark Drive
        {"queenly-majesty", AbilityItemKind::ABILITY}, // Queenly Majesty
        {"quick-ball", AbilityItemKind::ITEM}, // Quick Ball
        {"quick-claw", AbilityItemKind::ITEM}, // Quick Claw
        {"quick-draw", AbilityItemKind::ABILITY}, // Quick Draw
        {"quick-feet", AbilityItemKind::ABILITY}, // Quick Feet
        {"rain-dish", AbilityItemKind::ABILITY}, // Rain Dish
        {"rare-bone", AbilityItemKind::ITEM}, // Rare Bone
        {"rattled", AbilityItemKind::ABILITY}, // Rattled
        {"rawst-berry", AbilityItemKind::ITEM}, // Rawst Berry
        {"razor-claw", AbilityItemKind::ITEM}, // Razor Claw
        {"razor-fang", AbilityItemKind::ITEM}, // Razor Fang
        {"reaper-cloth", AbilityItemKind::ITEM}, // Reaper Cloth
        {"receiver", AbilityItemKind::ABILITY}, // Receiver
        {"reckless", AbilityItemKind::ABILITY}, // Reckless
        {"red-card", AbilityItemKind::ITEM}, // Red Card
        {"refrigerate", AbilityItemKind::ABILITY}, // Refrigerate
        {"regenerator", AbilityItemKind::ABILITY}, // Regenerator
        {"repeat-ball", AbilityItemKind::ITEM}, // Repeat Ball
        {"ribbon-sweet", AbilityItemKind::ITEM}, // Ribbon Sweet
        {"rindo-berry", AbilityItemKind::ITEM}, // Rindo Berry
        {"ring-target", AbilityItemKind::ITEM}, // Ring Target
        {"ripen", AbilityItemKind::ABILITY}, // Ripen
        {"rivalry", AbilityItemKind::ABILITY}, // Rivalry
        {"rks-system", AbilityItemKind::ABILITY}, // RKS System
        {"rock-head", AbilityItemKind::ABILITY}, // Rock Head
        {"rocky-helmet", AbilityItemKind::ITEM}, // Rocky Helmet
        {"rocky-payload", AbilityItemKind::ABILITY}, // Rocky Payload
        {"room-service", AbilityItemKind::ITEM}, // Room Service
        {"roseli-berry", AbilityItemKind::ITEM}, // Roseli Berry
        {"rough-skin", AbilityItemKind::ABILITY}, // Rough Skin
        {"rowap-berry", AbilityItemKind::ITEM}, // Rowap Berry
        {"run-away", AbilityItemKind::ABILITY}, // Run Away
        {"rusted-shield", AbilityItemKind::ITEM}, // Rusted Shield
        {"rusted-sword", AbilityItemKind::ITEM}, // Rusted Sword
        {"safari-ball", AbilityItemKind::ITEM}, // Safari Ball
        {"safety-goggles", AbilityItemKind::ITEM}, // Safety Goggles
        {"salac-berry", AbilityItemKind::ITEM}, // Salac Berry
        {"sand-force", AbilityItemKind::ABILITY}, // Sand Force
        {"sand-rush", AbilityItemKind::ABILITY}, // Sand Rush
        {"sand-spit", AbilityItemKind::ABILITY}, // Sand Spit
        {"sand-stream", AbilityItemKind::ABILITY}, // Sand Stream
        {"sand-veil", AbilityItemKind::ABILITY}, // Sand Veil
        {"sap-sipper", AbilityItemKind::ABILITY}, // Sap Sipper
        {"schooling", AbilityItemKind::ABILITY}, // Schooling
        {"scope-lens", AbilityItemKind::ITEM}, // Scope Lens
        {"scrappy", AbilityItemKind::ABILITY}, // Scrappy
        {"screen-cleaner", AbilityItemKind::ABILITY}, // Screen Cleaner
        {"seed-sower", AbilityItemKind::ABILITY}, // Seed Sower
        {"serene-grace", AbilityItemKind::ABILITY}, // Serene Grace
        {"shadow-shield", AbilityItemKind::ABILITY}, // Shadow Shield
        {"shadow-tag", AbilityItemKind::ABILITY}, // Shadow Tag
        {"sharp-beak", AbilityItemKind::ITEM}, // Sharp Beak
        {"sharpness", AbilityItemKind::ABILITY}, // Sharpness
        {"shed-shell", AbilityItemKind::ITEM}, // Shed Shell
        {"shed-skin", AbilityItemKind::ABILITY}, // Shed Skin
        {"sheer-force", AbilityItemKind::ABILITY}, // Sheer Force
        {"shell-armor", AbilityItemKind::ABILITY}, // Shell Armor
        {"shell-bell", AbilityItemKind::ITEM}, // Shell Bell
        {"shield-dust", AbilityItemKind::ABILITY}, // Shield Dust
        {"shields-down", AbilityItemKind::ABILITY}, // Shields Down
        {"shiny-stone", AbilityItemKind::ITEM}, // Shiny Stone
        {"shuca-berry", AbilityItemKind::ITEM}, // Shuca Berry
        {"silk-scarf", AbilityItemKind::ITEM}, // Silk Scarf
        {"silver-powder", AbilityItemKind::ITEM}, // Silver Powder
        {"simple", AbilityItemKind::ABILITY}, // Simple
        {"sitrus-berry", AbilityItemKind::ITEM}, // Sitrus Berry
        {"skill-link", AbilityItemKind::ABILITY}, // Skill Link
        {"sky-plate", AbilityItemKind::ITEM}, // Sky Plate
        {"slow-start", AbilityItemKind::ABILITY}, // Slow Start
        {"slush-rush", AbilityItemKind::ABILITY}, // Slush Rush
        {"smooth-rock", AbilityItemKind::ITEM}, // Smooth Rock
        {"sniper", AbilityItemKind::ABILITY}, // Sniper
        {"snow-cloak", AbilityItemKind::ABILITY}, // Snow Cloak
        {"snow-warning", AbilityItemKind::ABILITY}, // Snow Warning
        {"snowball", AbilityItemKind::ITEM}, // Snowball
        {"soft-sand", AbilityItemKind::ITEM}, // Soft Sand
        {"solar-power", AbilityItemKind::ABILITY}, // Solar Power
        {"solid-rock", AbilityItemKind::ABILITY}, // Solid Rock
        {"soul-dew", AbilityItemKind::ITEM}, // Soul Dew
        {"soul-heart", AbilityItemKind::ABILITY}, // Soul-Heart
        {"soundproof", AbilityItemKind::ABILITY}, // Soundproof
        {"speed-boost", AbilityItemKind::ABILITY}, // Speed Boost
        {"spell-tag", AbilityItemKind::ITEM}, // Spell Tag
        {"spicy-spray", AbilityItemKind::ABILITY}, // Spicy Spray
        {"splash-plate", AbilityItemKind::ITEM}, // Splash Plate
        {"spooky-plate", AbilityItemKind::ITEM}, // Spooky Plate
        {"sport-ball", AbilityItemKind::ITEM}, // Sport Ball
        {"stakeout", AbilityItemKind::ABILITY}, // Stakeout
        {"stall", AbilityItemKind::ABILITY}, // Stall
        {"stalwart", AbilityItemKind::ABILITY}, // Stalwart
        {"stamina", AbilityItemKind::ABILITY}, // Stamina
        {"stance-change", AbilityItemKind::ABILITY}, // Stance Change
        {"star-sweet", AbilityItemKind::ITEM}, // Star Sweet
        {"starf-berry", AbilityItemKind::ITEM}, // Starf Berry
        {"static", AbilityItemKind::ABILITY}, // Static
        {"steadfast", AbilityItemKind::ABILITY}, // Steadfast
        {"steam-engine", AbilityItemKind::ABILITY}, // Steam Engine
        {"steelworker", AbilityItemKind::ABILITY}, // Steelworker
        {"steely-spirit", AbilityItemKind::ABILITY}, // Steely Spirit
        {"stench", AbilityItemKind::ABILITY}, // Stench
        {"sticky-barb", AbilityItemKind::ITEM}, // Sticky Barb
        {"sticky-hold", AbilityItemKind::ABILITY}, // Sticky Hold
        {"stone-plate", AbilityItemKind::ITEM}, // Stone Plate
        {"storm-drain", AbilityItemKind::ABILITY}, // Storm Drain
        {"strawberry-sweet", AbilityItemKind::ITEM}, // Strawberry Sweet
        {"strong-jaw", AbilityItemKind::ABILITY}, // Strong Jaw
        {"sturdy", AbilityItemKind::ABILITY}, // Sturdy
        {"suction-cups", AbilityItemKind::ABILITY}, // Suction Cups
        {"sun-stone", AbilityItemKind::ITEM}, // Sun Stone
        {"super-luck", AbilityItemKind::ABILITY}, // Super Luck
        {"supersweet-syrup", AbilityItemKind::ABILITY}, // Supersweet Syrup
        {"supreme-overlord", AbilityItemKind::ABILITY}, // Supreme Overlord
        {"surge-surfer", AbilityItemKind::ABILITY}, // Surge Surfer
        {"swarm", AbilityItemKind::ABILITY}, // Swarm
        {"sweet-apple", AbilityItemKind::ITEM}, // Sweet Apple
        {"sweet-veil", AbilityItemKind::ABILITY}, // Sweet Veil
        {"swift-swim", AbilityItemKind::ABILITY}, // Swift Swim
        {"sword-of-ruin", AbilityItemKind::ABILITY}, // Sword of Ruin
        {"symbiosis", AbilityItemKind::ABILITY}, // Symbiosis
        {"synchronize", AbilityItemKind::ABILITY}, // Synchronize
        {"syrupy-apple", AbilityItemKind::ITEM}, // Syrupy Apple
        {"tablets-of-ruin", AbilityItemKind::ABILITY}, // Tablets of Ruin
        {"tamato-berry", AbilityItemKind::ITEM}, // Tamato Berry
        {"tanga-berry", AbilityItemKind::ITEM}, // Tanga Berry
        {"tangled-feet", AbilityItemKind::ABILITY}, // Tangled Feet
        {"tangling-hair", AbilityItemKind::ABILITY}, // Tangling Hair
        {"tart-apple", AbilityItemKind::ITEM}, // Tart Apple
        {"technician", AbilityItemKind::ABILITY}, // Technician
        {"telepathy", AbilityItemKind::ABILITY}, // Telepathy
        {"tera-shell", AbilityItemKind::ABILITY}, // Tera Shell
        {"tera-shift", AbilityItemKind::ABILITY}, // Tera Shift
        {"teraform-zero", AbilityItemKind::ABILITY}, // Teraform Zero
        {"teravolt", AbilityItemKind::ABILITY}, // Teravolt
        {"terrain-extender", AbilityItemKind::ITEM}, // Terrain Extender
        {"thermal-exchange", AbilityItemKind::ABILITY}, // Thermal Exchange
        {"thick-fat", AbilityItemKind::ABILITY}, // Thick Fat
        {"throat-spray", AbilityItemKind::ITEM}, // Throat Spray
        {"thunder-stone", AbilityItemKind::ITEM}, // Thunder Stone
        {"timer-ball", AbilityItemKind::ITEM}, // Timer Ball
        {"tinted-lens", AbilityItemKind::ABILITY}, // Tinted Lens
        {"torrent", AbilityItemKind::ABILITY}, // Torrent
        {"tough-claws", AbilityItemKind::ABILITY}, // Tough Claws
        {"toxic-boost", AbilityItemKind::ABILITY}, // Toxic Boost
        {"toxic-chain", AbilityItemKind::ABILITY}, // Toxic Chain
        {"toxic-debris", AbilityItemKind::ABILITY}, // Toxic Debris
        {"toxic-orb", AbilityItemKind::ITEM}, // Toxic Orb
        {"toxic-plate", AbilityItemKind::ITEM}, // Toxic Plate
        {"trace", AbilityItemKind::ABILITY}, // Trace
        {"transistor", AbilityItemKind::ABILITY}, // Transistor
        {"triage", AbilityItemKind::ABILITY}, // Triage
        {"truant", AbilityItemKind::ABILITY}, // Truant
        {"turboblaze", AbilityItemKind::ABILITY}, // Turboblaze
        {"twisted-spoon", AbilityItemKind::ITEM}, // Twisted Spoon
        {"ultra-ball", AbilityItemKind::ITEM}, // Ultra Ball
        {"unaware", AbilityItemKind::ABILITY}, // Unaware
        {"unburden", AbilityItemKind::ABILITY}, // Unburden
        {"unnerve", AbilityItemKind::ABILITY}, // Unnerve
        {"unremarkable-teacup", AbilityItemKind::ITEM}, // Unremarkable Teacup
        {"unseen-fist", AbilityItemKind::ABILITY}, // Unseen Fist
        {"up-grade", AbilityItemKind::ITEM}, // Up-Grade
        {"utility-umbrella", AbilityItemKind::ITEM}, // Utility Umbrella
        {"vessel-of-ruin", AbilityItemKind::ABILITY}, // Vessel of Ruin
        {"victory-star", AbilityItemKind::ABILITY}, // Victory Star
        {"vital-spirit", AbilityItemKind::ABILITY}, // Vital Spirit
        {"volt-absorb", AbilityItemKind::ABILITY}, // Volt Absorb
        {"wacan-berry", AbilityItemKind::ITEM}, // Wacan Berry
        {"wandering-spirit", AbilityItemKind::ABILITY}, // Wandering Spirit
        {"water-absorb", AbilityItemKind::ABILITY}, // Water Absorb
        {"water-bubble", AbilityItemKind::ABILITY}, // Water Bubble
        {"water-compaction", AbilityItemKind::ABILITY}, // Water Compaction
        {"water-stone", AbilityItemKind::ITEM}, // Water Stone
        {"water-veil", AbilityItemKind::ABILITY}, // Water Veil
        {"weak-armor", AbilityItemKind::ABILITY}, // Weak Armor
        {"weakness-policy", AbilityItemKind::ITEM}, // Weakness Policy
        {"well-baked-body", AbilityItemKind::ABILITY}, // Well-Baked Body
        {"wellspring-mask", AbilityItemKind::ITEM}, // Wellspring Mask
        {"white-herb", AbilityItemKind::ITEM}, // White Herb
        {"white-smoke", AbilityItemKind::ABILITY}, // White Smoke
        {"wide-lens", AbilityItemKind::ITEM}, // Wide Lens
        {"wiki-berry", AbilityItemKind::ITEM}, // Wiki Berry
        {"wimp-out", AbilityItemKind::ABILITY}, // Wimp Out
        {"wind-power", AbilityItemKind::ABILITY}, // Wind Power
        {"wind-rider", AbilityItemKind::ABILITY}, // Wind Rider
        {"wise-glasses", AbilityItemKind::ITEM}, // Wise Glasses
        {"wonder-guard", AbilityItemKind::ABILITY}, // Wonder Guard
        {"wonder-skin", AbilityItemKind::ABILITY}, // Wonder Skin
        {"yache-berry", AbilityItemKind::ITEM}, // Yache Berry
        {"zap-plate", AbilityItemKind::ITEM}, // Zap Plate
        {"zen-mode", AbilityItemKind::ABILITY}, // Zen Mode
        {"zero-to-hero", AbilityItemKind::ABILITY}, // Zero to Hero
        {"zoom-lens", AbilityItemKind::ITEM}, // Zoom Lens
    };
    return t;
}
}  //  anon namespace

AbilityItemKind lookup_ability_item_kind(const std::string& slug){
    const auto& t = table();
    auto it = t.find(slug);
    if (it == t.end()) return AbilityItemKind::UNKNOWN;
    return it->second;
}

//  Cap distance computation early. For long slugs this is fast enough
//  for a 563-entry table (one read), and we'd rather a O(N) scan than
//  maintain a separate trie/BK-tree.
static size_t levenshtein(const std::string& a, const std::string& b, size_t cap){
    size_t la = a.size(), lb = b.size();
    if (la > lb + cap || lb > la + cap) return cap + 1;
    std::vector<size_t> prev(lb + 1), cur(lb + 1);
    for (size_t j = 0; j <= lb; j++) prev[j] = j;
    for (size_t i = 1; i <= la; i++){
        cur[0] = i;
        size_t row_min = cur[0];
        for (size_t j = 1; j <= lb; j++){
            size_t cost = (a[i-1] == b[j-1]) ? 0 : 1;
            cur[j] = std::min({prev[j] + 1, cur[j-1] + 1, prev[j-1] + cost});
            row_min = std::min(row_min, cur[j]);
        }
        if (row_min > cap) return cap + 1;
        std::swap(prev, cur);
    }
    return prev[lb];
}

AbilityItemKind fuzzy_lookup_ability_item_kind(
    const std::string& slug, std::string* corrected_out, size_t max_distance
){
    const auto& t = table();
    size_t best = max_distance + 1;
    const std::string* best_slug = nullptr;
    AbilityItemKind best_kind = AbilityItemKind::UNKNOWN;
    for (const auto& kv : t){
        size_t d = levenshtein(slug, kv.first, best);
        if (d < best){
            best = d;
            best_slug = &kv.first;
            best_kind = kv.second;
            if (d == 0) break;
        }
    }
    if (best_slug && corrected_out) *corrected_out = *best_slug;
    return best_kind == AbilityItemKind::UNKNOWN ? AbilityItemKind::UNKNOWN : best_kind;
}

size_t ability_item_table_size(){ return table().size(); }

}}}
