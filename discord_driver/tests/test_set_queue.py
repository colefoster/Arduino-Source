import pytest

from discord_driver.set_queue import SetQueue, _species_from_body, load_sets_from_file


@pytest.fixture
def queue(tmp_path):
    q = SetQueue(tmp_path / "test.db")
    yield q
    q.close()


VAPOREON = (
    "Vaporeon @ Leftovers\n"
    "Ability: Water Absorb\n"
    "Shiny: Yes\n"
    "Bold Nature\n"
    "- Mud-Slap\n- Fake Tears\n- Charm\n- Helping Hand"
)

NICKED_LUCARIO = (
    "Bonecrusher (Lucario) (M) @ Life Orb\n"
    "Ability: Inner Focus\n"
    "Adamant Nature\n"
    "- Close Combat"
)


def test_species_extraction_simple():
    assert _species_from_body(VAPOREON) == "Vaporeon"


def test_species_extraction_nickname_form():
    assert _species_from_body(NICKED_LUCARIO) == "Lucario"


def test_add_and_get(queue):
    s = queue.add_set(VAPOREON)
    assert s.species == "Vaporeon"
    assert s.status == "pending"
    assert s.code is None
    assert queue.get(s.set_id) == s


def test_next_pending_orders_by_creation(queue):
    a = queue.add_set(VAPOREON)
    b = queue.add_set(NICKED_LUCARIO)
    nxt = queue.next_pending()
    assert nxt is not None and nxt.set_id == a.set_id


def test_full_lifecycle(queue):
    s = queue.add_set(VAPOREON)

    queue.mark_submitted(s.set_id)
    assert queue.get(s.set_id).status == "submitted"

    queue.mark_queued(s.set_id, "59961930")
    refreshed = queue.get(s.set_id)
    assert refreshed.status == "queued"
    assert refreshed.code == "59961930"

    # Match-by-code is the critical Discord-driver path.
    assert queue.get_by_code("59961930").set_id == s.set_id

    queue.mark_loading(s.set_id)
    queue.mark_traded(s.set_id)
    assert queue.get(s.set_id).status == "traded"
    assert queue.next_pending() is None


def test_failure_path_records_reason(queue):
    s = queue.add_set(VAPOREON)
    queue.mark_submitted(s.set_id)
    queue.mark_queued(s.set_id, "12345678")
    queue.mark_failed(s.set_id, "TrainerTooSlow")

    refreshed = queue.get(s.set_id)
    assert refreshed.status == "failed"
    assert refreshed.failure_reason == "TrainerTooSlow"


def test_in_flight_lists_only_active(queue):
    a = queue.add_set(VAPOREON)
    b = queue.add_set(NICKED_LUCARIO)
    queue.mark_submitted(a.set_id)
    queue.mark_queued(a.set_id, "11112222")
    queue.mark_loading(a.set_id)
    # b is still pending → not in flight
    in_flight = queue.in_flight()
    assert {x.set_id for x in in_flight} == {a.set_id}


def test_counts_by_status(queue):
    queue.add_set(VAPOREON)
    s2 = queue.add_set(NICKED_LUCARIO)
    queue.mark_submitted(s2.set_id)
    queue.mark_queued(s2.set_id, "99998888")
    assert queue.counts_by_status() == {"pending": 1, "queued": 1}


def test_persistence_across_reopen(tmp_path):
    db = tmp_path / "persist.db"
    q1 = SetQueue(db)
    s = q1.add_set(VAPOREON)
    q1.mark_submitted(s.set_id)
    q1.mark_queued(s.set_id, "44445555")
    q1.close()

    q2 = SetQueue(db)
    refreshed = q2.get_by_code("44445555")
    assert refreshed is not None
    assert refreshed.set_id == s.set_id
    q2.close()


def test_invalid_code_rejected(queue):
    s = queue.add_set(VAPOREON)
    queue.mark_submitted(s.set_id)
    with pytest.raises(ValueError):
        queue.mark_queued(s.set_id, "5996 1930")  # space not stripped
    with pytest.raises(ValueError):
        queue.mark_queued(s.set_id, "1234")


def test_unknown_set_id_raises(queue):
    with pytest.raises(KeyError):
        queue.mark_traded("does-not-exist")


def test_load_sets_from_file_blank_separated(tmp_path):
    f = tmp_path / "sets.txt"
    f.write_text(VAPOREON + "\n\n" + NICKED_LUCARIO + "\n")
    blocks = load_sets_from_file(f)
    assert len(blocks) == 2
    assert blocks[0].startswith("Vaporeon")
    assert "Lucario" in blocks[1]
