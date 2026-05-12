"""Canonical volatile-status enum mirroring poke-engine's PokemonVolatileStatus.

108 distinct statuses. Used for parser normalization (Showdown protocol event
strings -> canonical names) and encoder bitmask layout (each status occupies
a fixed bit position).

Reference: github.com/pmariglia/poke-engine src/genx/state.rs
"""
from __future__ import annotations

# Order is load-bearing: a status's index in this list IS its bit position
# in the encoded shard's per-slot volatile bitmask. Adding a new entry must
# go at the END (preserve indices), or all old shards become invalid.
VOLATILE_STATUSES: list[str] = [
    "AQUARING", "ATTRACT", "AUTOTOMIZE", "BANEFULBUNKER", "BIDE", "BOUNCE",
    "BURNINGBULWARK", "CHARGE", "CONFUSION", "CURSE", "DEFENSECURL",
    "DESTINYBOND", "DIG", "DISABLE", "DIVE", "ELECTRIFY", "ELECTROSHOT",
    "EMBARGO", "ENCORE", "ENDURE", "FLASHFIRE", "FLINCH", "FLY", "FOCUSENERGY",
    "FOLLOWME", "FORESIGHT", "FREEZESHOCK", "GASTROACID", "GEOMANCY",
    "GLAIVERUSH", "GRUDGE", "HEALBLOCK", "HELPINGHAND", "ICEBURN", "IMPRISON",
    "INGRAIN", "KINGSSHIELD", "LASERFOCUS", "LEECHSEED", "LIGHTSCREEN",
    "LOCKEDMOVE", "MAGICCOAT", "MAGNETRISE", "MAXGUARD", "METEORBEAM",
    "MINIMIZE", "MIRACLEEYE", "MUSTRECHARGE", "NIGHTMARE", "NORETREAT",
    "OCTOLOCK", "PARTIALLYTRAPPED", "PERISH4", "PERISH3", "PERISH2", "PERISH1",
    "PHANTOMFORCE", "POWDER", "POWERSHIFT", "POWERTRICK", "PROTECT",
    "PROTOSYNTHESISATK", "PROTOSYNTHESISDEF", "PROTOSYNTHESISSPA",
    "PROTOSYNTHESISSPD", "PROTOSYNTHESISSPE", "QUARKDRIVEATK", "QUARKDRIVEDEF",
    "QUARKDRIVESPA", "QUARKDRIVESPD", "QUARKDRIVESPE", "RAGE", "RAGEPOWDER",
    "RAZORWIND", "REFLECT", "ROOST", "SALTCURE", "SHADOWFORCE", "SKULLBASH",
    "SKYATTACK", "SKYDROP", "SILKTRAP", "SLOWSTART", "SMACKDOWN", "SNATCH",
    "SOLARBEAM", "SOLARBLADE", "SPARKLINGARIA", "SPIKYSHIELD", "SPOTLIGHT",
    "STOCKPILE", "SUBSTITUTE", "SYRUPBOMB", "TARSHOT", "TAUNT", "TELEKINESIS",
    "THROATCHOP", "TRUANT", "TORMENT", "TYPECHANGE", "UNBURDEN", "UPROAR",
    "YAWN",
]
N_VOLATILE_STATUSES = len(VOLATILE_STATUSES)
_VOL_INDEX: dict[str, int] = {name: i for i, name in enumerate(VOLATILE_STATUSES)}


def volatile_index(name: str) -> int:
    """Return the canonical bit position of a volatile status, or -1 if unknown."""
    return _VOL_INDEX.get(name, -1)


def normalize_showdown_volatile(effect: str) -> str:
    """Map a Showdown protocol effect string to a canonical volatile name.

    Showdown emits effects like ``"Substitute"``, ``"move: Encore"``,
    ``"ability: Protosynthesis"``, ``"perish3"``, ``"confusion"``. We strip
    any prefix, lowercase, drop punctuation/whitespace, and look up the
    normalized form against a normalized canonical list.

    Returns "" if no match — caller decides whether to drop or warn.
    """
    if not effect:
        return ""
    s = effect
    for prefix in ("move:", "ability:", "item:", "Move:", "Ability:", "Item:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = "".join(ch.lower() for ch in s if ch.isalnum())
    if s in _NORMALIZED_INDEX:
        return _NORMALIZED_INDEX[s]
    # Special-case the protosynthesis/quarkdrive variants — Showdown emits
    # "protosynthesis" / "quarkdrive" without the ATK/DEF/SPA/SPD/SPE suffix
    # at the activation event; the boosted-stat variant comes from a later
    # boost event. Caller is responsible for upgrading the canonical name
    # once the boost stat is known. For now, return the bare ATK form so
    # the bit gets set somewhere meaningful.
    if s == "protosynthesis":
        return "PROTOSYNTHESISATK"
    if s == "quarkdrive":
        return "QUARKDRIVEATK"
    return ""


_NORMALIZED_INDEX: dict[str, str] = {
    "".join(ch.lower() for ch in name if ch.isalnum()): name
    for name in VOLATILE_STATUSES
}


# Volatiles emitted by Showdown's -singleturn or -singlemove that should
# be cleared at turn boundaries (they don't persist beyond this turn).
SINGLE_TURN_VOLATILES: frozenset[str] = frozenset({
    "PROTECT", "ENDURE", "BANEFULBUNKER", "BURNINGBULWARK", "KINGSSHIELD",
    "MAXGUARD", "OBSTRUCT", "SILKTRAP", "SPIKYSHIELD", "WIDEGUARD",
    "QUICKGUARD", "MATBLOCK", "CRAFTYSHIELD", "FOLLOWME", "RAGEPOWDER",
    "HELPINGHAND", "MAGICCOAT", "SNATCH", "ELECTRIFY", "POWDER",
    "DESTINYBOND", "GRUDGE", "ROOST",
})

