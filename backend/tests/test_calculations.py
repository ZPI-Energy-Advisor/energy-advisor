import pytest
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.services.calculations import format_hour_label, calculate_all_tariffs

def _get_mock_db():
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
    return mock_db

def test_format_hour_label():
    assert format_hour_label(datetime(2025, 8, 9, 14, 15)) == "14:00"
    assert format_hour_label(datetime(2025, 8, 9, 0, 45)) == "00:00"
    assert format_hour_label(datetime(2025, 8, 9, 1, 0)) == "00:00"
    assert format_hour_label(datetime(2025, 8, 9, 0, 0)) == "23:00"

def test_calculate_old_format_success():
    csv_content = """Data;Wartość kWh;Rodzaj
    2024-11-03 1:00;0,65;pobór
    2024-11-03 2:00;0,50;pobór
    2024-11-03 24:00;1,00;pobór"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    results = calculate_all_tariffs(dummy_file, _get_mock_db())

    assert results["statistics"]["data_start"] == "2024-11-03"
    assert results["tariffs"]["G11"]["total_usage_kwh"] == 2.15

def test_calculate_new_format_with_excel_bug_and_oddanie():
    csv_content = """Data i godzina;Wartosc[kWh/kvar];Rodzaj energii
07.06.2026 01:00;1,00;pobór
07.06.2026 02:00;5,00;oddanie
46181;2,00;pobór"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    results = calculate_all_tariffs(dummy_file, _get_mock_db())

    assert results["tariffs"]["G11"]["total_usage_kwh"] == 3.00
    
    assert results["statistics"]["days_analyzed"] == 1
    assert results["statistics"]["data_start"] == "2026-06-07"
    
    assert results["statistics"]["has_missing_data"] is True

def test_calculate_only_oddanie_raises_400():
    csv_content = """Data i godzina;Wartosc[kWh/kvar];Rodzaj energii
07.06.2026 01:00;5,00;oddanie
07.06.2026 02:00;5,00;oddanie"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    
    with pytest.raises(HTTPException) as exc_info:
        calculate_all_tariffs(dummy_file, _get_mock_db())
    
    assert exc_info.value.status_code == 400
    assert "tylko dane o oddaniu" in str(exc_info.value.detail)


def test_calculate_bad_columns_raises_422():
    csv_content = "Totalna;Bzdura\n1;2"
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    
    with pytest.raises(HTTPException) as exc_info:
        calculate_all_tariffs(dummy_file, _get_mock_db())
    
    assert exc_info.value.status_code == 422
    assert "Nierozpoznany format" in str(exc_info.value.detail)