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
