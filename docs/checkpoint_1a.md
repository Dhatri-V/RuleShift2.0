# Checkpoint 1A: authoritative core persistence

This checkpoint adds PolicyFamily, PolicyVersion, Clause, and Rule only.
Validation issues, review records, index generations, and audit events are not
implemented here. Uploads do not yet persist PDFs or clauses; that is checkpoint 2.
Publication is **not yet trustworthy**: the later validation/review/publication
checkpoints must enforce provenance gates before this is release-ready.

## Schema and compatibility

- PolicyFamily owns its name. Version labels are unique within a family.
- PolicyVersion replaces the old policies table while preserving version IDs.
  `Policy` is a compatibility alias for the same mapped class; `Policy.name`
  reads/queries the family name. There is no duplicate policy table.
- The existing API's attendance_requirement column remains transitional. Existing
  API edits still update that column. The migrated legacy Rule value is an
  explicitly unverified snapshot of the pre-migration value, not an approved rule
  or a second active evaluator. Switching API writes/evaluation to Rule is later work.
- Every version defaults to requires_source_reingestion=true. Migration preserves
  old lifecycle status but does not equate VERIFIED/CURRENT with proven source
  lineage. Later publication and public-read gates must honor this flag.
- Each Clause belongs to one version and stores one-based page number, exact
  source text, optional clause label, and half-open Unicode character offsets
  into extracted page text. Database constraints check positive pages, offset
  length, and unique page/start positions. Checking against the actual stored
  page/PDF requires the ingestion implementation in checkpoint 2.
- Rule references a Clause through a composite foreign key that prevents a
  foreign-version source. Only legacy_unverified rules may lack a source.
  Attendance is the only rule type; numeric domain validation is checkpoint 3.
- An optional explicit predecessor must belong to the same family and cannot be
  the version itself. Migration does not infer predecessors from labels/dates.
  Cycle detection and publication transition checks remain later work.
- A partial unique index enforces at most one CURRENT per family. SQLite foreign
  keys are enabled on app, migration, and test connections. Referenced records
  cannot be silently deleted; existing draft deletion removes source-free legacy
  rules explicitly. Deletion of sourced drafts needs the later ingestion lifecycle.

## Migration and legacy preservation

Back up the existing database before upgrading. With dependencies installed,
from the repository root use the intended DATABASE_URL:

```sh
python -m alembic upgrade head
```

Migration 0002_core groups exact existing policy names into families and preserves
all IDs, labels, statuses, and attendance values (including null/out-of-range
legacy values). Each legacy row gets an unverified source-free Rule and a version
requiring source reingestion. No PDF, clause, approval, or supersession lineage is
fabricated. Existing status does not establish trust.

Multiple CURRENT rows for one family or unknown statuses stop migration with an
explicit reconciliation error. SQLite migration DDL/backfill runs in an explicit
transaction: failures preserve the original schema and data. Reconcile conflicts
only after reviewing the real records; do not guess or discard records.

An unversioned database that already has a policies table must first be checked
against revision 0001_initial and backed up before an operator stamps that
baseline. Do not run the initial create-table migration blindly on it.

A legacy-only downgrade to 0001_initial restores the old rows losslessly. A
schema containing new source clauses or relationships that cannot be represented
by the old schema refuses downgrade; restore the backup instead. Do not use
downgrade-to-base on a database whose data must be retained.

## Tests

```sh
python -m pytest -q tests/test_authoritative_models.py tests/test_authoritative_migration.py

# Full suite: isolate the working directory from existing Chroma data.
RULESHIFT_REPO="$(pwd)"
RULESHIFT_TEST_DIR="$(mktemp -d)"
(cd "$RULESHIFT_TEST_DIR" && PYTHONPATH="$RULESHIFT_REPO" python -m pytest -q "$RULESHIFT_REPO/tests")
```

Tests cover blank/populated migration, legacy round trips, transactional rollback
including a failure after DDL, migration/ORM schema parity, source relationships,
foreign keys, uniqueness, source span constraints, and compatibility API operations
against a migrated database. They use temporary or in-memory databases and never
migrate the repository's ruleshift.db.

Two pre-existing deletion tests use the default working-directory Chroma store.
Run the full suite from a disposable working directory as above; running it in
the repository can touch local Chroma data or fail when that data is read-only.
The new core-model/migration tests themselves use temporary databases exclusively.
