import requests
from unittest.mock import MagicMock, patch
from datetime import date
from app.services.pse_api import ensure_dynamic_prices

def test_ensure_dynamic_prices_uses_cache():
    db_mock = MagicMock()
    db_mock.query().filter().filter().distinct().count.return_value = 2
    
    start_date = date(2026, 1, 1)
    end_date = date(2026, 1, 2)

    with patch('app.services.pse_api.requests.get') as mock_get:
        ensure_dynamic_prices(start_date, end_date, db_mock)
        
        mock_get.assert_not_called()  
        db_mock.add_all.assert_not_called()  

def test_ensure_dynamic_prices_fetches_from_api():
    db_mock = MagicMock()
    db_mock.query().filter().filter().distinct().count.return_value = 0 
    db_mock.query().filter_by().first.return_value = None 
    
    start_date = date(2026, 1, 1)
    end_date = date(2026, 1, 1)
    
    fake_api_response = {
        "value": [
            {"business_date": "2026-01-01", "period": "00:00 - 00:15", "rce_pln": 500.0}
        ]
    }

    with patch('app.services.pse_api.requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_api_response
        mock_get.return_value = mock_response
        
        ensure_dynamic_prices(start_date, end_date, db_mock)
        
        mock_get.assert_called_once()
        assert db_mock.add_all.called
        
        added_prices = db_mock.add_all.call_args[0][0]
        
        assert len(added_prices) == 1
        assert added_prices[0].price_per_kwh == 0.5000  
        assert added_prices[0].hour == "00:00"

def test_ensure_dynamic_prices_fallback_mock():
    db_mock = MagicMock()
    db_mock.query().filter().filter().distinct().count.return_value = 0
    
    start_date = date(2026, 1, 1)
    end_date = date(2026, 1, 1)

    with patch('app.services.pse_api.requests.get', side_effect=requests.exceptions.ConnectionError("Brak neta")):
        ensure_dynamic_prices(start_date, end_date, db_mock)
        
        assert True