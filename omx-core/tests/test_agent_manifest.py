import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENT = REPO / "agents" / "report-reviewer.md"


def test_agent_file_exists_with_frontmatter():
    text = AGENT.read_text()
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "agent file must open with YAML frontmatter"
    fm = m.group(1)
    assert "name: report-reviewer" in fm
    assert re.search(r"(?m)^tools:", fm)
    assert "Write" not in fm.split("tools:")[1].splitlines()[0]
    assert "Edit" not in fm.split("tools:")[1].splitlines()[0]


def test_agent_runs_the_mechanical_verb_first():
    assert "omx report-review" in AGENT.read_text()
