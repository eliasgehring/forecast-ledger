def test_package_imports() -> None:
    import forecast_ledger

    assert forecast_ledger.__version__ == "0.1.0"