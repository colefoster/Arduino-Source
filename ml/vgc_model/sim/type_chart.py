"""Pokemon type effectiveness chart (Gen 6+, including Fairy).

Provides the 18x18 type matchup multipliers for damage calculation.
"""

# Standard 18 types in canonical order
TYPES = [
    "Normal", "Fire", "Water", "Electric", "Grass", "Ice",
    "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug",
    "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy",
]

# Effectiveness matrix: _EFF[attacking_type][defending_type] = multiplier
# Only store non-1.0 entries for compactness
_SUPER = 2.0    # super effective
_RESIST = 0.5   # not very effective
_IMMUNE = 0.0   # no effect

_EFF: dict[str, dict[str, float]] = {
    "Normal":   {"Rock": _RESIST, "Ghost": _IMMUNE, "Steel": _RESIST},
    "Fire":     {"Fire": _RESIST, "Water": _RESIST, "Grass": _SUPER, "Ice": _SUPER,
                 "Bug": _SUPER, "Rock": _RESIST, "Dragon": _RESIST, "Steel": _SUPER},
    "Water":    {"Fire": _SUPER, "Water": _RESIST, "Grass": _RESIST, "Ground": _SUPER,
                 "Rock": _SUPER, "Dragon": _RESIST},
    "Electric": {"Water": _SUPER, "Electric": _RESIST, "Grass": _RESIST, "Ground": _IMMUNE,
                 "Flying": _SUPER, "Dragon": _RESIST},
    "Grass":    {"Fire": _RESIST, "Water": _SUPER, "Grass": _RESIST, "Poison": _RESIST,
                 "Ground": _SUPER, "Flying": _RESIST, "Bug": _RESIST, "Rock": _SUPER,
                 "Dragon": _RESIST, "Steel": _RESIST},
    "Ice":      {"Fire": _RESIST, "Water": _RESIST, "Grass": _SUPER, "Ice": _RESIST,
                 "Ground": _SUPER, "Flying": _SUPER, "Dragon": _SUPER, "Steel": _RESIST},
    "Fighting": {"Normal": _SUPER, "Ice": _SUPER, "Poison": _RESIST, "Flying": _RESIST,
                 "Psychic": _RESIST, "Bug": _RESIST, "Rock": _SUPER, "Ghost": _IMMUNE,
                 "Dark": _SUPER, "Steel": _SUPER, "Fairy": _RESIST},
    "Poison":   {"Grass": _SUPER, "Poison": _RESIST, "Ground": _RESIST, "Rock": _RESIST,
                 "Ghost": _RESIST, "Steel": _IMMUNE, "Fairy": _SUPER},
    "Ground":   {"Fire": _SUPER, "Electric": _SUPER, "Grass": _RESIST, "Poison": _SUPER,
                 "Flying": _IMMUNE, "Bug": _RESIST, "Rock": _SUPER, "Steel": _SUPER},
    "Flying":   {"Electric": _RESIST, "Grass": _SUPER, "Fighting": _SUPER, "Bug": _SUPER,
                 "Rock": _RESIST, "Steel": _RESIST},
    "Psychic":  {"Fighting": _SUPER, "Poison": _SUPER, "Psychic": _RESIST, "Dark": _IMMUNE,
                 "Steel": _RESIST},
    "Bug":      {"Fire": _RESIST, "Grass": _SUPER, "Fighting": _RESIST, "Poison": _RESIST,
                 "Flying": _RESIST, "Psychic": _SUPER, "Ghost": _RESIST, "Dark": _SUPER,
                 "Steel": _RESIST, "Fairy": _RESIST},
    "Rock":     {"Fire": _SUPER, "Ice": _SUPER, "Fighting": _RESIST, "Ground": _RESIST,
                 "Flying": _SUPER, "Bug": _SUPER, "Steel": _RESIST},
    "Ghost":    {"Normal": _IMMUNE, "Psychic": _SUPER, "Ghost": _SUPER, "Dark": _RESIST},
    "Dragon":   {"Dragon": _SUPER, "Steel": _RESIST, "Fairy": _IMMUNE},
    "Dark":     {"Fighting": _RESIST, "Psychic": _SUPER, "Ghost": _SUPER, "Dark": _RESIST,
                 "Fairy": _RESIST},
    "Steel":    {"Fire": _RESIST, "Water": _RESIST, "Electric": _RESIST, "Ice": _SUPER,
                 "Rock": _SUPER, "Steel": _RESIST, "Fairy": _SUPER},
    "Fairy":    {"Fire": _RESIST, "Poison": _RESIST, "Fighting": _SUPER, "Dragon": _SUPER,
                 "Dark": _SUPER, "Steel": _RESIST},
}


def type_effectiveness(atk_type: str, def_type1: str, def_type2: str = "") -> float:
    """Calculate type effectiveness multiplier.

    Args:
        atk_type: attacking move's type
        def_type1: defender's primary type
        def_type2: defender's secondary type (empty string if monotype)

    Returns:
        Combined multiplier (0.0, 0.25, 0.5, 1.0, 2.0, or 4.0)
    """
    if not atk_type:
        return 1.0

    chart = _EFF.get(atk_type, {})
    mult = chart.get(def_type1, 1.0)
    if def_type2:
        mult *= chart.get(def_type2, 1.0)
    return mult
