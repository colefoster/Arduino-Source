"""MCTS-style 1-ply search engine for VGC battle decisions.

Combines the action model (move probabilities), battle simulator
(turn outcome), and winrate model (position evaluation) to find
the best action pair via sampling and evaluation.

Flow:
  1. Action model → probability distributions for 4 slots (yours + theirs)
  2. Sample N rollouts weighted by probabilities
  3. Simulate each turn with battle sim
  4. Batch-evaluate resulting states with winrate model
  5. Return action pair with highest average win%
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import torch
import torch.nn.functional as F

from ..data.feature_tables import FeatureTables
from ..data.usage_stats import UsageStats
from ..data.vocab import Vocabs
from ..sim.battle_sim import BattleSim, SimState, SimPokemon, predict_request_to_sim_state


# Feature dims (must match what models were trained on)
SPECIES_FEAT_DIM = 46
MOVE_FEAT_DIM = 56
ITEM_FEAT_DIM = 13
ABILITY_FEAT_DIM = 16
BOOST_STATS = ["atk", "def", "spa", "spd", "spe", "evasion"]
MAX_ACTIONS = 14
MAX_HISTORY = 30  # must match VGCTransformerV2Seq.config.max_history
CONF_KNOWN = 1.0
CONF_USAGE = 0.5

# Action-type slugs the C++ live trace emits in history entries.
_HIST_TYPE_MOVE = "move"
_HIST_TYPE_SWITCH = "switch"


@dataclass
class SearchResult:
    action_a: int
    action_b: int
    win_pct: float
    own_probs_a: list[float] = field(default_factory=list)
    own_probs_b: list[float] = field(default_factory=list)
    opp_probs_a: list[float] = field(default_factory=list)
    opp_probs_b: list[float] = field(default_factory=list)
    n_rollouts: int = 0
    pair_scores: dict = field(default_factory=dict)


class SearchEngine:
    """1-ply MCTS search using action model + sim + winrate model."""

    def __init__(
        self,
        action_model,
        winrate_model,
        vocabs: Vocabs,
        feature_tables: FeatureTables,
        usage_stats: Optional[UsageStats],
        device: torch.device,
    ):
        self.action_model = action_model
        self.winrate_model = winrate_model
        self.vocabs = vocabs
        self.ft = feature_tables
        self.usage_stats = usage_stats
        self.device = device
        self.sim = BattleSim(feature_tables)

    def search(self, req_dict: dict, n_rollouts: int = 100) -> SearchResult:
        """Run 1-ply MCTS search and return best action pair."""

        # Step 1: Build v2-compatible batch from request (own perspective)
        batch_own = self._build_v2_batch(req_dict, perspective="own")

        # Step 2: Run action model from our POV
        with torch.no_grad():
            out_own = self.action_model(batch_own)
        probs_own_a = F.softmax(out_own["logits_a"].squeeze(0), dim=-1)
        probs_own_b = F.softmax(out_own["logits_b"].squeeze(0), dim=-1)

        # Step 3: Build swapped batch and run action model from opponent's POV
        batch_opp = self._build_v2_batch(req_dict, perspective="opp")
        with torch.no_grad():
            out_opp = self.action_model(batch_opp)
        probs_opp_a = F.softmax(out_opp["logits_a"].squeeze(0), dim=-1)
        probs_opp_b = F.softmax(out_opp["logits_b"].squeeze(0), dim=-1)

        # Step 4: Convert request to SimState
        sim_state = predict_request_to_sim_state(req_dict, self.ft, self.usage_stats)

        # Step 5: Sample N rollouts
        own_a_samples = torch.multinomial(probs_own_a, n_rollouts, replacement=True)
        own_b_samples = torch.multinomial(probs_own_b, n_rollouts, replacement=True)
        opp_a_samples = torch.multinomial(probs_opp_a, n_rollouts, replacement=True)
        opp_b_samples = torch.multinomial(probs_opp_b, n_rollouts, replacement=True)

        # Step 6: Simulate each rollout
        resulting_states: list[SimState] = []
        valid_indices: list[int] = []
        for i in range(n_rollouts):
            own_actions = (own_a_samples[i].item(), own_b_samples[i].item())
            opp_actions = (opp_a_samples[i].item(), opp_b_samples[i].item())
            try:
                new_state = self.sim.simulate_turn(sim_state, own_actions, opp_actions)
                resulting_states.append(new_state)
                valid_indices.append(i)
            except Exception:
                continue  # Skip broken sims

        if not resulting_states:
            # Fallback: return raw model prediction
            return SearchResult(
                action_a=probs_own_a.argmax().item(),
                action_b=probs_own_b.argmax().item(),
                win_pct=0.5,
                own_probs_a=probs_own_a.cpu().tolist(),
                own_probs_b=probs_own_b.cpu().tolist(),
                opp_probs_a=probs_opp_a.cpu().tolist(),
                opp_probs_b=probs_opp_b.cpu().tolist(),
                n_rollouts=0,
            )

        # Step 7: Batch-evaluate all resulting states with winrate model
        winrate_batch = self._states_to_winrate_batch(resulting_states)
        with torch.no_grad():
            win_logits = self.winrate_model(winrate_batch)["win_logit"]
        win_probs = torch.sigmoid(win_logits)  # (N,)

        # Step 8: Aggregate by (own_a, own_b) pair
        pair_scores: dict[tuple[int, int], list[float]] = defaultdict(list)
        for idx, vi in enumerate(valid_indices):
            pair = (own_a_samples[vi].item(), own_b_samples[vi].item())
            pair_scores[pair].append(win_probs[idx].item())

        # Step 9: Best pair by average win%
        best_pair = max(pair_scores, key=lambda p: sum(pair_scores[p]) / len(pair_scores[p]))
        best_win_pct = sum(pair_scores[best_pair]) / len(pair_scores[best_pair])

        return SearchResult(
            action_a=best_pair[0],
            action_b=best_pair[1],
            win_pct=best_win_pct,
            own_probs_a=probs_own_a.cpu().tolist(),
            own_probs_b=probs_own_b.cpu().tolist(),
            opp_probs_a=probs_opp_a.cpu().tolist(),
            opp_probs_b=probs_opp_b.cpu().tolist(),
            n_rollouts=len(resulting_states),
            pair_scores={f"{k[0]},{k[1]}": round(sum(v) / len(v), 4)
                         for k, v in pair_scores.items()},
        )

    # ── V2 batch encoding ────────────────────────────────────────

    def _build_v2_batch(self, req_dict: dict, perspective: str) -> dict[str, torch.Tensor]:
        """Build a v2-compatible tensor batch from a PredictRequest dict.

        When perspective="opp", swaps own/opp so the model predicts from
        the opponent's point of view.
        """
        if perspective == "opp":
            req = self._swap_perspective(req_dict)
        else:
            req = req_dict

        empty = {"species": "", "hp": 0.0, "status": "", "moves": [],
                 "item": "", "ability": "", "boosts": [0]*6, "is_mega": False, "alive": False}

        own_active = (req.get("own_active", []) + [empty, empty])[:2]
        own_bench = (req.get("own_bench", []) + [empty, empty])[:2]
        opp_active = (req.get("opp_active", []) + [empty, empty])[:2]
        opp_bench = (req.get("opp_bench", []) + [empty, empty])[:2]

        all_pokemon = own_active + own_bench + opp_active + opp_bench
        is_own = [True] * 4 + [False] * 4

        species_ids, hp_values, status_ids, boost_values = [], [], [], []
        item_ids, ability_ids, mega_flags, alive_flags, move_ids = [], [], [], [], []
        species_features, move_features, item_features, ability_features = [], [], [], []
        move_confidences, item_confidences, ability_confidences = [], [], []

        for slot_idx, poke in enumerate(all_pokemon):
            species = poke.get("species", "")
            if not species:
                species_ids.append(0); hp_values.append(0.0); status_ids.append(0)
                boost_values.append([0]*6); item_ids.append(0); ability_ids.append(0)
                mega_flags.append(0); alive_flags.append(0); move_ids.append([0,0,0,0])
                species_features.append(torch.zeros(SPECIES_FEAT_DIM))
                move_features.append(torch.zeros(4, MOVE_FEAT_DIM))
                item_features.append(torch.zeros(ITEM_FEAT_DIM))
                ability_features.append(torch.zeros(ABILITY_FEAT_DIM))
                move_confidences.append([0.0]*4); item_confidences.append(0.0)
                ability_confidences.append(0.0)
                continue

            alive = poke.get("alive", True)
            species_ids.append(self.vocabs.species[species])
            hp_values.append(poke.get("hp", 1.0) if alive else 0.0)
            status_ids.append(self.vocabs.status[poke.get("status", "")] if poke.get("status") else 0)
            # Boosts: model is (B,8,6) trained on [atk,def,spa,spd,spe,eva].
            # C++ emits 7-D [atk,def,spa,spd,spe,accuracy,evasion] (accuracy
            # is always 0). If we get 7 elements, drop index 5 to preserve
            # the trained layout. 6-D inputs pass through unchanged.
            raw_boosts = poke.get("boosts", [0]*6) or [0]*6
            if len(raw_boosts) >= 7:
                boosts = [raw_boosts[0], raw_boosts[1], raw_boosts[2],
                          raw_boosts[3], raw_boosts[4], raw_boosts[6]]
            else:
                boosts = (list(raw_boosts) + [0]*6)[:6]
            boost_values.append(boosts)
            mega_flags.append(int(poke.get("is_mega", False)))
            alive_flags.append(1 if alive else 0)

            # Species features
            sf = self.ft.get_species_features(species)
            species_features.append(FeatureTables.to_tensor(sf, "species"))

            # Moves — for own pokemon use what's known, for opp infer from usage
            moves = list(poke.get("moves", []))[:4]
            # If the client supplied per-move confidences (C++ tracker since
            # 2026-05-12), trust them. Otherwise fall back to the heuristic
            # (CONF_KNOWN for own / for opp's already-revealed moves).
            client_mconf = poke.get("move_confidences") or []
            client_mconf_signal = any(c > 0.0 for c in client_mconf[:len(moves)])
            if client_mconf_signal:
                m_confs = list(client_mconf[:len(moves)])
                # Pad missing trailing entries with 0.
                while len(m_confs) < len(moves):
                    m_confs.append(0.0)
            elif is_own[slot_idx]:
                m_confs = [CONF_KNOWN] * len(moves)
            else:
                m_confs = [CONF_KNOWN if m else 0.0 for m in moves]

            # Usage-stats fill (opp only) — only when we don't have all 4 moves
            # AND the C++ side didn't already populate the slot. Adds inferred
            # moves with CONF_USAGE so the model treats them as priors.
            if not is_own[slot_idx] and self.usage_stats and len(moves) < 4:
                inferred = self.usage_stats.infer_moveset(species, moves)
                for m in inferred[len(moves):]:
                    moves.append(m)
                    m_confs.append(CONF_USAGE)

            while len(moves) < 4: moves.append("")
            while len(m_confs) < 4: m_confs.append(0.0)

            move_ids.append([self.vocabs.moves[m] if m else 0 for m in moves[:4]])
            move_confidences.append(m_confs[:4])

            slot_mf = []
            for m in moves[:4]:
                if m:
                    slot_mf.append(FeatureTables.to_tensor(self.ft.get_move_features(m), "move"))
                else:
                    slot_mf.append(torch.zeros(MOVE_FEAT_DIM))
            move_features.append(torch.stack(slot_mf))

            # Item — prefer C++-supplied confidence (item_confidence); fall
            # back to usage stats for opp / CONF_KNOWN for own.
            item = poke.get("item", "")
            client_iconf = float(poke.get("item_confidence") or 0.0)
            if client_iconf > 0.0:
                i_conf = client_iconf
            elif not item and not is_own[slot_idx] and self.usage_stats:
                item = self.usage_stats.get_likely_item(species) or ""
                i_conf = CONF_USAGE if item else 0.0
            else:
                i_conf = CONF_KNOWN if item else 0.0
            item_ids.append(self.vocabs.items[item] if item else 0)
            item_confidences.append(i_conf)
            item_features.append(
                FeatureTables.to_tensor(self.ft.get_item_features(item), "item")
                if item else torch.zeros(ITEM_FEAT_DIM)
            )

            # Ability — same C++-confidence-first pattern as item.
            ability = poke.get("ability", "")
            client_aconf = float(poke.get("ability_confidence") or 0.0)
            if client_aconf > 0.0:
                a_conf = client_aconf
            elif not ability and not is_own[slot_idx] and self.usage_stats:
                ability = self.usage_stats.get_likely_ability(species) or ""
                a_conf = CONF_USAGE if ability else 0.0
            else:
                a_conf = CONF_KNOWN if ability else 0.0
            ability_ids.append(self.vocabs.abilities[ability] if ability else 0)
            ability_confidences.append(a_conf)
            ability_features.append(
                FeatureTables.to_tensor(self.ft.get_ability_features(ability), "ability")
                if ability else torch.zeros(ABILITY_FEAT_DIM)
            )

        f = req.get("field", {})
        D = self.device

        # Build v2_seq-compatible tensors
        batch = {
            "species_ids": torch.tensor([species_ids], dtype=torch.long, device=D),
            "hp_values": torch.tensor([hp_values], dtype=torch.float, device=D),
            "status_ids": torch.tensor([status_ids], dtype=torch.long, device=D),
            "boost_values": torch.tensor([boost_values], dtype=torch.float, device=D),
            "item_ids": torch.tensor([item_ids], dtype=torch.long, device=D),
            "ability_ids": torch.tensor([ability_ids], dtype=torch.long, device=D),
            "mega_flags": torch.tensor([mega_flags], dtype=torch.float, device=D),
            "alive_flags": torch.tensor([alive_flags], dtype=torch.float, device=D),
            "move_ids": torch.tensor([move_ids], dtype=torch.long, device=D),
            "species_features": torch.stack(species_features).unsqueeze(0).to(D),
            "move_features": torch.stack(move_features).unsqueeze(0).to(D),
            "item_features": torch.stack(item_features).unsqueeze(0).to(D),
            "ability_features": torch.stack(ability_features).unsqueeze(0).to(D),
            "move_confidences": torch.tensor([move_confidences], dtype=torch.float, device=D),
            "item_confidences": torch.tensor([item_confidences], dtype=torch.float, device=D),
            "ability_confidences": torch.tensor([ability_confidences], dtype=torch.float, device=D),
            "weather_id": torch.tensor([self.vocabs.weather[f.get("weather", "")] if f.get("weather") else 0], dtype=torch.long, device=D),
            "terrain_id": torch.tensor([self.vocabs.terrain[f.get("terrain", "")] if f.get("terrain") else 0], dtype=torch.long, device=D),
            "trick_room": torch.tensor([1.0 if f.get("trick_room") else 0.0], dtype=torch.float, device=D),
            "tailwind_own": torch.tensor([1.0 if f.get("tailwind_own") else 0.0], dtype=torch.float, device=D),
            "tailwind_opp": torch.tensor([1.0 if f.get("tailwind_opp") else 0.0], dtype=torch.float, device=D),
            "screens_own": torch.tensor([[1.0 if s else 0.0 for s in f.get("screens_own", [False]*3)[:3]]], dtype=torch.float, device=D),
            "screens_opp": torch.tensor([[1.0 if s else 0.0 for s in f.get("screens_opp", [False]*3)[:3]]], dtype=torch.float, device=D),
            "turn": torch.tensor([min(f.get("turn", 1), 30)], dtype=torch.float, device=D),
            "action_mask_a": torch.tensor([[True]*MAX_ACTIONS], dtype=torch.bool, device=D),
            "action_mask_b": torch.tensor([[True]*MAX_ACTIONS], dtype=torch.bool, device=D),
            # v2_seq prev_seq_* tensors. Populated from req["history"] when
            # the live trace sends per-turn snapshots; otherwise zeros (the
            # model treats prev_seq_len=0 as "no history"). Window matches
            # the trained model's max_history=30.
            **self._encode_history(req.get("history") or [], req, D),
            # Team preview (dummy — not used by action heads)
            "own_team_ids": torch.zeros(1, 6, dtype=torch.long, device=D),
            "opp_team_ids": torch.zeros(1, 6, dtype=torch.long, device=D),
            "selected_ids": torch.zeros(1, 4, dtype=torch.long, device=D),
            "has_team_preview": torch.tensor([False], dtype=torch.bool, device=D),
        }

        # Apply legal action masks from request
        la = req.get("legal_actions_a")
        if la:
            batch["action_mask_a"] = torch.tensor([(la + [True]*MAX_ACTIONS)[:MAX_ACTIONS]], dtype=torch.bool, device=D)
        lb = req.get("legal_actions_b")
        if lb:
            batch["action_mask_b"] = torch.tensor([(lb + [True]*MAX_ACTIONS)[:MAX_ACTIONS]], dtype=torch.bool, device=D)

        return batch

    def _encode_history(
        self, history: list[dict], req: dict, D: torch.device,
    ) -> dict[str, torch.Tensor]:
        """Pack the rolling per-turn history into the v2_seq prev_seq_* tensors.

        ``history`` is a list of dicts matching ``HistoryEntry`` from the
        inference server schema — newest-last, capped client-side. ``req``
        is the (already perspective-swapped) request, used to compare the
        last history entry against the current state for the flag bits.
        Returns the six prev_seq_* tensors shaped (1, MAX_HISTORY, ...) plus
        prev_seq_len (1,). Entries past MAX_HISTORY are dropped from the
        oldest end so the most recent turns win the window.

        Mirrors the trainer's encoder layout: slots [own_a, own_b, opp_a,
        opp_b]; action_types -> {noop=MAX_ACTIONS, move=0..11 placeholder,
        switch=12..13 placeholder}. The C++ side currently emits "noop"
        for action_types because per-turn action attribution is unreliable
        from OCR alone — that's fine; the LSTM still sees the state
        trajectory (species + HP), which carries most of the signal.

        prev_seq_flags[t] = [any_fainted, any_switch, field_changed]
            Trainer (enriched_dataset._encode_history_sequence) defines
            these by comparing turn t's snapshot to turn t+1 (the last
            entry compares against the *current* sample). We mirror that:
              any_fainted: any slot present at turn t with hp<=0 that's
                no longer represented at turn t+1.
              any_switch:  the set of base species across the 4 slots
                differs between turn t and turn t+1.
              field_changed: requires per-turn field state, which the C++
                history payload does not carry — left at 0.0 (gap).

        prev_seq_speed[t] = [own_a_went_first, own_b_went_first]
            Trainer derives from per-turn move_order log (1.0=own first,
            0.0=after, 0.5=unknown). The live-trace pipeline does not
            emit move order, so we default to 0.5 (unknown) — left as a
            gap to be filled when the C++ side starts publishing speed
            order per turn-transition.
        """
        # Keep newest MAX_HISTORY turns.
        history = history[-MAX_HISTORY:]
        T = len(history)

        actions = torch.full((1, MAX_HISTORY, 4), MAX_ACTIONS, dtype=torch.long, device=D)
        species = torch.zeros(1, MAX_HISTORY, 4, dtype=torch.long, device=D)
        hp = torch.zeros(1, MAX_HISTORY, 4, dtype=torch.float, device=D)
        flags = torch.zeros(1, MAX_HISTORY, 3, dtype=torch.float, device=D)
        speed = torch.full((1, MAX_HISTORY, 2), 0.5, dtype=torch.float, device=D)

        # Python-side lists of per-turn slot snapshots, for the flag pass.
        per_turn_species: list[list[str]] = []
        per_turn_hp: list[list[float]] = []
        per_turn_field: list[tuple[str, str, bool]] = []
        per_turn_order: list[list[int]] = []

        for t, entry in enumerate(history):
            spec_slugs = (entry.get("active_species") or []) + [""]*4
            hps = (entry.get("active_hp") or []) + [0.0]*4
            types = (entry.get("action_types") or []) + ["noop"]*4
            moves = (entry.get("action_moves") or []) + [""]*4
            per_turn_species.append([(s or "") for s in spec_slugs[:4]])
            per_turn_hp.append([float(h or 0.0) for h in hps[:4]])
            per_turn_field.append((
                entry.get("weather") or "",
                entry.get("terrain") or "",
                bool(entry.get("trick_room") or False),
            ))
            order = (entry.get("move_order") or []) + [-1]*4
            per_turn_order.append([int(order[s]) for s in range(4)])
            for s in range(4):
                slug = spec_slugs[s] or ""
                species[0, t, s] = self.vocabs.species[slug] if slug else 0
                hp[0, t, s] = float(hps[s] or 0.0)
                # Action encoding: noop = MAX_ACTIONS (pad), move = 0
                # (placeholder; live trace currently never carries a real
                # move slug here), switch = 12. The model's history LSTM
                # consumes this as a categorical embedding lookup; the
                # important signal is "move vs switch vs noop" rather than
                # which move exactly.
                a_type = types[s] or "noop"
                if a_type == _HIST_TYPE_SWITCH:
                    actions[0, t, s] = 12
                elif a_type == _HIST_TYPE_MOVE and (moves[s] or ""):
                    actions[0, t, s] = 0
                # else: stays at MAX_ACTIONS (noop / pad)

        # Snapshot of the *current* sample (one step past the last history
        # entry) — used as the comparison target for the last entry's flags.
        # Slot order matches the trainer: [own_a, own_b, opp_a, opp_b].
        cur_own = (req.get("own_active", []) + [{}, {}])[:2]
        cur_opp = (req.get("opp_active", []) + [{}, {}])[:2]
        cur_species = [
            (cur_own[0].get("species") or ""),
            (cur_own[1].get("species") or ""),
            (cur_opp[0].get("species") or ""),
            (cur_opp[1].get("species") or ""),
        ]
        cur_field_obj = req.get("field") or {}
        cur_field = (
            cur_field_obj.get("weather") or "",
            cur_field_obj.get("terrain") or "",
            bool(cur_field_obj.get("trick_room") or False),
        )

        for t in range(T):
            next_species = (per_turn_species[t + 1] if t + 1 < T else cur_species)
            next_field = (per_turn_field[t + 1] if t + 1 < T else cur_field)
            this_species = per_turn_species[t]
            this_hp = per_turn_hp[t]
            this_field = per_turn_field[t]

            this_set = {s for s in this_species if s}
            next_set = {s for s in next_species if s}

            # any_switch: species set differs between this turn and next.
            any_switch = 1.0 if this_set != next_set else 0.0

            # any_fainted: a slot present this turn with hp<=0 that is no
            # longer present next turn. Approximates the trainer rule
            # (which compared full state from the prior sample's view).
            any_fainted = 0.0
            for s_idx, slug in enumerate(this_species):
                if slug and this_hp[s_idx] <= 0.0 and slug not in next_set:
                    any_fainted = 1.0
                    break

            # field_changed: (weather, terrain, trick_room) tuple differs
            # vs the next turn (or current request, for the last entry).
            field_changed = 1.0 if this_field != next_field else 0.0
            flags[0, t, 0] = any_fainted
            flags[0, t, 1] = any_switch
            flags[0, t, 2] = field_changed

            # prev_seq_speed[t] = [own_a_went_first, own_b_went_first].
            # 1.0 if the own slot moved strictly before every opp slot that
            # also moved this turn; 0.0 if it moved after any opp; 0.5 if
            # the own slot did not move (move_order == -1 sentinel).
            order = per_turn_order[t]
            own_a, own_b, opp_a, opp_b = order[0], order[1], order[2], order[3]
            opp_orders = [v for v in (opp_a, opp_b) if v >= 0]
            for slot_idx, own_v in enumerate((own_a, own_b)):
                if own_v < 0:
                    speed[0, t, slot_idx] = 0.5
                elif not opp_orders:
                    # Own moved, no opp moved — by convention own went first.
                    speed[0, t, slot_idx] = 1.0
                elif own_v < min(opp_orders):
                    speed[0, t, slot_idx] = 1.0
                else:
                    speed[0, t, slot_idx] = 0.0

        return {
            "prev_seq_actions": actions,
            "prev_seq_species": species,
            "prev_seq_hp": hp,
            "prev_seq_flags": flags,
            "prev_seq_speed": speed,
            "prev_seq_len": torch.tensor([T], dtype=torch.long, device=D),
        }

    @staticmethod
    def _swap_perspective(req_dict: dict) -> dict:
        """Swap own/opp in the request to get opponent's POV."""
        swapped = dict(req_dict)
        swapped["own_active"] = req_dict.get("opp_active", [])
        swapped["own_bench"] = req_dict.get("opp_bench", [])
        swapped["opp_active"] = req_dict.get("own_active", [])
        swapped["opp_bench"] = req_dict.get("own_bench", [])

        f = dict(req_dict.get("field", {}))
        f["tailwind_own"], f["tailwind_opp"] = f.get("tailwind_opp", False), f.get("tailwind_own", False)
        f["screens_own"], f["screens_opp"] = f.get("screens_opp", [False]*3), f.get("screens_own", [False]*3)
        # Encoder-shape additions (2026-05-12). Swap each side's hazards,
        # side-condition timers, and side-level last-move ledger.
        f["hazards_own"], f["hazards_opp"] = f.get("hazards_opp", {}), f.get("hazards_own", {})
        f["side_timers_own"], f["side_timers_opp"] = f.get("side_timers_opp", {}), f.get("side_timers_own", {})
        f["last_move_own"], f["last_move_opp"] = f.get("last_move_opp", ""), f.get("last_move_own", "")
        swapped["field"] = f

        # Swap legal action masks
        swapped["legal_actions_a"] = None
        swapped["legal_actions_b"] = None

        # Swap history slot ordering: encoder lays out each entry as
        # [own_a, own_b, opp_a, opp_b]; for the opponent's POV we mirror
        # slots 0↔2 and 1↔3 in every per-turn array.
        hist = req_dict.get("history") or []
        if hist:
            mirrored = []
            for e in hist:
                def _swap4(lst, default):
                    arr = (list(lst or []) + [default]*4)[:4]
                    return [arr[2], arr[3], arr[0], arr[1]]
                mirrored.append({
                    "active_species": _swap4(e.get("active_species"), ""),
                    "active_hp":      _swap4(e.get("active_hp"), 0.0),
                    "action_types":   _swap4(e.get("action_types"), "noop"),
                    "action_moves":   _swap4(e.get("action_moves"), ""),
                    #  move_order is slot-indexed [own_a, own_b, opp_a, opp_b]
                    #  too, so it mirrors 0↔2 / 1↔3 like the rest.
                    "move_order":     _swap4(e.get("move_order"), -1),
                    #  weather / terrain / trick_room are global field state —
                    #  not own/opp-relative — so they pass through unchanged.
                    "weather":        e.get("weather", ""),
                    "terrain":        e.get("terrain", ""),
                    "trick_room":     bool(e.get("trick_room", False)),
                })
            swapped["history"] = mirrored
        return swapped

    # ── Winrate batch encoding ───────────────────────────────────

    def _states_to_winrate_batch(self, states: list[SimState]) -> dict[str, torch.Tensor]:
        """Batch-encode N SimStates for the winrate model in one forward pass."""
        N = len(states)

        all_species_ids, all_hp, all_status, all_boosts = [], [], [], []
        all_item_ids, all_ability_ids, all_mega, all_alive, all_move_ids = [], [], [], [], []
        all_sp_feat, all_mv_feat, all_it_feat, all_ab_feat = [], [], [], []
        all_mv_conf, all_it_conf, all_ab_conf = [], [], []
        all_weather, all_terrain, all_tr, all_tw_own, all_tw_opp = [], [], [], [], []
        all_sc_own, all_sc_opp, all_turn = [], [], []

        for state in states:
            # Same 8-slot layout
            empty_poke = SimPokemon(species="", hp_frac=0.0,
                                    base_stats={"hp":0,"atk":0,"def":0,"spa":0,"spd":0,"spe":0},
                                    types=("",""), moves=[], fainted=True)
            slots = [
                state.own_active[0] if len(state.own_active) > 0 else empty_poke,
                state.own_active[1] if len(state.own_active) > 1 else empty_poke,
                state.own_bench[0] if len(state.own_bench) > 0 else empty_poke,
                state.own_bench[1] if len(state.own_bench) > 1 else empty_poke,
                state.opp_active[0] if len(state.opp_active) > 0 else empty_poke,
                state.opp_active[1] if len(state.opp_active) > 1 else empty_poke,
                state.opp_bench[0] if len(state.opp_bench) > 0 else empty_poke,
                state.opp_bench[1] if len(state.opp_bench) > 1 else empty_poke,
            ]
            is_own = [True]*4 + [False]*4

            sp_ids, hp_v, st_ids, bst_v = [], [], [], []
            it_ids, ab_ids, mg_f, al_f, mv_ids = [], [], [], [], []
            sp_f, mv_f, it_f, ab_f = [], [], [], []
            mv_c, it_c, ab_c = [], [], []

            for i, poke in enumerate(slots):
                if not poke.species or poke.fainted:
                    sp_ids.append(0); hp_v.append(0.0); st_ids.append(0)
                    bst_v.append([0]*6); it_ids.append(0); ab_ids.append(0)
                    mg_f.append(0); al_f.append(0); mv_ids.append([0,0,0,0])
                    sp_f.append(torch.zeros(SPECIES_FEAT_DIM))
                    mv_f.append(torch.zeros(4, MOVE_FEAT_DIM))
                    it_f.append(torch.zeros(ITEM_FEAT_DIM))
                    ab_f.append(torch.zeros(ABILITY_FEAT_DIM))
                    mv_c.append([0.0]*4); it_c.append(0.0); ab_c.append(0.0)
                    continue

                sp_ids.append(self.vocabs.species[poke.species])
                hp_v.append(poke.hp_frac)
                st_ids.append(self.vocabs.status[poke.status] if poke.status else 0)
                bst_v.append([poke.boosts.get(s, 0) for s in BOOST_STATS[:5]] + [0])
                it_ids.append(self.vocabs.items[poke.item] if poke.item else 0)
                ab_ids.append(self.vocabs.abilities[poke.ability] if poke.ability else 0)
                mg_f.append(int(poke.is_mega))
                al_f.append(1)

                sp_f.append(FeatureTables.to_tensor(self.ft.get_species_features(poke.species), "species"))

                moves = (poke.moves + ["","","",""])[:4]
                mv_ids.append([self.vocabs.moves[m] if m else 0 for m in moves])
                conf = CONF_KNOWN if is_own[i] else CONF_USAGE
                mv_c.append([conf if m else 0.0 for m in moves])
                slot_mf = []
                for m in moves:
                    if m:
                        slot_mf.append(FeatureTables.to_tensor(self.ft.get_move_features(m), "move"))
                    else:
                        slot_mf.append(torch.zeros(MOVE_FEAT_DIM))
                mv_f.append(torch.stack(slot_mf))

                it_f.append(FeatureTables.to_tensor(self.ft.get_item_features(poke.item), "item") if poke.item else torch.zeros(ITEM_FEAT_DIM))
                it_ids[-1] = self.vocabs.items[poke.item] if poke.item else 0
                it_c.append(conf if poke.item else 0.0)

                ab_f.append(FeatureTables.to_tensor(self.ft.get_ability_features(poke.ability), "ability") if poke.ability else torch.zeros(ABILITY_FEAT_DIM))
                ab_c.append(conf if poke.ability else 0.0)

            all_species_ids.append(sp_ids)
            all_hp.append(hp_v)
            all_status.append(st_ids)
            all_boosts.append(bst_v)
            all_item_ids.append(it_ids)
            all_ability_ids.append(ab_ids)
            all_mega.append(mg_f)
            all_alive.append(al_f)
            all_move_ids.append(mv_ids)
            all_sp_feat.append(torch.stack(sp_f))
            all_mv_feat.append(torch.stack(mv_f))
            all_it_feat.append(torch.stack(it_f))
            all_ab_feat.append(torch.stack(ab_f))
            all_mv_conf.append(mv_c)
            all_it_conf.append(it_c)
            all_ab_conf.append(ab_c)

            all_weather.append(self.vocabs.weather[state.field.weather] if state.field.weather else 0)
            all_terrain.append(self.vocabs.terrain[state.field.terrain] if state.field.terrain else 0)
            all_tr.append(1.0 if state.field.trick_room else 0.0)
            all_tw_own.append(1.0 if state.field.tailwind_own else 0.0)
            all_tw_opp.append(1.0 if state.field.tailwind_opp else 0.0)
            all_sc_own.append([1.0 if s else 0.0 for s in state.field.screens_own[:3]])
            all_sc_opp.append([1.0 if s else 0.0 for s in state.field.screens_opp[:3]])
            all_turn.append(min(state.turn, 30))

        D = self.device
        return {
            "species_ids": torch.tensor(all_species_ids, dtype=torch.long, device=D),
            "hp_values": torch.tensor(all_hp, dtype=torch.float, device=D),
            "status_ids": torch.tensor(all_status, dtype=torch.long, device=D),
            "boost_values": torch.tensor(all_boosts, dtype=torch.float, device=D),
            "item_ids": torch.tensor(all_item_ids, dtype=torch.long, device=D),
            "ability_ids": torch.tensor(all_ability_ids, dtype=torch.long, device=D),
            "mega_flags": torch.tensor(all_mega, dtype=torch.float, device=D),
            "alive_flags": torch.tensor(all_alive, dtype=torch.float, device=D),
            "move_ids": torch.tensor(all_move_ids, dtype=torch.long, device=D),
            "species_features": torch.stack(all_sp_feat).to(D),
            "move_features": torch.stack(all_mv_feat).to(D),
            "item_features": torch.stack(all_it_feat).to(D),
            "ability_features": torch.stack(all_ab_feat).to(D),
            "move_confidences": torch.tensor(all_mv_conf, dtype=torch.float, device=D),
            "item_confidences": torch.tensor(all_it_conf, dtype=torch.float, device=D),
            "ability_confidences": torch.tensor(all_ab_conf, dtype=torch.float, device=D),
            "weather_id": torch.tensor(all_weather, dtype=torch.long, device=D),
            "terrain_id": torch.tensor(all_terrain, dtype=torch.long, device=D),
            "trick_room": torch.tensor(all_tr, dtype=torch.float, device=D),
            "tailwind_own": torch.tensor(all_tw_own, dtype=torch.float, device=D),
            "tailwind_opp": torch.tensor(all_tw_opp, dtype=torch.float, device=D),
            "screens_own": torch.tensor(all_sc_own, dtype=torch.float, device=D),
            "screens_opp": torch.tensor(all_sc_opp, dtype=torch.float, device=D),
            "turn": torch.tensor(all_turn, dtype=torch.float, device=D),
            "action_mask_a": torch.ones(N, MAX_ACTIONS, dtype=torch.bool, device=D),
            "action_mask_b": torch.ones(N, MAX_ACTIONS, dtype=torch.bool, device=D),
        }
