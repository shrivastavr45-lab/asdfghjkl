from fastapi.testclient import TestClient

from app.main import app
from app.services.elexon_client import ElexonAPIError

client = TestClient(app)


def test_health():
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'
    assert response.json()['data_mode'] == 'live-elexon-only'


def test_dates_restrict_to_january_2026():
    payload = client.get('/api/dates').json()
    assert len(payload['dates']) == 31
    assert payload['dates'][0] == '2026-01-01'
    assert payload['dates'][-1] == '2026-01-31'


def test_invalid_date_is_rejected():
    response = client.get('/api/analysis?date=2026-02-01&cutoff_time=16:00')
    assert response.status_code == 422


def test_invalid_cutoff_is_rejected():
    response = client.get('/api/analysis?date=2026-01-14&cutoff_time=25:99')
    assert response.status_code == 422


def test_elexon_failure_returns_502_without_sample_data(monkeypatch):
    def fail(*args, **kwargs):
        raise ElexonAPIError("Elexon is unavailable in this test.")
    monkeypatch.setattr('app.api.routes.get_analysis', fail)
    response = client.get('/api/analysis?date=2026-01-14&cutoff_time=16:00')
    assert response.status_code == 502
    assert response.json()['detail'] == 'Elexon is unavailable in this test.'
