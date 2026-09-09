> Historical verification baseline. Stable chunk ownership, Clause persistence and PDF source evidence are now implemented; see `docs/source_persistence.md` for current results. The SQL/vector rollback failure remains open.

# Large mixed-content PDF ingestion verification

## Conclusion

The existing parser and chunker preserve all extractable text and original page
numbers in the tested 50-, 75-, and 100-page documents. Unrelated sections do not
break the tested parsing, segmentation, or index-write path.

**Overall authoritative-ingestion acceptance: FAIL.** This is a verification task,
not the implementation of the pending source-persistence checkpoint. Successful
upload does not prove immutable evidence, stable ownership metadata, clause
persistence, atomic rollback, or reliable whole-document rule extraction.

Only `tests/test_large_pdf_ingestion.py` and this document are added. Production
parser, upload handler, RAG, rule extraction, schema, UI and deployment are unchanged.
Tests use isolated databases/indexes; no live policies are uploaded or modified.

## Pipeline evidence

- `services/pdf_service.py:8` / `:34`: PyMuPDF opens PDF bytes and calls
  `page.get_text("text", sort=True).strip()` separately for each page. Enumeration
  starts at 1. Blank and graphics-only pages remain in the returned list.
- `backend/main.py:213`: the entire upload is read into memory before checking the
  byte limit (10 MiB default). There is no document-page-count or extracted-text
  budget. These fixtures fit the current byte limit; this is not a resource-abuse
  or arbitrary-PDF safety certification.
- `backend/main.py:269`: all nonempty pages, with original page labels, are joined
  into one rule-extraction prompt. `ai/extraction.py` asks for a single attendance
  value. No topic-aware multi-rule extraction or prompt-length guard exists.
- `ai/rag.py:26`: each nonempty page becomes a separate Document before splitting
  at 800 characters with 100-character overlap. This is character-based chunking,
  not semantic or authoritative clause segmentation.
- `ai/rag.py:34`: metadata contains `policy_name`, the `version` label and
  `page_number`; content is `page_content`. It does not contain `policy_id`,
  `version_id`, a source-file identity/hash, a clause ID or source offsets.
- `backend/main.py:288` writes the index before creating/committing the version
  at `:292` / `:300`. A failed SQL commit returns 409 without removing chunks.
- `database/models.py:96` defines Clause, but the upload handler creates none.
  `requires_source_reingestion` remains true by default. Uploaded PDF bytes are
  not durably stored or hashed by this path. Existing checkpoint documentation
  explicitly leaves that implementation for the source-persistence checkpoint.

Terminology: PolicyFamily is the logical policy owner; PolicyVersion.id is the
legacy API `id`. Human-readable policy names/version labels are not substitutes
for stable numeric ownership IDs.

## Reproducible fixtures and test boundaries

PDFs are generated in memory with the project's existing PyMuPDF dependency;
there are no binary fixtures or new dependencies. Each text page contains six
numbered clauses, a reference table, and unique page/clause markers. Topics cycle
through attendance, library, internal assessment, laboratory safety, hostel,
finance, research ethics and IT acceptable use. Every 17th page is blank and
every 23rd page contains graphics without text.

| PDF pages | PDF bytes | Nonempty text pages | Extracted characters | Chunks |
| --- | ---: | ---: | ---: | ---: |
| 50 | 52,877 | 46 | 114,990 | 184 |
| 75 | 78,219 | 68 | 170,002 | 272 |
| 100 | 104,530 | 91 | 227,522 | 364 |

These are dense synthetic academic-policy fixtures, not merely repeated page
titles. Authored text is independently compared to extracted text with whitespace
normalization. Every chunk must be an exact substring of its indicated page;
coverage assertions require every non-whitespace source character to survive.
The last page, every text-bearing page and all eight topics are checked.

Upload tests use the real authenticated FastAPI handler, parser, splitter,
temporary SQLite and real Chroma persistence. Only rule extraction and embeddings
are deterministic doubles. Tests verify counts, stored content/metadata, version
ownership in SQL, duplicate rejection without index changes, and clean failure
before indexing when rule extraction raises. They also check that the complete
document is passed to rule extraction; they do not claim the model can accurately
process that prompt. No retrieval/answer-generation behavior is changed or tested
as part of the new suite.

## Acceptance criteria

| Criterion | Result |
| --- | --- |
| Page-by-page extraction at 50/75/100 pages | PASS |
| Original numbering across blank and graphics-only pages | PASS |
| All unrelated topic text survives segmentation and index storage | PASS |
| Exact chunk text, policy name, version label and page metadata | PASS |
| Stable policy_id and version_id on chunks | FAIL: missing |
| Authoritative per-version clauses with source spans | FAIL: no rows created |
| Immutable PDF identity/hash linking persisted evidence | FAIL: not implemented |
| Duplicate name/version rejection leaves the existing index unchanged | PASS |
| Extraction failure before indexing leaves no policy/index data | PASS |
| SQL commit failure rolls back newly indexed chunks | FAIL: 364 orphan chunks |
| Real model accuracy/context handling for a mixed 100-page document | NOT VERIFIED |

## Results and reproduction

- New suite: **12 passed, 3 xfailed**, 24 warnings, 21.33 seconds.
- Explicit acceptance probe (`--runxfail`): **3 failed**, 12 deselected, 8.49 seconds.
- Full backend regression suite after the final test edit: **268 passed, 3 xfailed**,
  108 warnings, 24.78 seconds. All 256 previously passing backend tests still pass.
- No frontend changes; frontend tests/build were not rerun for this task.

The new suite has 12 passing checks (four checks at each document size) and three
strict expected failures documenting missing guarantees. They are marked
`xfail(strict=True, raises=AssertionError)`: unexpected runtime errors fail, and
an unexpectedly passing contract also requires review. These marks are not an
acceptance waiver. Running the three contracts with `--runxfail` produces three
actual failures: absent IDs, zero clauses, and 364 orphaned chunks respectively.

Run tests from a disposable working directory, because some existing deletion
tests otherwise use the working directory's Chroma data:

```sh
RULESHIFT_REPO=/Users/dhatriv/Documents/RuleShift2.0
RULESHIFT_TEST_DIR=$(mktemp -d)
cd "$RULESHIFT_TEST_DIR"
PYTHONPATH="$RULESHIFT_REPO" python -m pytest -q -rxX "$RULESHIFT_REPO/tests/test_large_pdf_ingestion.py"
PYTHONPATH="$RULESHIFT_REPO" python -m pytest -q --runxfail --tb=short "$RULESHIFT_REPO/tests/test_large_pdf_ingestion.py" -k 'authoritative or failed_commit'
PYTHONPATH="$RULESHIFT_REPO" python -m pytest -q -rxX "$RULESHIFT_REPO/tests"
```

The `--runxfail` command intentionally exits nonzero until the missing production
guarantees are implemented. Existing dependency deprecations and short JWT-secret
warnings from test fixtures are unrelated to large-PDF ingestion.

## Limitations and follow-up boundary

Do not describe the system as safe authoritative ingestion merely because this
size test passes. Source persistence, stable index ownership and safe cross-store
rollback remain necessary. Rule extraction still consumes one potentially large,
mixed-topic prompt; local-model truncation and semantic errors are outside this
verification. Image-only/scanned content requires OCR and remains unsupported;
tables are flattened text, not preserved table structure. No general guarantees
are made for complex layouts, arbitrary Unicode fonts, encrypted files, much
larger uploads, concurrent failures or process crashes.

No production fixes, later checkpoints, commits or pushes are included in this task.
