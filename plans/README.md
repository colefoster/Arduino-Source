# Plans

Design docs and implementation plans for Pokemon Champions work. Higher-level architecture lives in [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

| File | What it is |
|---|---|
| [`search_engine.md`](search_engine.md) | Implementation plan for the `POST /search` MCTS 1-ply endpoint (action model + sim + winrate). **Built; current lift -0.4%, encoding fix needed.** |
| [`sim_v2_improvements.md`](sim_v2_improvements.md) | Format-specific battle sim improvements (Fairy Aura, type-boost items, Intimidate, etc.). **Largely landed; 81 sim tests passing.** |
| [`test_image_architecture.md`](test_image_architecture.md) | PRD for the screen-based `test_images/` overhaul (manifest.json labels, screens.yaml). **Shipped 2026-04-28.** |
| [`test_image_architecture_plan.md`](test_image_architecture_plan.md) | Implementation plan for the PRD above. Tracks GitHub issue PokemonAutomation/Arduino-Source#1219. |
| [`../docs/model-v2-plan.md`](../docs/model-v2-plan.md) | Action model v2 architecture rationale (LSTM history + transformer). **Shipped: v2_seq at 68.7% top-1.** |
