# Checkpoint 1B: supporting persistence

Scope: schema/ORM support for validation findings, rule review metadata, index
generation metadata, and audit events. No API handlers, publication gates,
supersession logic, frontend workflows, validators, index rebuilds, or PDF
persistence are implemented by this checkpoint.

## Records

- **ValidationIssue** belongs to a version and optionally a rule/clause of that
  same version. Stores code, validator identifier, message, severity, blocking
  flag, creation time, and OPEN/RESOLVED status. Resolution requires actor,
  timestamp, and explanation; unresolved records cannot contain resolution metadata.
- **RuleReview** is optional, one-to-one latest metadata for a rule. Stores
  PENDING_REVIEW/APPROVED/REJECTED/NON_EXECUTABLE status and, for decisions,
  reviewer ID, timestamp, reason, and a rule snapshot. There is no user table yet;
  actor/reviewer identifiers are strings. No row means no recorded review.
  This record does not approve a rule for execution. Transition authorization,
  approval invalidation after edits, snapshot checking, and review history through
  audit events belong to the later review service.
- **IndexGeneration** stores a per-version generation number, status, collection,
  embedding model identifier, chunking configuration, expected/observed chunk
  counts, optional manifest SHA-256, failure detail, and timestamps. Counts must
  be nonnegative integers. Generations are unique within a version. Counts may
  differ to record a failed attempt. READY is stored metadata, not independently
  verified index readiness. No active-index pointer, chunk manifest rows, Chroma
  calls, rebuild command, or activation behavior exists here.
- **AuditEvent** records family, optional version/rule/clause, actor kind and ID,
  action, reason, before/after JSON, correlation ID, and occurrence time. Composite
  foreign keys reject wrong-family/wrong-version targets. SQLite triggers reject
  UPDATE, DELETE, and replacement of an existing event ID, including raw SQL.
  These are append-only database records, not a tamper-proof external ledger:
  an operator with database ownership can remove triggers or restore a database.

Timestamps use UTC (SQLite CURRENT_TIMESTAMP, returned as naive UTC datetimes).
JSON fields are snapshots/configuration, not executable rules. Replace JSON
values as a whole when updating mutable records; in-place nested JSON mutation is
not tracked. Later services must construct validated/redacted payloads without
passwords, tokens, full profiles, or provider credentials. No automatic audit
emission, secret redaction, or side effects are attached to existing API calls.

## Relationships and transactions

Supporting rows use restrictive foreign keys so referenced source/core records
are not silently discarded. The new unique composite index rules(version_id,id)
enables rule/version ownership checks without rebuilding or rewriting rules.
Application-level deletion behavior for newly referenced records is later work.
All supporting records participate in normal SQLAlchemy transactions. Audit inserts
can commit/roll back with business mutations; this checkpoint does not wire those
inserts into mutation endpoints or enforce that an event accompanies every mutation.

## Migration

Revision 0003_supporting follows 0002_core. Upgrade adds four empty tables, lookup
indexes, the composite rule index, and three audit triggers. Existing families,
versions, clauses, rules, IDs, statuses, and provenance flags are unchanged. It
never fabricates past validation results, approvals, index generations, or events.
Back up the chosen database before applying `python -m alembic upgrade head`.

SQLite is the supported/tested database. Hash/integer constraints and audit
triggers are SQLite-specific; PostgreSQL migration requires separate implementation.
Migrations are tested on empty and populated temporary databases, including a
failed migration after DDL. The explicit SQLite transaction from 1A makes upgrade
failure roll back the whole change. Online downgrade to 0002_core succeeds only
when all supporting tables are empty; otherwise it refuses data loss. Offline
downgrade is refused because the data-preservation check requires live reads.
The 1A migration tests now expect the new head schema; their preservation and
rollback assertions remain in place.

## Verification commands

With the project Python environment activated, run from the repository root:

```sh
python -m pytest -q tests/test_supporting_models.py tests/test_supporting_migration.py
RULESHIFT_REPO="$(pwd)"
RULESHIFT_TEST_DIR="$(mktemp -d)"
(cd "$RULESHIFT_TEST_DIR" && PYTHONPATH="$RULESHIFT_REPO" python -m pytest -q "$RULESHIFT_REPO/tests")
```

The scratch working directory prevents pre-existing deletion tests from using the
local Chroma store. The new persistence tests use temporary/in-memory databases.
Run frontend regression tests and the production build in an isolated frontend
copy with the installed dependencies: `npm test` and `npm run build`.
