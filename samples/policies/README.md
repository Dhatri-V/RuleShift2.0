# Large PDFs for manual testing

The manual-upload documents are fictional academic policies with ten topics:
attendance, examinations, internal assessment, condonation, fees, hostel,
library, discipline, IT/laboratory and miscellaneous academic procedures.
Each page has a distinct procedure and worked case. Nothing is uploaded by the
generator. Upload these files yourself through the Admin UI.

| File | Pages | Suggested version | Attendance | Internal marks | Medical condonation |
|---|---:|---|---|---|---|
| academic_policy_50_pages.pdf | 50 | 2025-50 | 75% | 16/40 | 70% to below 75%, department approval |
| academic_policy_75_pages.pdf | 75 | 2026-75 | 80% | 20/50 | 75% to below 80%, Dean approval |
| academic_policy_100_pages.pdf | 100 | 2027-100 | 85% | 24/60 | 80% to below 85%, Academic Board approval |

Use the same policy name, `Academic Policy Manual Test`, with the different
versions above to test version comparison. Review extracted values before
verification: the existing large-document rule extraction can truncate its LLM
input and produce an incorrect attendance threshold. The impact calculator
currently evaluates ordinary attendance only.

`manual_test_facts.json` contains ground-truth facts and exact physical page
numbers for each document. Library limits are respectively 4 books/14 days,
5 books/21 days and 6 books/28 days; hostel visitor departure times are 20:00,
19:30 and 19:00. Examination entry closes after 30, 20 and 15 minutes.

Regenerate the three manual documents and fact sheet with:

```sh
python scripts/generate_manual_policy_samples.py
```

`academic_handbook_100_pages.pdf` is retained only because the source-persistence
regression test requires it. It is not one of the recommended manual uploads.
No obsolete tiny PDF is present in this directory.
