# Uploaded-version ownership and source persistence

Implemented scope: stable chunk ownership, authoritative source segments and
original PDF evidence for new uploads. Retrieval, answer generation, rule
extraction, frontend and deployment are unchanged. This does not complete the
remaining publication or cross-store rollback checkpoints.

## Ownership and lineage

- `SourceDocument` is keyed by `PolicyVersion.id` and stores `policy_id` (the
  owning PolicyFamily), original PDF bytes, SHA-256, byte/page counts and parser
  identity. A composite foreign key enforces the correct policy/version pair.
- `SourcePage` is keyed by `(version_id, page_number)` and stores the exact
  PyMuPDF text used during ingestion, including empty pages. PDF bytes are held
  as a SQLite BLOB; no user filename is used as a storage path and there is no
  publicly mounted upload directory.
- Existing `Clause` rows now hold every indexed source segment: stable integer
  primary key, version foreign key, original page number, source text, and
  half-open Unicode character offsets into SourcePage text. `Clause.policy_id`
  resolves through its version's persisted family relationship, avoiding a
  duplicated owner field that could disagree. Clauses are source segments,
  not an assertion of semantic boundaries or executable/approved rules.
- Every chunk produced by the upload endpoint contains `policy_id`, `version_id`,
  `clause_id`, `page_number`, `start_offset`, `end_offset`, `source_sha256`, and the
  existing policy name/version labels. Its document content exactly equals the
  persisted clause text and its indicated page slice. Chroma IDs use
  `clause:<source_sha256>:<version_id>:<clause_id>`.
- The existing 800-character / 100-character-overlap splitter is retained;
  start-offset tracking is added without changing retrieval filters or prompts.
  The ingestion service persists the exact segments before handing those same
  segments to indexing. Uploaded source lineage is checked before index writes.
- SQLite triggers reject UPDATE and INSERT OR REPLACE of existing PDF/page
  records, including raw SQL writes. An authorised draft deletion can remove the
  complete source and its clauses. No source-edit endpoint is introduced.
- Successful new uploads set `requires_source_reingestion=False`. This means
  source evidence exists; it does not imply valid rules or publication approval.

## Migration and compatibility

Migration `0004_source` follows `0003_supporting`. It adds `source_documents`,
`source_pages`, constraints and four immutable-record triggers. Core/supporting
rows, IDs and lifecycle states remain unchanged. No legacy source evidence is
fabricated. Existing uploaded policies and their old Chroma chunks must be
explicitly reingested later to gain this metadata; the legacy standalone indexing
helper remains compatible with existing callers/tests.

The live local database was backed up before upgrading. All nine existing
versions and all preexisting table rows were checked unchanged after migration;
`PRAGMA foreign_key_check` returned no violations. Existing versions have no new
source records until reingestion. The local `/health` and `/policies` endpoints
both returned 200 after migration.

For another local checkout, run `python -m alembic upgrade head` before uploading.
The migration is SQLite-specific, consistent with the existing persistence
checkpoints. Downgrade refuses to discard source records; a failure during
migration rolls back its tables/triggers/revision. Empty-source downgrade is
covered by existing migration round-trip tests.

The draft-deletion handler now removes owned clauses/pages/PDF records so ordinary
uploaded drafts remain deletable. Existing restrictive references still prevent
deleting a clause used by another authoritative record.

## The actual 100-page sample

Project file: `samples/policies/academic_handbook_100_pages.pdf`

- Exactly 100 text-bearing A4 pages; 237,987 bytes; 252,883 extracted characters in the local parser runtime.
- Ten bookmarked sections: Attendance, Examinations, Internal Assessment,
  Condonation, Hostel, Library, Fees, Discipline, IT and Laboratory, and
  Miscellaneous Academic Policies.
- Each section contains ten numbered procedures, including application/evidence,
  decisions, appeals and record-retention text. Every page carries the fictional
  demonstration notice and its physical page number.
- Ordinary attendance minimum: 85 percent. Condonation: at least 80 but below 85,
  subject to recorded approval. Internal assessment minimum: 16 out of 40.
- SHA-256: `1f8346d344c97d3ed58c6c80bfe079ddca04db6a2a6b845fa50490d45fabf044`.

This becomes the recommended manual-upload sample instead of the earlier tiny
PDFs. It was not automatically uploaded to the live database and no existing
verified sample policy was deleted. The user can exercise the real UI flow:

1. Start the backend, Vite and the existing Ollama services.
2. In Admin, log in using the configured local account.
3. Choose the sample PDF, policy name `Academic Handbook (100-page DEMO)` and
   version `2026-DEMO`. Use a new version label for a deliberate later upload;
   duplicate policy-name/version combinations are rejected.
4. Upload and review the extracted ordinary attendance value against the PDF
   before verifying. The current model still receives the entire document in
   one prompt; reliable large-document rule extraction is not claimed here.

Regenerate the file with `python scripts/generate_large_policy_sample.py`.
This uses only the existing PyMuPDF dependency. Content/layout is reproducible;
PDF internal identifiers may change the file hash on regeneration. All 100 pages
were rendered and visually reviewed; representative pages were inspected at
readable resolution.

## Test results

- Large-PDF suite: **14 passing checks, 1 expected failure**. The former missing-ID
  and missing-Clause expected failures are now normal passing tests.
- Combined large-PDF and new source-persistence run (before the additional cross-policy constraint test): **25 passed, 1 xfailed**,
  48 warnings, 25.05 seconds.
- Full backend suite against the final implementation: **282 passed, 1 xfailed**,
  132 warnings, 29.77 seconds.
- No frontend changes; frontend tests/build were not rerun for this scope.

The new persistence tests cover exact PDF and clause/page round trips, immutable
source update/replace protection, distinct clause ownership for identical bytes
uploaded under different versions, indexing-failure SQL rollback, draft deletion,
legacy-preserving migrations, downgrade protection, injected migration failure,
and authenticated upload of the actual on-disk 100-page sample.

Tests use the real parser, chunker, SQLite and Chroma persistence. Rule extraction
and embeddings are deterministic doubles; successful tests do not certify live
Ollama throughput, context handling or semantic accuracy. Tests run from a clean
disposable directory, avoiding both module shadowing and the live Chroma store.

```sh
RULESHIFT_REPO=/Users/dhatriv/Documents/RuleShift2.0
RULESHIFT_TEST_DIR=$(mktemp -d)
cd "$RULESHIFT_TEST_DIR"
PYTHONPATH="$RULESHIFT_REPO" python -m pytest -q -rxX "$RULESHIFT_REPO/tests/test_large_pdf_ingestion.py" "$RULESHIFT_REPO/tests/test_source_persistence.py"
PYTHONPATH="$RULESHIFT_REPO" python -m pytest -q -rxX "$RULESHIFT_REPO/tests"
```

## Remaining acceptance failure

**SQL commit / vector rollback remains FAIL.** A commit failure after indexing
can leave orphaned Chroma chunks. The existing strict xfail still demonstrates
364 surviving chunks for the 100-page synthetic fixture. SQL source records roll
back, but vector compensation, crash recovery and cleanup are deferred as allowed
by the task. Partial vector-write failures also require that later work.

Whole-document rule extraction, semantic clause detection, old-index backfill,
OCR, and publication gates were not redesigned. Source evidence is now preserved
for successful new uploads; this is not a claim of complete end-to-end publication
trustworthiness. No commit or push was performed by the assistant.


## Files changed in this task

Modified:

- `backend/main.py`
- `ai/rag.py` (chunk metadata/write support only)
- `database/models.py`
- `tests/test_large_pdf_ingestion.py`
- `tests/test_upload_validation.py`
- `tests/test_authoritative_migration.py`
- `tests/test_supporting_migration.py`
- `docs/large_pdf_ingestion_verification.md` (marked as the historical baseline)

Added:

- `database/source_models.py`
- `services/source_service.py`
- `alembic/versions/0004_source_evidence.py`
- `tests/test_source_persistence.py`
- `scripts/generate_large_policy_sample.py`
- `samples/policies/academic_handbook_100_pages.pdf`
- `samples/policies/README.md`
- `docs/source_persistence.md`

Preexisting health-check/frontend changes remain untouched by this task, except
that the already-modified backend file also received the ingestion integration.
No Git commit or push command was run by the assistant.
