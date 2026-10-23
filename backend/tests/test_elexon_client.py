from unittest.mock import Mock, patch

import pytest
import requests

from app.services.elexon_client import ElexonAPIError, _unwrap_rows, fetch_stream
from datetime import datetime, timezone


def test_stream_unwraps_documented_array():
    assert _unwrap_rows([{"generation": 1}], "FUELHH") == [{"generation": 1}]


def test_stream_unwraps_data_envelope():
    assert _unwrap_rows({"data": [{"generation": 1}]}, "WINDFOR") == [{"generation": 1}]


def test_stream_rejects_malformed_payload():
    with pytest.raises(ElexonAPIError):
        _unwrap_rows({"unexpected": []}, "FUELHH")


def test_api_timeout_is_explained():
    with patch('app.services.elexon_client.requests.get', side_effect=requests.Timeout()):
        with pytest.raises(ElexonAPIError, match='timed out'):
            fetch_stream('FUELHH', datetime(2026, 1, 14, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc))


def test_api_http_error_is_explained():
    response = Mock()
    response.status_code = 503
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    with patch('app.services.elexon_client.requests.get', return_value=response):
        with pytest.raises(ElexonAPIError, match='HTTP 503'):
            fetch_stream('WINDFOR', datetime(2026, 1, 14, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc))


def test_only_allowed_datasets_can_be_requested():
    with pytest.raises(ValueError):
        fetch_stream('OTHER', datetime(2026, 1, 14, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc))


def test_fuelhh_uses_publication_time_filters():
    from app.services.elexon_client import _dataset_params
    params = _dataset_params(
        'FUELHH',
        datetime(2026, 1, 14, tzinfo=timezone.utc),
        datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert params == {
        'publishDateTimeFrom': '2026-01-14T00:00:00Z',
        'publishDateTimeTo': '2026-01-15T00:00:00Z',
    }
    assert 'settlementDateFrom' not in params
    assert 'fuelType' not in params  # filter WIND locally from returned FUELHH rows


def test_day_actuals_uses_bounded_publication_revision_window():
    from datetime import date, timedelta
    from app.services.elexon_client import ACTUAL_REVISION_WINDOW_DAYS, fetch_day_actuals
    with patch('app.services.elexon_client.fetch_stream', return_value=[]) as fetch:
        assert fetch_day_actuals(date(2026, 1, 14)) == []
    args = fetch.call_args.args
    assert args[0] == 'FUELHH'
    assert args[1] == datetime(2026, 1, 14, tzinfo=timezone.utc)
    assert args[2] == datetime(2026, 1, 14, tzinfo=timezone.utc) + timedelta(days=ACTUAL_REVISION_WINDOW_DAYS + 1)


def test_windfor_uses_publication_time_filters():
    from app.services.elexon_client import _dataset_params
    params = _dataset_params(
        'WINDFOR',
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert params['publishDateTimeFrom'] == '2026-01-01T00:00:00Z'
    assert params['publishDateTimeTo'] == '2026-01-15T00:00:00Z'
    assert 'from' not in params and 'to' not in params


def test_stream_rejects_malformed_rows():
    with pytest.raises(ElexonAPIError, match='malformed row'):
        _unwrap_rows([{'generation': 1}, None], 'FUELHH')
