# RuleShift implementation status

Updated: 2026-09-13

## Complete for the attendance release

- Immutable uploaded PDF bytes and SHA-256 identity
- 1-based page extraction, immutable source pages, and exact clause spans
- Stable policy-family, version, clause, and vector ownership metadata
- Source-backed attendance verification; source-free and mismatched rules fail closed
- Blocking-validation and vector-count checks before current promotion
- Safe same-family supersession with explicit predecessor lineage
- Compensating deletion of Chroma chunks after failed SQL commit
- Isolated vector storage in tests and a SQLite-authoritative rebuild command
- Public exclusion of DRAFT versions and authenticated admin catalogue
- SQL current-version resolution for omitted-version Ask
- Exact historical version isolation for explicitly selected reviewed versions
- Structured RAG evidence, conflict state, primary citations, and numeric-claim guard
- Numeric-aware same-family chronological comparison enforced by frontend and backend
- Deterministic attendance impact with durable old/new evidence
- Immutable persisted impact snapshots
- Admin login, protected mutations, logout, source review, publication, and audit history
- Real 50/75/100-page ingestion tests
- Labelled attendance regression evaluation and generated report

## Intentional release limits

- Executable rules cover ordinary minimum attendance percentages only.
- No generic scholarship, examination, placement, fee, deadline, exception, or compound-condition engine.
- No OCR for scanned PDFs.
- No background processing queue or provider retry across restarts.
- No saved student identity or cross-user profile system; impact checks are anonymous.
- Local SQLite and Chroma support one application instance.
- No Docker packaging in this release.

## Future extensions

- Typed multi-domain rule DSL and tri-state missing-data evaluation
- Clause alignment and reviewed semantic change classifications
- Background ingestion jobs with progress and durable retry
- OCR and table extraction
- Multi-user administrator records with password hashing
- PostgreSQL/object storage/shared vector service for multi-instance deployment
- Larger institution-labelled evaluation datasets
