# Civ3 Conquests Trainer

Single-player trainer for *Civilization III: Conquests* (Steam v1.22, with or without the C3X mod).
Pure Python (3.8+), no extra packages.

## Use

1. Start Conquests and load or start a game.
2. `python civ3_trainer.py` (run as administrator if attaching fails).
3. Pick your civilization (pre-selected) and use the buttons.

`python civ3_trainer.py --dump` prints what the trainer reads from the game (handy for debugging).

## Features

| Feature | How it works |
|---|---|
| Gold: set / +1,000 / +10,000 / lock | Treasury is stored as `Gold_Encoded + Gold_Decrement`; the trainer rewrites `Gold_Encoded`. |
| Complete research | Fills the current research's beakers and sets "turns spent" (Leader +0x100) to 100, past Civ3's minimum research time (4 turns), so the game finishes the tech at the end of the turn with all normal side effects. |
| Finish production | Sets each city's shield box (City +0x44) to the cost of its current build. The cost is computed like the game's `City_get_order_cost` (0x4B3D30): cost factor, trait discount, Palace scaling. |
| Fill food boxes | Sets each city's stored food (City +0x40) to its food box size (City +0x244), so it grows at end of turn. |
| Full movement | Sets unit `Moves` used (Unit +0x50) to 0. |
| Golden age | Sets `Golden_Age_End` (Leader +0x3C) to current turn + remaining + 20. |

## Memory layout (Steam build, image base 0x400000, no ASLR)

| What | Address / offset |
|---|---|
| `leaders[32]` (Leader structs) | `0xA75698`, struct size detected at runtime |
| Human player bitmask | `0xA74EB4` |
| BIC rules data | `0x9E5D08` (AdvanceCount at +0x8B4) |
| Leader: Gold_Decrement / Gold_Encoded | +0x44 / +0x48 |
| Leader: Research_Bulbs / Current_Research_ID | +0xF8 / +0xFC |

Source: the [C3X](https://github.com/maxpetul/C3X) project's reverse-engineering notes (`source/civ_prog_objects.csv`,
`source/Civ3Conquests.h`), verified against the game's code (`Leader_has_tech` at `0x56D5A0`).
