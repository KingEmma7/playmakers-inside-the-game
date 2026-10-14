# Gallery agents

A real Microsoft Agent Framework Director workflow with deterministic stats, verified
Tactics/Storyline insights, schema-validated graphics, audience shaping, recovery and
parallel seeded What-If continuations. Runs offline with no credentials.

```bash
python -m gallery_agents demo --seed 7 --speed 50 --kill tactics@20
python -m gallery_agents demo --speed 0 --limit 5 --kill tactics@0 --whatif-rollouts 20
```

See the root README's “How the agents work” section for contracts, checkpoint restoration,
viewer settings, streaming endpoints and Azure limitations.
