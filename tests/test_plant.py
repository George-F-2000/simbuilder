import os

import pytest

from optimizer import plant
from conftest import TIR_TEXT, AAE_TEXT


def test_registry_is_only_the_road_load_pair():
    assert set(plant.PARAMS) == {"lmy_scale", "aero_scale"}


def test_validate_rejects_unknown_parameter():
    with pytest.raises(KeyError):
        plant.validate_params({"mass_kg": 2000})
    with pytest.raises(KeyError):
        plant.validate_params({"spring_rate": 1.0})


def test_validate_clips_and_fills_defaults():
    p = plant.validate_params({"lmy_scale": 99.0, "aero_scale": 0.0})
    assert p["lmy_scale"] == plant.PARAMS["lmy_scale"]["max"]
    assert p["aero_scale"] == plant.PARAMS["aero_scale"]["min"]
    f = plant.full_params({"lmy_scale": 1.2})
    assert f == {"lmy_scale": 1.2, "aero_scale": 1.0}
    with pytest.raises(ValueError):
        plant.validate_params({"lmy_scale": 1.0}, {"lmy_scale": (0.1, 3.0)})


def test_scale_keyword_lmy():
    new, old = plant.scale_keyword(TIR_TEXT, "LMY", 1.2)
    assert old == 1.25
    assert "LMY =                             1.5" in new
    # other scaling factors untouched
    assert "LMUX =                            1   " in new
    assert "LMUY =                            1   " in new
    with pytest.raises(plant.PlantEditError):
        plant.scale_keyword(TIR_TEXT, "LMZ", 1.2)


def test_scale_spline_column_drag_only():
    new, n = plant.scale_spline_column(AAE_TEXT, "DRAG_COEFFICIENT", 1, 2.0)
    assert n == 4
    drag = new.split("[DRAG_COEFFICIENT]")[1].split("$---")[0]
    side = new.split("[SIDEFORCE_COEFFICIENT]")[1]
    assert "0.6" in drag and "0.62" in drag and "0.64" in drag and "0.66" in drag
    assert "0.0                 0.3" not in drag          # old values gone
    assert "0.0                 0.0" in side and "10.0                0.4" in side   # side force untouched
    # incidence angles (column 0) untouched
    assert "10.0" in drag and "20.0" in drag and "30.0" in drag
    with pytest.raises(plant.PlantEditError):
        plant.scale_spline_column(AAE_TEXT, "LIFT_COEFFICIENT", 1, 2.0)


def test_candidate_files_written(tmp_path, tir_file, aae_file):
    out = plant.candidate_files(str(tmp_path / "plant"), 3,
                                {"lmy_scale": 1.1, "aero_scale": 0.9}, tir_file, aae_file)
    assert os.path.isfile(out["tire_path"]) and os.path.isfile(out["aero_path"])
    assert os.path.basename(out["tire_path"]).startswith("c03_")
    assert out["edits"]["lmy"]["base"] == 1.25
    assert abs(out["edits"]["lmy"]["value"] - 1.375) < 1e-9
    assert out["edits"]["aero"]["rows"] == 4
    txt = open(out["aero_path"]).read()
    assert "0.27" in txt    # 0.3 * 0.9


def test_candidate_files_raise_when_target_missing(tmp_path, aae_file):
    bad = tmp_path / "nolmy.tir"
    bad.write_text("[SCALING_COEFFICIENTS]\n LMUX = 1\n", encoding="utf-8")
    with pytest.raises(plant.PlantEditError):
        plant.candidate_files(str(tmp_path / "plant"), 0, {}, str(bad), aae_file)


def test_deck_file_refs_resolves_relative(tmp_path):
    deck = tmp_path / "model.xml"
    (tmp_path / "t.tir").write_text("x")
    deck.write_text('<a string="../model_dir/../t.tir"/> <b string="C:/x/y/aero.aae"/>')
    tirs = plant.deck_file_refs(str(deck), ".tir")
    assert len(tirs) == 1 and tirs[0].lower().endswith("t.tir")
    aaes = plant.deck_file_refs(str(deck), ".aae")
    assert aaes and aaes[0].lower().endswith("aero.aae")
