import json

from omx_core.doctor import run_doctor
from omx_core.cli import main


def test_doctor_shape_no_root():
    out = run_doctor()
    assert out["omx_core_importable"] is True
    assert isinstance(out["python_version"], str)
    assert set(out["deps"]) == {"numpy", "yaml", "matplotlib", "tensorboard", "pandas"}
    assert out["profile_present"] is None
    assert out["hooks_installed"] is None


def test_doctor_profile_detection(tmp_path):
    assert run_doctor(root=str(tmp_path))["profile_present"] is False
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text("output_root: experiments\n")
    assert run_doctor(root=str(tmp_path))["profile_present"] is True


def test_doctor_hooks_detection(tmp_path):
    assert run_doctor(plugin_root=str(tmp_path))["hooks_installed"] is False
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "run_hook.py").write_text("# stub")
    assert run_doctor(plugin_root=str(tmp_path))["hooks_installed"] is True


def test_cli_doctor(tmp_path, capsys):
    rc = main(["doctor", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["profile_present"] is False
