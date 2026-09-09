# Manual-upload academic handbook

Use `academic_handbook_100_pages.pdf` as the primary local ingestion sample in
place of the earlier two-page demo documents. This is an actual 100-page fictional
handbook with ten sections, bookmarks, numbered clauses and page labels.

The sections cover attendance, examinations, internal assessment, condonation,
hostel, library, fees, discipline, IT/laboratory rules and miscellaneous academics.
It is demonstration data, not an official institution policy.

After `python -m alembic upgrade head`, upload through Admin using:

- Policy name: `Academic Handbook (100-page DEMO)`
- Version: `2026-DEMO`
- File: `samples/policies/academic_handbook_100_pages.pdf`

The documented local login is `admin@example.edu` / `change-me` when configured
in the ignored local `.env`. Keep Ollama running. Review the extracted ordinary
attendance threshold against the source: **85 percent**, with discretionary
condonation from **80 percent** and a separate **16/40** internal-assessment rule.
The calculator still handles ordinary attendance only; a long mixed-topic prompt
may need manual review because rule extraction is unchanged.

Existing database sample versions were preserved. This file has not been
automatically uploaded to the live app, so the first manual upload can use the
name/version above. Later identical name/version uploads correctly return 409.

Regenerate from the repository root:

```sh
python scripts/generate_large_policy_sample.py
```

See `docs/source_persistence.md` for stored lineage, tests and the remaining
SQL/vector rollback issue.
