import ast
from pathlib import Path

from seen_core.pii import ner

CORE = Path(__file__).resolve().parents[2] / "packages/core/src/seen_core"
HOT = ["hook.py", "spool.py", "paths.py", "config.py", "gitdelta.py", "gitutil.py", "project.py", "secret.py", "redact.py",
       "memory/files.py", "memory/rank.py", "memory/session.py", "memory/stale.py", "pii/detect.py", "pii/validators.py",
       "pii/projectcfg.py", "skills/lock.py", "skills/scan.py", "skills/hashing.py", "frontmatter.py"]


def imports(path: Path) -> set[str]:
    out = set()
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
    return out


def test_hot_path_never_imports_heavy_modules() -> None:
    heavy = {"presidio_analyzer", "spacy", "sqlalchemy", "alembic", "yaml", "fastapi", "pathspec", "pydantic", "typer"}
    for f in HOT:
        bad = imports(CORE / f) & heavy
        # pathspec is used lazily inside functions that only run in block mode / at ingest
        assert not (bad - {"pathspec"}), (f, bad)


def test_ner_engine_with_injected_analyzer() -> None:
    class Res:
        def __init__(self, t: str, s: int, e: int, score: float) -> None:
            self.entity_type, self.start, self.end, self.score = t, s, e, score

    class Fake:
        def analyze(self, text: str, language: str) -> list[Res]:
            i = text.index("Asha Rao")
            return [Res("PERSON", i, i + 8, 0.85), Res("LOCATION", 0, 4, 0.3)]

    found = ner.scan("Pune: patient Asha Rao visited", analyzer=Fake())
    assert [(f.type, f.confidence, f.count) for f in found] == [("person", "medium", 1)]
    assert len(found[0].fingerprints[0]) == 16


def test_ner_unavailable_is_reported_not_fatal() -> None:
    assert ner.available() in (True, False)
    if not ner.available():
        assert ner.scan("Asha Rao") == []
