"""enrich_blocks: bounded queries, merged across chunks."""

from sqlalchemy import event

from seen_core.db import ledger_session
from seen_core.db.models import Change
from seen_core.headline import headline_of
from seen_core.provenance import enrich
from seen_core.provenance.blame import Block


def _seed(n: int) -> list[Block]:
    with ledger_session() as db:
        db.add_all(Change(id=f"c{i:05d}", summary=f"Did thing number {i} properly.", model="m") for i in range(n))
        db.commit()
    return [Block(i + 1, i + 1, "agent", f"c{i:05d}") for i in range(n)]


def test_more_than_900_ids_are_chunked_and_complete() -> None:
    blocks = _seed(1000)
    with ledger_session() as db:
        stmts: list[str] = []
        event.listen(db.get_bind(), "before_cursor_execute", lambda *a: stmts.append(a[2]))
        out = enrich.enrich_blocks(db, blocks)
    assert len(stmts) == 6  # two chunks, three queries each
    assert [b.change_id for b in out] == [b.change_id for b in blocks]
    assert out[999].headline == "Did thing number 999 properly." and out[0].model == "m"


def test_small_chunk_merges(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(enrich, "CHUNK", 2)
    out = enrich.enrich_blocks(ledger_session().__enter__(), _seed(5))
    assert [b.headline for b in out] == [f"Did thing number {i} properly." for i in range(5)]


def test_headline_strips_control_characters() -> None:
    h = headline_of("\x1b[31mFixed\x1b[0m the \x1b]0;x\x07retry\tpath\x85 properly.", None, [])
    assert h == "[31mFixed[0m the ]0;xretry path properly."
    assert not any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F for c in h)
