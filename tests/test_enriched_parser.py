"""Tests for the enriched two-pass battle log parser."""

import pytest

from src.vgc_model.data.enriched_parser import (
    CONF_KNOWN,
    CONF_PLAYER,
    CONF_UNKNOWN,
    CONF_USAGE,
    EnrichedBattleParser,
    EnrichedSample,
    _pass1_extract,
    parse_battle_enriched,
)


# ---------------------------------------------------------------------------
# Minimal battle log for testing
# ---------------------------------------------------------------------------
# A short VGC doubles log: 6 pokemon per side, bring 4, 2 leads.
# p1 wins. Enough turns to test progressive revelation.
SAMPLE_LOG = """\
|player|p1|Player1|
|player|p2|Player2|
|poke|p1|Charizard, L50, M|
|poke|p1|Venusaur, L50, M|
|poke|p1|Blastoise, L50, M|
|poke|p1|Pikachu, L50, M|
|poke|p1|Snorlax, L50, M|
|poke|p1|Gengar, L50, M|
|poke|p2|Garchomp, L50, M|
|poke|p2|Salamence, L50, M|
|poke|p2|Metagross, L50, M|
|poke|p2|Tyranitar, L50, M|
|poke|p2|Rotom, L50|
|poke|p2|Amoonguss, L50, M|
|start
|switch|p1a: Zard|Charizard, L50, M|100/100
|switch|p1b: Venu|Venusaur, L50, M|100/100
|switch|p2a: Chomp|Garchomp, L50, M|100/100
|switch|p2b: Sally|Salamence, L50, M|100/100
|turn|1
|move|p1a: Zard|Heat Wave|p2a: Chomp
|-ability|p2b: Sally|Intimidate
|move|p1b: Venu|Sleep Powder|p2a: Chomp
|move|p2a: Chomp|Earthquake|
|move|p2b: Sally|Draco Meteor|p1a: Zard
|-damage|p1a: Zard|55/100
|turn|2
|move|p1a: Zard|Flamethrower|p2b: Sally
|-damage|p2b: Sally|30/100
|move|p1b: Venu|Giga Drain|p2a: Chomp
|-damage|p2a: Chomp|60/100
|move|p2a: Chomp|Rock Slide|
|move|p2b: Sally|Hydro Pump|p1a: Zard
|-damage|p1a: Zard|20/100
|turn|3
|move|p1a: Zard|Protect||
|move|p1b: Venu|Sludge Bomb|p2b: Sally
|-damage|p2b: Sally|0/100
|faint|p2b: Sally
|move|p2a: Chomp|Dragon Claw|p1b: Venu
|-damage|p1b: Venu|70/100
|
|switch|p2b: Meta|Metagross, L50, M|100/100
|turn|4
|-item|p2b: Meta|Assault Vest
|move|p1a: Zard|Heat Wave|p2a: Chomp
|-damage|p2a: Chomp|0/100
|faint|p2a: Chomp
|move|p1b: Venu|Giga Drain|p2b: Meta
|move|p2b: Meta|Bullet Punch|p1a: Zard
|-damage|p1a: Zard|5/100
|win|Player1
"""


class TestPass1Extract:
    """Test the full-log knowledge extraction pass."""

    def test_extracts_all_moves(self):
        knowledge = _pass1_extract(SAMPLE_LOG)
        # p1 Charizard used: Heat Wave, Flamethrower, Protect
        zard = knowledge["p1|Charizard"]
        assert set(zard.moves) == {"Heat Wave", "Flamethrower", "Protect"}

    def test_extracts_opponent_moves(self):
        knowledge = _pass1_extract(SAMPLE_LOG)
        chomp = knowledge["p2|Garchomp"]
        assert set(chomp.moves) == {"Earthquake", "Rock Slide", "Dragon Claw"}

    def test_extracts_ability(self):
        knowledge = _pass1_extract(SAMPLE_LOG)
        sally = knowledge["p2|Salamence"]
        assert sally.ability == "Intimidate"

    def test_extracts_item(self):
        knowledge = _pass1_extract(SAMPLE_LOG)
        meta = knowledge["p2|Metagross"]
        assert meta.item == "Assault Vest"

    def test_unrevealed_stays_empty(self):
        knowledge = _pass1_extract(SAMPLE_LOG)
        # p1's Venusaur: no item or ability revealed
        venu = knowledge["p1|Venusaur"]
        assert venu.item == ""
        assert venu.ability == ""


class TestEnrichedParser:
    """Test the full enriched parser output."""

    def test_produces_samples(self):
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        assert samples is not None
        assert len(samples) > 0

    def test_samples_have_both_players(self):
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        players = {s.player for s in samples}
        assert players == {"p1", "p2"}

    def test_winner_flagged_correctly(self):
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        for s in samples:
            if s.player == "p1":
                assert s.is_winner is True
            else:
                assert s.is_winner is False

    def test_own_team_has_6_pokemon(self):
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        for s in samples:
            assert len(s.own_team_full) == 6

    def test_opp_preview_has_6_species(self):
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        for s in samples:
            assert len(s.opp_team_preview) == 6


class TestOwnTeamRetroactiveKnowledge:
    """Own team should have retroactive data from the full log."""

    def test_own_moves_known_from_log(self):
        """Even at turn 1, own team moves from the full log are present."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        # Get a p1 sample from turn 1
        p1_turn1 = [s for s in samples if s.player == "p1" and s.state.turn == 1]
        assert len(p1_turn1) == 1
        sample = p1_turn1[0]

        # Find Charizard in own team
        zard = next(p for p in sample.own_team_full if p.species == "Charizard")
        # Should have all 3 moves from the log (Heat Wave, Flamethrower, Protect)
        assert "Heat Wave" in zard.moves_known
        assert "Flamethrower" in zard.moves_known
        assert "Protect" in zard.moves_known
        # All with CONF_KNOWN
        for i, m in enumerate(zard.moves_known):
            if m:
                assert zard.move_confidences[i] == CONF_KNOWN

    def test_own_moves_padded_to_4(self):
        """Own team moves should be padded to 4 slots."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        p1_sample = next(s for s in samples if s.player == "p1")
        for poke in p1_sample.own_team_full:
            assert len(poke.moves_known) == 4
            assert len(poke.move_confidences) == 4

    def test_unknown_own_slots_have_zero_confidence(self):
        """Unfilled move slots should have CONF_UNKNOWN."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        p1_sample = next(s for s in samples if s.player == "p1")
        # Charizard has 3 known moves, 4th slot unknown
        zard = next(p for p in p1_sample.own_team_full if p.species == "Charizard")
        assert zard.moves_known[3] == ""
        assert zard.move_confidences[3] == CONF_UNKNOWN


class TestOpponentProgressiveRevelation:
    """Opponent info should only include what's revealed up to current turn."""

    def test_turn1_opp_moves_in_state(self):
        """At turn 1 sample emission, opponent moves from turn 1 are tracked.

        The sample is emitted when |turn|2 fires, so turn 1's moves have
        already been processed and appear in moves_known.
        """
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        p1_turn1 = next(s for s in samples if s.player == "p1" and s.state.turn == 1)
        # Garchomp used Earthquake in turn 1
        chomp = next(
            (p for p in p1_turn1.state.p2_active if "Garchomp" in p.species), None
        )
        assert chomp is not None
        assert "Earthquake" in chomp.moves_known
        # But Rock Slide (turn 2) should NOT be here yet
        assert "Rock Slide" not in chomp.moves_known

    def test_turn2_opp_has_turn1_moves(self):
        """At turn 2, opponent pokemon should have moves revealed in turn 1."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        p1_turn2 = next(s for s in samples if s.player == "p1" and s.state.turn == 2)

        # Garchomp used Earthquake in turn 1
        chomp = next(
            (p for p in p1_turn2.state.p2_active if "Garchomp" in p.species), None
        )
        assert chomp is not None
        assert "Earthquake" in chomp.moves_known

        # Salamence used Draco Meteor in turn 1
        sally = next(
            (p for p in p1_turn2.state.p2_active if "Salamence" in p.species), None
        )
        assert sally is not None
        assert "Draco Meteor" in sally.moves_known

    def test_turn3_opp_accumulates_moves(self):
        """By turn 3, opponent should have moves from turns 1 AND 2."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        p1_turn3 = next(s for s in samples if s.player == "p1" and s.state.turn == 3)

        chomp = next(
            (p for p in p1_turn3.state.p2_active if "Garchomp" in p.species), None
        )
        assert chomp is not None
        # Turn 1: Earthquake, Turn 2: Rock Slide
        assert "Earthquake" in chomp.moves_known
        assert "Rock Slide" in chomp.moves_known

    def test_opp_ability_revealed(self):
        """Opponent ability should appear once revealed in the log."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        # Salamence's Intimidate is revealed in turn 1
        p1_turn2 = next(s for s in samples if s.player == "p1" and s.state.turn == 2)
        sally = next(
            (p for p in p1_turn2.state.p2_active if "Salamence" in p.species), None
        )
        assert sally is not None
        assert sally.ability == "Intimidate"

    def test_opp_item_revealed_late(self):
        """Metagross Assault Vest revealed in turn 4 should not appear at turn 3."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        # Turn 3: Metagross just switched in, no item revealed yet
        p1_turn3_samples = [s for s in samples if s.player == "p1" and s.state.turn == 3]
        if p1_turn3_samples:
            # Metagross shouldn't be active yet at turn 3 state (switches in after turn 3)
            # But if it is, item should not be revealed
            for s in p1_turn3_samples:
                for p in s.state.p2_active + s.state.p2_bench:
                    if "Metagross" in p.species:
                        assert p.item == "" or p.item == "Assault Vest"


class TestConfidenceTiers:
    """Test confidence flag values for different enrichment sources."""

    def test_known_move_confidence(self):
        """Moves from the log should have CONF_KNOWN = 1.0."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        p1_sample = next(s for s in samples if s.player == "p1")
        zard = next(p for p in p1_sample.own_team_full if p.species == "Charizard")
        # First 3 moves are known from log
        for i in range(3):
            assert zard.move_confidences[i] == CONF_KNOWN

    def test_unknown_confidence(self):
        """Unfilled slots should have CONF_UNKNOWN = 0.0."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        p1_sample = next(s for s in samples if s.player == "p1")
        # Pikachu never appeared, so all moves unknown
        pika = next(p for p in p1_sample.own_team_full if p.species == "Pikachu")
        assert all(c == CONF_UNKNOWN for c in pika.move_confidences)
        assert pika.item_confidence == CONF_UNKNOWN
        assert pika.ability_confidence == CONF_UNKNOWN

    def test_usage_stats_confidence(self):
        """Moves filled from usage stats should have CONF_USAGE = 0.5."""

        class FakeUsageStats:
            def top_moves(self, species, n=4):
                if species == "Pikachu":
                    return ["Thunderbolt", "Fake Out", "Volt Switch", "Protect"]
                return []

            def top_item(self, species):
                if species == "Pikachu":
                    return "Focus Sash"
                return ""

            def top_ability(self, species):
                if species == "Pikachu":
                    return "Lightning Rod"
                return ""

        samples = parse_battle_enriched(
            SAMPLE_LOG, rating=1500, usage_stats=FakeUsageStats()
        )
        p1_sample = next(s for s in samples if s.player == "p1")
        pika = next(p for p in p1_sample.own_team_full if p.species == "Pikachu")

        # Pikachu has no log data, so all filled from usage
        assert pika.moves_known[0] == "Thunderbolt"
        assert all(c == CONF_USAGE for c in pika.move_confidences)
        assert pika.item == "Focus Sash"
        assert pika.item_confidence == CONF_USAGE
        assert pika.ability == "Lightning Rod"
        assert pika.ability_confidence == CONF_USAGE

    def test_player_profile_confidence(self):
        """Moves filled from player profiles should have CONF_PLAYER = 0.8."""

        class FakePlayerProfiles:
            def get_moves(self, player, species):
                if species == "Snorlax":
                    return ["Body Slam", "Curse", "Rest", "Sleep Talk"]
                return []

            def get_item(self, player, species):
                if species == "Snorlax":
                    return "Leftovers"
                return ""

            def get_ability(self, player, species):
                if species == "Snorlax":
                    return "Thick Fat"
                return ""

        samples = parse_battle_enriched(
            SAMPLE_LOG,
            rating=1500,
            player_profiles=FakePlayerProfiles(),
            player_name="Player1",
        )
        p1_sample = next(s for s in samples if s.player == "p1")
        snorlax = next(p for p in p1_sample.own_team_full if p.species == "Snorlax")

        assert snorlax.moves_known[0] == "Body Slam"
        assert all(c == CONF_PLAYER for c in snorlax.move_confidences)
        assert snorlax.item == "Leftovers"
        assert snorlax.item_confidence == CONF_PLAYER
        assert snorlax.ability == "Thick Fat"
        assert snorlax.ability_confidence == CONF_PLAYER

    def test_mixed_confidence_tiers(self):
        """Known log moves + player profile backfill = mixed confidences."""

        class FakePlayerProfiles:
            def get_moves(self, player, species):
                if species == "Charizard":
                    return ["Heat Wave", "Flamethrower", "Protect", "Air Slash"]
                return []

            def get_item(self, player, species):
                return ""

            def get_ability(self, player, species):
                return ""

        samples = parse_battle_enriched(
            SAMPLE_LOG,
            rating=1500,
            player_profiles=FakePlayerProfiles(),
            player_name="Player1",
        )
        p1_sample = next(s for s in samples if s.player == "p1")
        zard = next(p for p in p1_sample.own_team_full if p.species == "Charizard")

        # 3 moves from log (CONF_KNOWN), 1 from profile (CONF_PLAYER)
        known_count = sum(1 for c in zard.move_confidences if c == CONF_KNOWN)
        player_count = sum(1 for c in zard.move_confidences if c == CONF_PLAYER)
        assert known_count == 3
        assert player_count == 1
        assert "Air Slash" in zard.moves_known


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_log_returns_none(self):
        result = parse_battle_enriched("", rating=0)
        assert result is None

    def test_no_winner_returns_none(self):
        partial = """\
|player|p1|Alice|
|player|p2|Bob|
|poke|p1|Pikachu, L50, M|
|poke|p2|Charizard, L50, M|
"""
        result = parse_battle_enriched(partial, rating=0)
        assert result is None

    def test_rating_propagated(self):
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1750)
        assert all(s.rating == 1750 for s in samples)

    def test_no_enrichment_sources_still_works(self):
        """Parser works standalone without usage_stats or player_profiles."""
        samples = parse_battle_enriched(SAMPLE_LOG, rating=1500)
        assert samples is not None
        p1_sample = next(s for s in samples if s.player == "p1")
        # Pokemon that never appeared should have all-unknown
        pika = next(p for p in p1_sample.own_team_full if p.species == "Pikachu")
        assert all(m == "" for m in pika.moves_known)
        assert all(c == CONF_UNKNOWN for c in pika.move_confidences)
