# NOVA Doctor + preserved BM25 v2 candidate

Local review candidate, 2026-10-15. No upload or leaderboard evaluation performed.

The original index is preserved byte for byte. Source document titles, issuers,
URLs (where provided), hashes, license labels and review status remain embedded
in its records/source_metadata. This is supplied reference material, never the
current patient's history or test results. Coding cases are not universal rules.

The index contains INTERNAL_ONLY / external_redistribution_allowed=false metadata.
Permission for external submission/redistribution has not been established.
Structural ZIP validation is not a license clearance or an official build approval.
The two coding publications have original llm_processing_allowed=false with
LATEST_REVISION_LISTING_CONFIRMATION_REQUIRED. Generating code and the separate
research_usage_policy.json identify this as an internal extraction/version gate,
not an identified publisher prohibition. The user authorizes project case-based
reasoning. assets/research_policy.json permits that scoped research use while
preserving all original flags and review history. External submission remains
UNCONFIRMED; project authorization does not grant publisher rights. Confirmed
publisher prohibitions and unclassified restriction flags are not overridden.

assets/evidence_units.json records intact source units and original locations.
No patient fact is inferred from the reference cases. A source-case association
is never labeled a universal or definitive diagnostic rule.

SDK: unmodified nova_sdk.py 1.0.1 from https://nova.snubhai.org/docs/starter.zip.
No dependency packages, model weights, development key, patient scripts, gold
answers, test fixtures or evaluation questions are included in this candidate.

Entry point: run.py -> official run_agent(prepare, consult).
The official environment supplies NOVA_API_BASE / NOVA_RUN_TOKEN / NOVA_SESSION_ID.
For local testing and development-key setup use the parent project's README.md.
