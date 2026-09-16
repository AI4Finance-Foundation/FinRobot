import importlib.util
from pathlib import Path

import pytest

CODING_PATH = Path(__file__).parents[1] / "finrobot" / "functional" / "coding.py"
SPEC = importlib.util.spec_from_file_location("coding", CODING_PATH)
coding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coding)
CodingUtils = coding.CodingUtils


def test_create_file_with_code_writes_inside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CodingUtils.create_file_with_code("reports/analysis.py", "print('ok')")

    assert result == "File created successfully"
    assert (tmp_path / "coding" / "reports" / "analysis.py").read_text() == "print('ok')"


def test_create_file_with_code_rejects_parent_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="Path escapes the coding workspace"):
        CodingUtils.create_file_with_code("../escape.py", "print('bad')")

    assert not (tmp_path / "escape.py").exists()


def test_modify_code_rejects_parent_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outside.py").write_text("print('unchanged')\n")

    with pytest.raises(ValueError, match="Path escapes the coding workspace"):
        CodingUtils.modify_code("../outside.py", 1, 1, "print('changed')")

    assert (tmp_path / "outside.py").read_text() == "print('unchanged')\n"
