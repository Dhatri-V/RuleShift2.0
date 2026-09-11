"""The exact persisted 2026 upload matches the retained handbook fixture."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from core.attendance_source import attendance_provisions
from services.pdf_service import extract_pdf_pages
from services.rule_source import source_check, require_source_match


def policy(texts, value=75):
    return SimpleNamespace(attendance_requirement=value, source_document=SimpleNamespace(
        pages=[SimpleNamespace(page_number=i, source_text=text) for i,text in enumerate(texts,1)]))


def test_exact_2026_pdf_governing_rule_not_examples_or_condonation():
    pdf=(Path(__file__).resolve().parents[1]/"samples/policies/academic_handbook_100_pages.pdf").read_bytes()
    assert sha256(pdf).hexdigest()=="1f8346d344c97d3ed58c6c80bfe079ddca04db6a2a6b845fa50490d45fabf044"
    pages=extract_pdf_pages(pdf)
    record=policy([p['text'] for p in pages])
    result=source_check(record)
    assert result['status']=='MISMATCH'
    assert result['expected_value']==85
    assert [e['page_number'] for e in result['evidence']]==list(range(1,11))
    assert all(e['quote'].startswith('Students must maintain at least 85 percent attendance') for e in result['evidence'])
    assert all(not attendance_provisions(p['text']) for p in pages[30:40])
    with pytest.raises(HTTPException) as error: require_source_match(record)
    assert error.value.status_code==409
    record.attendance_requirement=85
    assert source_check(record)['status']=='MATCH'


@pytest.mark.parametrize('text',[
    'Students must maintain at least 85 percent attendance in each registered course to meet the ordinary examination attendance requirement.',
    '1.1.2 Governing requirement. Students must maintain at least 85 percent attendance in each\nregistered course to meet the ordinary examination attendance requirement.',
    'Students must maintain a minimum of 85% attendance in each course.',
])
def test_course_wide_normative_wording(text):
    assert [f['value'] for f in attendance_provisions(text)]==[85]


@pytest.mark.parametrize('text',[
    'A student at 80 percent does not meet the ordinary threshold. A student at 90 percent meets it.',
    'Medical condonation may be considered when course attendance is at least 80 percent but below the ordinary 85 percent requirement.',
    'Internal assessment requires 50 percent of the marks.',
    'Example: Students must maintain at least 75 percent attendance in each course.',
    '1.1.3 Worked example. The minimum attendance requirement is 75%.',
    'If approved for condonation, students must maintain at least 75 percent attendance in each course.',
])
def test_non_governing_percentages_do_not_establish_ordinary_requirement(text):
    assert attendance_provisions(text)==[]
    record=policy([text])
    assert source_check(record)['status']=='ABSENT'
    with pytest.raises(HTTPException): require_source_match(record)


def test_conflicting_governing_rules_remain_blocked_with_candidate_pages():
    record=policy(['The minimum attendance requirement is 80%.',
        'Students must maintain at least 85 percent attendance in each registered course.',
        'The minimum attendance requirement is 80%.'])
    result=source_check(record)
    assert result['status']=='AMBIGUOUS'
    assert result['candidates']==[{'value':80,'pages':[1,3]},{'value':85,'pages':[2]}]
    assert '80% (pages 1, 3)' in result['message'] and '85% (pages 2)' in result['message']
    with pytest.raises(HTTPException): require_source_match(record,85)


def test_2027_wording_still_matches():
    result=source_check(policy(['The minimum attendance requirement is 85% in each course.'],85))
    assert result['status']=='MATCH' and result['expected_value']==85
