import calculations_seed


def test_seed_does_not_use_removed_models():
    # Seed ładuje cennik z plików, więc nie może odwoływać się do usuniętych modeli ani pól.
    source = open(calculations_seed.__file__, encoding="utf-8").read()
    for name in ("RegulatoryPeriod", "SupplierUreRate", "OsdVariableNetworkRate"):
        assert name not in source
    assert calculations_seed.TARIFF_DATA_DIR.is_dir()
