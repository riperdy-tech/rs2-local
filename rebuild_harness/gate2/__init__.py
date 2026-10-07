"""Gate 2 (registration REGISTRATION_gate2_DRAFT.md, approved 2026-10-07): does Muse add information to the frozen code engine?

The replay runner, the sample drawer, the Muse server lifecycle, the GPU wait, the outcome extraction and the G1-G6 scoring.  Nothing in this package starts a
model or a server on import; the runner starts the pinned llama-server only when it is told to run (and the GPU is free).  The engine files are FROZEN at c7d7a4f and are
only imported.
"""
