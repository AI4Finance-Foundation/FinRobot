import subprocess

import scripts.find_refs as find_refs


def test_find_def_site_escapes_regex_metacharacters(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="finrobot/example.py\n")

    monkeypatch.setattr(find_refs.subprocess, "run", fake_run)

    assert find_refs._find_def_site("foo.bar") == "finrobot/example.py"
    assert r"foo\.bar" in calls[0][2]


def test_grep_hits_searches_symbol_as_fixed_string(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="finrobot/example.py:12:foo.bar()\n")

    monkeypatch.setattr(find_refs.subprocess, "run", fake_run)

    assert find_refs._grep_hits("foo.bar") == {("finrobot/example.py", 12)}
    assert calls[0][1] == "-rwnF"
    assert "foo.bar" in calls[0]
