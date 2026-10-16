# What-If card

## Sub-features

- On goals, big chances, and red cards, 200 seeded rollouts compare before, after, and the counterfactual. The fan view keeps the latest card.

## How to get to it (user POV)

Watch a replay past the first goal (seed 7 scores early in the first half).

## Driving it with Playwright

Wait for `.casual .whatif` (up to 240 s). It shows `Probabilidad de victoria · 200 simulaciones` in Spanish.

## Gotchas

- Rollouts run in a process pool. The first card is slower while workers spawn.
