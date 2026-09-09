from fastapi.testclient import TestClient
from backend.main import app, get_database


def test_health_and_root_work_without_database():
    def unavailable_database():
        raise RuntimeError('Database unavailable')
    app.dependency_overrides[get_database] = unavailable_database
    try:
        with TestClient(app) as client:
            assert client.get('/health').status_code == 200
            assert client.get('/health').json() == {'status': 'ok'}
            assert client.get('/').json() == {'message': 'RuleShift API is running'}
    finally:
        app.dependency_overrides.pop(get_database, None)


def test_vite_cors_health_and_authenticated_upload_preflight():
    with TestClient(app) as client:
        response = client.get('/health', headers={'Origin': 'http://localhost:5173'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
        response = client.options('/policies/upload', headers={
            'Origin': 'http://localhost:5173',
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'authorization,content-type',
        })
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
