from app.models.planet_estimator import enrich


def test_estimator_preserves_measurements_and_marks_missing_values():
    planet = {
        "name": "Example b",
        "period": {"value": 12.4, "unit": "d"},
        "mass": {"value": 9.1, "unit": "M_earth"},
        "radius": None,
        "transit_duration": None,
        "transit_depth": None,
        "semi_major_axis": {"value": 0.1, "unit": "AU"},
    }
    star = {
        "radius": {"value": 1.0, "unit": "R_sun"},
        "mass": {"value": 1.0, "unit": "M_sun"},
        "teff": {"value": 5700, "unit": "K"},
    }

    planets, metadata = enrich([planet], star)

    assert planets[0]["mass"] == planet["mass"]  # archive values are never overwritten
    assert planets[0]["radius"]["calculated"] is True
    assert planets[0]["radius"]["estimate"]["method"] == "Local ridge regression"
    assert metadata and metadata["estimates"] >= 1


def test_estimate_carries_error_and_basis():
    planets, _ = enrich([{"name": "X b", "period": {"value": 12.4}, "mass": {"value": 9.1}, "radius": None, "semi_major_axis": {"value": 0.1}}],
                        {"radius": {"value": 1.0}, "mass": {"value": 1.0}, "teff": {"value": 5700}})
    est = planets[0]["radius"]["estimate"]
    assert est["error_factor"] and est["error_factor"] > 1
    assert est["error_basis"]                      # says whether the error is held-out or in-sample
    assert "factor" in est["uncertainty_note"]


def test_no_estimate_from_fewer_than_two_inputs():
    planets, meta = enrich([{"name": "Y b", "period": {"value": 3.0}, "radius": None, "mass": None}], None)
    assert planets[0]["radius"] is None and meta is None


def test_holdout_error_preferred(monkeypatch):
    from app.models import planet_estimator as pe
    assert pe._error({"rmse_log10": 0.1, "holdout_rmse_log10": 0.2}) == (0.2, "held-out data")
    assert pe._error({"rmse_log10": 0.1})[0] == 0.1 and "in-sample" in pe._error({"rmse_log10": 0.1})[1]
    assert pe._error({}) == (None, None)
