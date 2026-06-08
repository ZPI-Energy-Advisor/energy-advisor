import pytest
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock
from app.services.calculations import format_hour_label, calculate_all_tariffs

def test_format_hour_label():
    assert format_hour_label(datetime(2025, 8, 9, 14, 15)) == "14:00"
    assert format_hour_label(datetime(2025, 8, 9, 0, 45)) == "00:00"
    assert format_hour_label(datetime(2025, 8, 9, 1, 0)) == "00:00"
    assert format_hour_label(datetime(2025, 8, 9, 0, 0)) == "23:00"

def test_calculate_all_tariffs_success():
    csv_content = """Data;Wartość kWh;Rodzaj
    2024-11-03 1:00;0,65;pobór
    2024-11-03 2:00;0,50;pobór
    2024-11-03 24:00;1,00;pobór"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))

    mock_db = MagicMock()
    
    mock_tariff = MagicMock()
    mock_tariff.id = 1
    mock_tariff.name = "G11"
    mock_tariff.type = "stala"
    
    mock_rate = MagicMock()
    mock_rate.time_start = datetime.strptime("00:00:00", "%H:%M:%S").time()
    mock_rate.time_end = datetime.strptime("23:59:59", "%H:%M:%S").time()
    mock_rate.price_per_kwh = 1.0

    mock_db.query().all.return_value = [mock_tariff]
    mock_db.query().filter().all.return_value = [mock_rate]

    results = calculate_all_tariffs(dummy_file, mock_db)

    
    assert results["statistics"]["days_analyzed"] == 1
    assert results["statistics"]["data_start"] == "2024-11-03"
    
    assert results["tariffs"]["G11"]["total_usage_kwh"] == 2.15
    assert results["tariffs"]["G11"]["estimated_cost_pln"] == 2.15
    
    hourly = results["chart_hourly"]
    hour_23_data = next((item for item in hourly if item["hour"] == "23:00"), None)
    assert hour_23_data is not None
    assert hour_23_data["kwh"] == 1.0

def test_calculate_all_tariffs_bad_format():
    csv_content = "ZłaKolumna1;ZłaKolumna2\n1;2"
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    mock_db = MagicMock()

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        calculate_all_tariffs(dummy_file, mock_db)
    
    assert exc_info.value.status_code == 422
    assert "Nierozpoznany format" in str(exc_info.value.detail)