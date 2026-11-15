# Contextual advertising agent network

Each slot has an independent placement strategist → copywriter → independent critic → optional rewrite → TTS workflow. Up to three slot workflows run concurrently. Each model client owns its instructions and schema; live clients do not patch shared prompts. Stock/custom TTS retains its provider queue and permission checks.

The strategist receives the last 200 available words before the cut, all selected businesses that pass profile exclusions, and retrieved earlier passages for stance checks. It compares businesses semantically rather than committing to a keyword-ranked advertiser, and may return no ad. The exact callback citation must match a preceding source. Short episode openings use the available text without inventing context. Earlier retrieval is selective rather than a guarantee of exhaustive episode-wide stance detection.

The copywriter writes 110–140 spoken words, aiming at 130, with one creative idea, natural pause cues and a supplied CTA. Account/subscription flags remain internal eligibility metadata. Copy cannot imply free access or invent offers. Old short seed ads are excluded from the new writing policy. Prompts and context changes invalidate creative/session caches, while audio transcription and reviewed break analysis remain reusable.

Local validation can request one repair. The independent critic can send one editorial revision back to the writer. Rejected or uncertain copy never reaches TTS. The bounded loop can still fail or choose no ad rather than force a bad placement.

Selection comparisons are cached under `cache/live/selections`; writer/critic traces are beside creative entries as `agent_trace.json`; sessions record the network's concurrency and per-slot selection reasoning. The UI exposes this under **Why this business**.

Tests cover the preceding-word window, absence of future text, concurrent strategist execution, isolated writer instructions, bounded validation repair, and existing cache behavior. `check_parallel_network.py` exercises three slots with real APIs against the cached uploaded episode.
