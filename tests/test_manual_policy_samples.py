"""Validate the delivered PDFs through RuleShift's production parser."""
import json
from pathlib import Path
import re

import pytest

from services.pdf_service import extract_pdf_pages

ROOT = Path(__file__).resolve().parents[1] / 'samples/policies'


@pytest.mark.parametrize('count,attendance,marks,condonation,late,visitor,books,days', [
    (50, 75, (16,40), 70, 30, '20:00', 4, 14),
    (75, 80, (20,50), 75, 20, '19:30', 5, 21),
    (100, 85, (24,60), 80, 15, '19:00', 6, 28),
])
def test_manual_sample_pages_unique_cases_and_known_facts(count, attendance, marks, condonation, late, visitor, books, days):
    filename = f'academic_policy_{count}_pages.pdf'
    pdf = (ROOT / filename).read_bytes()
    assert len(pdf) < 10 * 1024 * 1024
    pages = extract_pdf_pages(pdf)
    assert len(pages) == count
    assert [p['page_number'] for p in pages] == list(range(1,count+1))
    assert all(p['text'] for p in pages)
    texts = [' '.join(p['text'].split()) for p in pages]
    cases = [re.search(r'Worked review case\. (.*?)\. The ', t).group(1) for t in texts]
    assert len(set(cases)) == count, 'Pages must have distinct substantive worked cases'
    manifest = json.loads((ROOT/'manual_test_facts.json').read_text())[filename]
    assert manifest['pages'] == count
    for topic, fact in manifest['facts'].items():
        source = texts[fact['page']-1]
        assert topic in source
        assert fact['fact'] in source
    fulltext = ' '.join(texts)
    for expected in [
        f'ordinary minimum attendance is {attendance} percent',
        f'internal assessment minimum is {marks[0]} marks out of {marks[1]}',
        f'from {condonation} percent to below {attendance} percent attendance',
        f'entry closes {late} minutes',
        f'visitors must leave by {visitor}',
        f'borrow {books} books for {days} calendar days',
    ]:
        assert expected in fulltext
    # Version-specific source facts must not accidentally inherit another edition.
    for other in (75,80,85):
        if other != attendance:
            assert f'ordinary minimum attendance is {other} percent' not in fulltext
