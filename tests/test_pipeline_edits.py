"""The pipeline changes made for the optimizer: counted tyre/aero overrides,
deck hooks, aero files in deck_info."""
import os

import pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DECK = ('<Model>\n  <Tire string = "C:/old/place/old_tyre.tir" />\n'
        '  <Tire string = "C:/old/place/old_tyre.tir" />\n'
        '  <Aero string = "C:/old/place/old_aero.aae" />\n</Model>\n')


def _vehicle(tir, aae):
    return {"deck_default": False, "tire_path": tir, "aero_path": aae, "spec": {}}


def test_apply_vehicle_counts_tyre_and_aero_references(tmp_path, tir_file, aae_file):
    lines = []
    out = pipeline.apply_vehicle(_vehicle(tir_file, aae_file), DECK, str(tmp_path),
                                 str(tmp_path), lines.append)
    assert out.count(tir_file.replace("\\", "/")) == 2
    assert out.count(aae_file.replace("\\", "/")) == 1
    assert any("tire file ->" in l and "2 references" in l for l in lines)
    assert any("aero file ->" in l and "1 reference" in l for l in lines)


def test_apply_vehicle_warns_when_deck_has_no_reference(tmp_path, tir_file, aae_file):
    lines = []
    out = pipeline.apply_vehicle(_vehicle(tir_file, aae_file), "<Model/>", str(tmp_path),
                                 str(tmp_path), lines.append)
    assert out == "<Model/>"
    assert any("WARNING" in l and ".tir reference" in l for l in lines)
    assert any("WARNING" in l and ".aae reference" in l for l in lines)


def test_apply_vehicle_warns_when_override_file_missing(tmp_path):
    lines = []
    pipeline.apply_vehicle(_vehicle(str(tmp_path / "nope.tir"), str(tmp_path / "nope.aae")),
                           DECK, str(tmp_path), str(tmp_path), lines.append)
    assert sum(1 for l in lines if "WARNING" in l and "not found" in l) == 2


def test_deck_hooks_example_and_failure(tmp_path):
    lines = []
    example = os.path.join(ROOT, "deck_hook_example.py")
    settings = {"deck_hooks": [example, str(tmp_path / "missing.local.py")]}
    out = pipeline.apply_deck_hooks(settings, DECK, str(tmp_path),
                                    {"hook_params": {"k": 1}}, lines.append)
    assert out == DECK
    assert any("example deck hook" in l and "1 hook parameter" in l for l in lines)
    assert any("deck hook deck_hook_example.py: changed x0" in l for l in lines)
    assert any("missing.local.py NOT applied" in l for l in lines)


def test_deck_hook_changes_and_per_run_hooks(tmp_path):
    hook = tmp_path / "my_plant.local.py"
    hook.write_text(
        "import re\n"
        "def apply(deck_text, *, run_dir, settings, vehicle, log):\n"
        "    k = vehicle.get('hook_params', {}).get('gain', 1)\n"
        "    new, n = re.subn(r'old_aero', 'gain%g_aero' % k, deck_text)\n"
        "    if n != 1: raise RuntimeError('count %d' % n)\n"
        "    return new, {'aero': n}\n", encoding="utf-8")
    lines = []
    out = pipeline.apply_deck_hooks({}, DECK, str(tmp_path),
                                    {"deck_hooks": [str(hook)], "hook_params": {"gain": 2}},
                                    lines.append)
    assert "gain2_aero.aae" in out
    assert any("my_plant.local.py: aero x1" in l for l in lines)


def test_deck_info_lists_aero(tmp_path):
    deck = tmp_path / "m.xml"
    deck.write_text(DECK)
    info = pipeline.deck_info({"deck": str(deck)})
    assert info["tires"] == ["old_tyre.tir"]
    assert info["aeros"] == ["old_aero.aae"]
