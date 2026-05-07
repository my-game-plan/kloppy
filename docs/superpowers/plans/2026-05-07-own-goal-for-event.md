# OwnGoalForEvent + GoalQualifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `GoalQualifier` (BoolQualifier) attached at parse time to GOAL shots, plus a synthetic `OwnGoalForEvent` (with `GoalQualifier`) inserted after `OWN_GOAL` shots on the beneficiary team — so a single qualifier query returns every goal credited to a team.

**Architecture:**
- New domain types (`GoalQualifier`, `OwnGoalForEvent`, `EventType.OWN_GOAL_FOR`) in `kloppy/domain/models/event.py`.
- Override `EventDataset.__post_init__` to attach `GoalQualifier` automatically to every parsed dataset.
- New opt-in `SyntheticOwnGoalForGenerator` registered in `EventDataset.add_synthetic_event`, mirroring the carry/ball_receipt pattern.

**Tech Stack:** Python 3.x, dataclasses, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-07-own-goal-for-event-design.md`

**Branch:** `mgp-fork/own-goal-for-event` (already created and checked out from `mgp-fork/v11`).

---

## File Structure

**Create:**
- `kloppy/domain/services/synthetic_event_generators/own_goal_for.py` — `SyntheticOwnGoalForGenerator`.

**Modify:**
- `kloppy/domain/models/event.py` — `EventType.OWN_GOAL_FOR`, `GoalQualifier`, `OwnGoalForEvent`, `EventDataset.__post_init__` override + `_attach_goal_qualifiers`, `add_synthetic_event` branch, `__all__` exports.
- `kloppy/domain/services/event_factory.py` — `build_own_goal_for` builder + import.

**Test:**
- `kloppy/tests/test_synthetic_event_generator.py` — tests for `GoalQualifier` attachment, generator behavior, idempotence.
- `kloppy/tests/test_statsbomb.py` — append a small assertion that the existing OWN_GOAL fixture produces an `OwnGoalForEvent` after running the generator.

---

## Conventions

- Run tests with: `pytest <path>::<test_name> -v` from repo root.
- Tests live in `kloppy/tests/`.
- Existing tests use the `base_dir` fixture (defined in `kloppy/tests/conftest.py`) which points to `kloppy/tests/`.
- Commit messages: lowercase, imperative, follow recent commits in the branch (e.g., "fix own goal deserialization [korastats]"). Co-author footer included.

---

## Task 1: Add `EventType.OWN_GOAL_FOR`, `GoalQualifier`, `OwnGoalForEvent`

**Files:**
- Modify: `kloppy/domain/models/event.py`
- Test: `kloppy/tests/test_synthetic_event_generator.py` (append a new test class)

- [ ] **Step 1.1: Write the failing test**

Append to `kloppy/tests/test_synthetic_event_generator.py`:

```python
class TestOwnGoalForDomain:
    """Domain-level tests for the new GoalQualifier and OwnGoalForEvent."""

    def test_goal_qualifier_is_bool_qualifier(self):
        from kloppy.domain import GoalQualifier
        from kloppy.domain.models.event import BoolQualifier

        q = GoalQualifier(value=True)
        assert isinstance(q, BoolQualifier)
        assert q.name == "goal"
        assert q.to_dict() == {"is_goal": True}

    def test_own_goal_for_event_type_exists(self):
        from kloppy.domain import EventType

        assert EventType.OWN_GOAL_FOR.value == "OWN_GOAL_FOR"

    def test_own_goal_for_event_class_attributes(self):
        from kloppy.domain import OwnGoalForEvent, EventType

        assert OwnGoalForEvent.event_type == EventType.OWN_GOAL_FOR
        assert OwnGoalForEvent.event_name == "own_goal_for"
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py::TestOwnGoalForDomain -v`

Expected: FAIL with `ImportError` on `GoalQualifier` (and `OwnGoalForEvent` once that import is reached).

- [ ] **Step 1.3: Add `EventType.OWN_GOAL_FOR` enum member**

In `kloppy/domain/models/event.py`, find the `EventType` enum (around line 223). Add `OWN_GOAL_FOR` after `BALL_RECEIPT` (around line 268):

```python
    OWN_GOAL_FOR = "OWN_GOAL_FOR"
```

Also add it to the docstring list at the top of the enum (around lines 226-246):

```python
        OWN_GOAL_FOR (EventType):
```

- [ ] **Step 1.4: Add `GoalQualifier` class**

In the same file, near `CounterAttackQualifier` (around line 549), add:

```python
@dataclass
class GoalQualifier(BoolQualifier):
    """
    Marks an event that scored a goal for the team owning this event.

    Attached automatically (via EventDataset post-load) to ShotEvents
    with result == ShotResult.GOAL, and to synthetic OwnGoalForEvents
    on the team that benefited from an opponent's own goal.

    ShotEvents with result == ShotResult.OWN_GOAL do NOT receive this
    qualifier — the synthetic OwnGoalForEvent on the opposing team
    carries it instead.
    """

    pass
```

- [ ] **Step 1.5: Add `OwnGoalForEvent` class**

In the same file, near `BallReceiptEvent` (around line 1148), add:

```python
@dataclass(repr=False)
@docstring_inherit_attributes(Event)
class OwnGoalForEvent(Event):
    """
    OwnGoalForEvent

    Synthetic event representing a goal credited to a team via an
    opponent's own goal. Inserted after the source ShotEvent whose
    result == ShotResult.OWN_GOAL. The team is the beneficiary
    (opponent of the shooter); player is None.

    Attributes:
        event_type (EventType): `EventType.OWN_GOAL_FOR`
        event_name (str): `"own_goal_for"`
    """

    event_type: EventType = EventType.OWN_GOAL_FOR
    event_name: str = "own_goal_for"
```

- [ ] **Step 1.6: Update `__all__` exports**

In the same file, find `__all__` (around line 1483). Add `"GoalQualifier"` (alphabetically near other qualifiers) and `"OwnGoalForEvent"` (near other event classes). Also add `"OWN_GOAL_FOR"` is NOT a separate export — `EventType` already exports the whole enum.

Locate lines like:
```python
    "BallReceiptEvent",
    ...
    "CounterAttackQualifier",
```

Add:
```python
    "GoalQualifier",
    "OwnGoalForEvent",
```

- [ ] **Step 1.7: Run test to verify it passes**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py::TestOwnGoalForDomain -v`

Expected: PASS (3 tests).

- [ ] **Step 1.8: Commit**

```bash
git add kloppy/domain/models/event.py kloppy/tests/test_synthetic_event_generator.py
git commit -m "$(cat <<'EOF'
add GoalQualifier, OwnGoalForEvent, EventType.OWN_GOAL_FOR

Introduces domain types for unified goal-credit semantics. GoalQualifier
is a BoolQualifier marking events that scored a goal for the owning team.
OwnGoalForEvent represents a goal credited via an opponent's own goal
(player=None, team=beneficiary).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `EventFactory.build_own_goal_for`

**Files:**
- Modify: `kloppy/domain/services/event_factory.py`
- Test: `kloppy/tests/test_synthetic_event_generator.py` (extend `TestOwnGoalForDomain`)

- [ ] **Step 2.1: Write the failing test**

Append a test method to `TestOwnGoalForDomain`:

```python
    def test_event_factory_build_own_goal_for(self):
        from kloppy.domain import EventFactory, OwnGoalForEvent

        factory = EventFactory()
        event = factory.build_own_goal_for(
            event_id="ogf-1",
            coordinates=None,
            team=None,
            player=None,
            ball_owning_team=None,
            ball_state=None,
            period=None,
            timestamp=None,
            raw_event=None,
            qualifiers=None,
            related_event_ids=[],
            result=None,
        )
        assert isinstance(event, OwnGoalForEvent)
        assert event.event_id == "ogf-1"
        assert event.player is None
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py::TestOwnGoalForDomain::test_event_factory_build_own_goal_for -v`

Expected: FAIL with `AttributeError: 'EventFactory' object has no attribute 'build_own_goal_for'`.

- [ ] **Step 2.3: Add the import**

In `kloppy/domain/services/event_factory.py`, at line 26 (the `from kloppy.domain.models.event import PressureEvent, BallReceiptEvent` line), add `OwnGoalForEvent`:

```python
from kloppy.domain.models.event import PressureEvent, BallReceiptEvent, OwnGoalForEvent
```

- [ ] **Step 2.4: Add the builder method**

In the same file, after `build_ball_receipt` (around line 135), add:

```python
    def build_own_goal_for(self, **kwargs) -> OwnGoalForEvent:
        return create_event(OwnGoalForEvent, **kwargs)
```

- [ ] **Step 2.5: Run test to verify it passes**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py::TestOwnGoalForDomain::test_event_factory_build_own_goal_for -v`

Expected: PASS.

- [ ] **Step 2.6: Commit**

```bash
git add kloppy/domain/services/event_factory.py kloppy/tests/test_synthetic_event_generator.py
git commit -m "$(cat <<'EOF'
add EventFactory.build_own_goal_for

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Post-load `GoalQualifier` attachment in `EventDataset.__post_init__`

**Files:**
- Modify: `kloppy/domain/models/event.py`
- Test: `kloppy/tests/test_synthetic_event_generator.py` (new test class `TestGoalQualifierAttachment`)

- [ ] **Step 3.1: Write the failing test**

Append to `kloppy/tests/test_synthetic_event_generator.py`:

```python
class TestGoalQualifierAttachment:
    """Tests for automatic GoalQualifier attachment at EventDataset construction."""

    def _load_dataset_statsbomb(self, base_dir, base_filename="statsbomb"):
        from kloppy import statsbomb
        return statsbomb.load(
            event_data=base_dir / f"files/{base_filename}_event.json",
            lineup_data=base_dir / f"files/{base_filename}_lineup.json",
        )

    def test_goal_qualifier_attached_to_goal_shots(self, base_dir):
        from kloppy.domain import GoalQualifier, ShotEvent, ShotResult

        dataset = self._load_dataset_statsbomb(base_dir)
        goal_shots = [
            e
            for e in dataset.events
            if isinstance(e, ShotEvent) and e.result == ShotResult.GOAL
        ]
        assert len(goal_shots) > 0, (
            "fixture must contain at least one GOAL shot for this test"
        )
        for shot in goal_shots:
            assert shot.qualifiers is not None
            assert any(
                isinstance(q, GoalQualifier) for q in shot.qualifiers
            ), f"GOAL shot {shot.event_id} missing GoalQualifier"

    def test_goal_qualifier_not_attached_to_own_goal_shots(self, base_dir):
        from kloppy.domain import GoalQualifier, ShotEvent, ShotResult

        dataset = self._load_dataset_statsbomb(base_dir)
        own_goal_shots = [
            e
            for e in dataset.events
            if isinstance(e, ShotEvent) and e.result == ShotResult.OWN_GOAL
        ]
        assert len(own_goal_shots) > 0, (
            "fixture must contain at least one OWN_GOAL shot for this test"
        )
        for shot in own_goal_shots:
            qualifiers = shot.qualifiers or []
            assert not any(
                isinstance(q, GoalQualifier) for q in qualifiers
            ), f"OWN_GOAL shot {shot.event_id} should NOT have GoalQualifier"

    def test_goal_qualifier_idempotent(self, base_dir):
        """Running __post_init__ logic twice should not duplicate qualifiers."""
        from kloppy.domain import GoalQualifier, ShotEvent, ShotResult

        dataset = self._load_dataset_statsbomb(base_dir)
        # Force a second pass of the attachment logic.
        dataset._attach_goal_qualifiers()

        goal_shots = [
            e
            for e in dataset.events
            if isinstance(e, ShotEvent) and e.result == ShotResult.GOAL
        ]
        for shot in goal_shots:
            count = sum(
                1 for q in (shot.qualifiers or []) if isinstance(q, GoalQualifier)
            )
            assert count == 1, (
                f"GOAL shot {shot.event_id} has {count} GoalQualifiers, expected 1"
            )
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py::TestGoalQualifierAttachment -v`

Expected: FAIL — GOAL shots will not have `GoalQualifier` because nothing attaches it yet, and `_attach_goal_qualifiers` does not exist.

- [ ] **Step 3.3: Add `__post_init__` override and `_attach_goal_qualifiers` to `EventDataset`**

In `kloppy/domain/models/event.py`, find the `EventDataset` class (around line 1162). Insert these methods inside the class body, immediately before the existing `_update_formations_and_positions` method (which is around line 1178):

```python
    def __post_init__(self):
        super().__post_init__()
        self._attach_goal_qualifiers()

    def _attach_goal_qualifiers(self):
        for event in self.events:
            if not isinstance(event, ShotEvent):
                continue
            if event.result != ShotResult.GOAL:
                continue
            if event.qualifiers is None:
                event.qualifiers = []
            if not any(isinstance(q, GoalQualifier) for q in event.qualifiers):
                event.qualifiers.append(GoalQualifier(value=True))

```

(Both `ShotEvent`, `ShotResult`, and `GoalQualifier` are defined earlier in the same module — no imports needed.)

- [ ] **Step 3.4: Run test to verify it passes**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py::TestGoalQualifierAttachment -v`

Expected: PASS (3 tests).

- [ ] **Step 3.5: Run the full synthetic event test module to check for regressions**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py -v`

Expected: PASS for all tests (existing carry/ball_receipt tests should still pass).

- [ ] **Step 3.6: Commit**

```bash
git add kloppy/domain/models/event.py kloppy/tests/test_synthetic_event_generator.py
git commit -m "$(cat <<'EOF'
attach GoalQualifier to GOAL shots at EventDataset construction

EventDataset now overrides __post_init__ to attach a GoalQualifier to
every ShotEvent with result == GOAL. OWN_GOAL shots are deliberately
skipped — the synthetic OwnGoalForEvent on the opposing team will
carry the qualifier instead. Idempotent: re-running does not duplicate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `SyntheticOwnGoalForGenerator` and `add_synthetic_event` wire-up

**Files:**
- Create: `kloppy/domain/services/synthetic_event_generators/own_goal_for.py`
- Modify: `kloppy/domain/models/event.py` (the `add_synthetic_event` method around line 1438)
- Test: `kloppy/tests/test_synthetic_event_generator.py` (new test class)

- [ ] **Step 4.1: Write the failing test**

Append to `kloppy/tests/test_synthetic_event_generator.py`:

```python
class TestSyntheticOwnGoalForGenerator:
    """Tests for SyntheticOwnGoalForGenerator."""

    def _load_dataset_statsbomb(self, base_dir, base_filename="statsbomb"):
        from kloppy import statsbomb
        return statsbomb.load(
            event_data=base_dir / f"files/{base_filename}_event.json",
            lineup_data=base_dir / f"files/{base_filename}_lineup.json",
        )

    def test_no_own_goals_produces_no_synthetic_events(self, base_dir):
        """Filter out shots; the generator should produce no OwnGoalForEvents."""
        from kloppy.domain import EventType, OwnGoalForEvent
        from kloppy import statsbomb

        # Load only non-shot events to guarantee no OWN_GOAL shots.
        dataset = statsbomb.load(
            event_data=base_dir / "files/statsbomb_event.json",
            lineup_data=base_dir / "files/statsbomb_lineup.json",
            event_types=[
                e.value for e in EventType if e.value != "SHOT"
            ],
        )
        before = len([e for e in dataset.events if isinstance(e, OwnGoalForEvent)])
        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)
        after = len([e for e in dataset.events if isinstance(e, OwnGoalForEvent)])
        assert before == 0
        assert after == 0

    def test_one_own_goal_produces_one_synthetic_event(self, base_dir):
        from kloppy.domain import (
            EventType,
            GoalQualifier,
            OwnGoalForEvent,
            ShotEvent,
            ShotResult,
        )

        dataset = self._load_dataset_statsbomb(base_dir)
        own_goal_shots = [
            e
            for e in dataset.events
            if isinstance(e, ShotEvent) and e.result == ShotResult.OWN_GOAL
        ]
        assert len(own_goal_shots) >= 1

        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)

        synthetic_events = [
            e for e in dataset.events if isinstance(e, OwnGoalForEvent)
        ]
        assert len(synthetic_events) == len(own_goal_shots)

        # Pick the first own goal and verify the corresponding synthetic event.
        source = own_goal_shots[0]
        synthetic = next(
            e for e in synthetic_events
            if e.event_id == f"own_goal_for-{source.event_id}"
        )

        # Positioned immediately after the source.
        events_list = list(dataset.events)
        source_idx = events_list.index(source)
        assert events_list[source_idx + 1] is synthetic

        # Beneficiary team (opponent of source).
        teams = dataset.metadata.teams
        opponent = next(t for t in teams if t != source.team)
        assert synthetic.team == opponent

        # Player is None.
        assert synthetic.player is None

        # Coordinates copied from source.
        assert synthetic.coordinates == source.coordinates

        # GoalQualifier is present.
        assert synthetic.qualifiers is not None
        assert any(
            isinstance(q, GoalQualifier) for q in synthetic.qualifiers
        )

        # Linked to source via related_event_ids.
        assert synthetic.related_event_ids == [source.event_id]

    def test_generator_is_idempotent(self, base_dir):
        from kloppy.domain import EventType, OwnGoalForEvent

        dataset = self._load_dataset_statsbomb(base_dir)
        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)
        first_run_ids = sorted(
            e.event_id for e in dataset.events
            if isinstance(e, OwnGoalForEvent)
        )

        # Second run on the same dataset.
        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)
        second_run_ids = sorted(
            e.event_id for e in dataset.events
            if isinstance(e, OwnGoalForEvent)
        )

        assert first_run_ids == second_run_ids
        assert len(first_run_ids) >= 1, "fixture must have at least one own goal"
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py::TestSyntheticOwnGoalForGenerator -v`

Expected: FAIL — `KloppyError: Not possible to generate synthetic OWN_GOAL_FOR` (the wire-up is missing) or `ImportError`.

- [ ] **Step 4.3: Create the generator module**

Create `kloppy/domain/services/synthetic_event_generators/own_goal_for.py` with:

```python
from typing import Optional

from kloppy.domain import (
    EventDataset,
    EventFactory,
    ShotEvent,
    ShotResult,
)
from kloppy.domain.models.event import GoalQualifier
from kloppy.domain.services.synthetic_event_generators.synthetic_event_generator import (
    SyntheticEventGenerator,
)


class SyntheticOwnGoalForGenerator(SyntheticEventGenerator):
    def __init__(self, event_factory: Optional[EventFactory] = None, **kwargs):
        self.event_factory = event_factory or EventFactory()

    def add_synthetic_event(self, dataset: EventDataset) -> EventDataset:
        existing_ids = {e.event_id for e in dataset.events}

        for event in list(dataset.events):
            if not isinstance(event, ShotEvent):
                continue
            if event.result != ShotResult.OWN_GOAL:
                continue

            new_event_id = f"own_goal_for-{event.event_id}"
            if new_event_id in existing_ids:
                continue

            opponent_team = next(
                t for t in dataset.metadata.teams if t != event.team
            )

            new_own_goal_for = self.event_factory.build_own_goal_for(
                event_id=new_event_id,
                coordinates=event.coordinates,
                team=opponent_team,
                player=None,
                ball_owning_team=event.ball_owning_team,
                ball_state=event.ball_state,
                period=event.period,
                timestamp=event.timestamp,
                raw_event=None,
                qualifiers=[GoalQualifier(value=True)],
                related_event_ids=[event.event_id],
                result=None,
            )
            dataset.insert(
                new_own_goal_for, after_event_id=event.event_id
            )
            existing_ids.add(new_event_id)

        return dataset
```

- [ ] **Step 4.4: Wire up in `EventDataset.add_synthetic_event`**

In `kloppy/domain/models/event.py`, find `add_synthetic_event` (around line 1438). After the `BALL_RECEIPT` branch (around line 1475), add a third `elif`:

```python
        elif event_type_ == EventType.OWN_GOAL_FOR:
            from kloppy.domain.services.synthetic_event_generators.own_goal_for import (
                SyntheticOwnGoalForGenerator,
            )

            synthetic_event_generator = SyntheticOwnGoalForGenerator(
                event_factory_, **kwargs
            )
```

Also update the docstring (around line 1446) to list `OWN_GOAL_FOR`:

```python
            event_type_ (EventType): The type of event to generate. The supported event types are currently:
                - `EventType.CARRY`: Generates carry events.
                - `EventType.BALL_RECEIPT`: Generates ball receipt events.
                - `EventType.OWN_GOAL_FOR`: Generates own-goal-for events on the beneficiary team.
```

- [ ] **Step 4.5: Run test to verify it passes**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py::TestSyntheticOwnGoalForGenerator -v`

Expected: PASS (3 tests).

- [ ] **Step 4.6: Run the full synthetic event test module**

Run: `pytest kloppy/tests/test_synthetic_event_generator.py -v`

Expected: PASS for all tests.

- [ ] **Step 4.7: Commit**

```bash
git add kloppy/domain/services/synthetic_event_generators/own_goal_for.py kloppy/domain/models/event.py kloppy/tests/test_synthetic_event_generator.py
git commit -m "$(cat <<'EOF'
add SyntheticOwnGoalForGenerator

New opt-in synthetic generator that inserts an OwnGoalForEvent
(carrying GoalQualifier) on the beneficiary team after every
ShotEvent with result == OWN_GOAL. Wired into
EventDataset.add_synthetic_event(EventType.OWN_GOAL_FOR), mirroring
the carry/ball_receipt generator pattern. Deterministic event_ids
make re-runs idempotent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Provider parser end-to-end test (statsbomb)

**Files:**
- Modify: `kloppy/tests/test_statsbomb.py` (extend existing `TestStatsBombOwnGoalEvent` class around line 824)

The existing statsbomb fixture already contains an OWN_GOAL shot (event id `89dd4f4b-0a70-48d8-a0e7-ac4c`, asserted at `kloppy/tests/test_statsbomb.py:850`). We add an assertion that, after running the synthetic generator, an `OwnGoalForEvent` exists on the beneficiary team.

- [ ] **Step 5.1: Write the failing test**

In `kloppy/tests/test_statsbomb.py`, append a new test method to `TestStatsBombOwnGoalEvent`:

```python
    def test_own_goal_for_generator(self, base_dir: Path):
        """After running OWN_GOAL_FOR generator, the beneficiary team gets a synthetic event with GoalQualifier."""
        from kloppy.domain import (
            EventType,
            GoalQualifier,
            OwnGoalForEvent,
        )

        dataset = statsbomb.load(
            lineup_data=base_dir / "files" / "statsbomb_lineup.json",
            event_data=base_dir / "files" / "statsbomb_event.json",
        )

        source_shot = dataset.get_event_by_id(
            "89dd4f4b-0a70-48d8-a0e7-ac4c"
        )
        assert source_shot is not None
        assert source_shot.result == ShotResult.OWN_GOAL

        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)

        synthetic = dataset.get_event_by_id(
            "own_goal_for-89dd4f4b-0a70-48d8-a0e7-ac4c"
        )
        assert isinstance(synthetic, OwnGoalForEvent)
        assert synthetic.team != source_shot.team  # beneficiary
        assert synthetic.player is None
        assert synthetic.coordinates == source_shot.coordinates
        assert any(
            isinstance(q, GoalQualifier) for q in (synthetic.qualifiers or [])
        )
```

If `ShotResult` is not yet imported at the top of `test_statsbomb.py`, verify the existing imports cover it (it is already imported, used at line 850).

- [ ] **Step 5.2: Run test to verify it passes**

Run: `pytest kloppy/tests/test_statsbomb.py::TestStatsBombOwnGoalEvent::test_own_goal_for_generator -v`

Expected: PASS — all underlying machinery is in place from Tasks 1-4.

(If this test fails, do not weaken assertions. Diagnose the underlying generator/qualifier issue.)

- [ ] **Step 5.3: Run the full statsbomb test module to check for regressions**

Run: `pytest kloppy/tests/test_statsbomb.py -v`

Expected: PASS for all tests.

- [ ] **Step 5.4: Commit**

```bash
git add kloppy/tests/test_statsbomb.py
git commit -m "$(cat <<'EOF'
test: own_goal_for synthetic event end-to-end via statsbomb fixture

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Final verification and PR

- [ ] **Step 6.1: Run the full test suite for affected areas**

Run from repo root:

```bash
pytest kloppy/tests/test_synthetic_event_generator.py kloppy/tests/test_statsbomb.py -v
```

Expected: all tests PASS.

- [ ] **Step 6.2: Run a broader smoke test across event-related provider tests**

Run:

```bash
pytest kloppy/tests/test_synthetic_event_generator.py kloppy/tests/test_statsbomb.py kloppy/tests/test_korastats.py kloppy/tests/test_statsperform.py -v
```

Expected: all tests PASS. (`__post_init__` runs on every parsed dataset, so this verifies nothing regresses across providers.)

If any failure mentions `player=None` causing crashes, inspect the failing call site — that's a real signal we need to handle, not something to suppress in the generator.

- [ ] **Step 6.3: Push the branch**

```bash
git push -u origin mgp-fork/own-goal-for-event
```

- [ ] **Step 6.4: Open the PR**

```bash
gh pr create --base mgp-fork/v11 --title "add OwnGoalForEvent + GoalQualifier" --body "$(cat <<'EOF'
## Summary
- Adds `GoalQualifier` (BoolQualifier) attached automatically at `EventDataset` construction to every `ShotEvent` with `result == GOAL`.
- Adds `OwnGoalForEvent` and `EventType.OWN_GOAL_FOR`, plus an opt-in `SyntheticOwnGoalForGenerator` invoked via `dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)`.
- After running the generator, a single `GoalQualifier` query returns every goal credited to a team — regular goals via the source shot, own goals via the synthetic event on the beneficiary team.

## Test plan
- [ ] `pytest kloppy/tests/test_synthetic_event_generator.py -v`
- [ ] `pytest kloppy/tests/test_statsbomb.py -v`
- [ ] `pytest kloppy/tests/test_korastats.py kloppy/tests/test_statsperform.py -v`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Return the PR URL.

---

## Self-Review

**Spec coverage:**
- New `GoalQualifier` (BoolQualifier subclass) → Task 1.4 ✓
- New `OwnGoalForEvent` + `EventType.OWN_GOAL_FOR` → Task 1.3, 1.5 ✓
- `EventFactory.build_own_goal_for` → Task 2 ✓
- Post-load `GoalQualifier` attachment in `EventDataset.__post_init__` → Task 3 ✓
- `SyntheticOwnGoalForGenerator` + `add_synthetic_event` wire-up → Task 4 ✓
- Tests: GoalQualifier attachment → Task 3 ✓; generator (no own goals / one own goal / idempotent) → Task 4 ✓; provider parser test → Task 5 ✓
- Idempotence guarantees → Task 3 (qualifier) and Task 4 (generator) both have idempotence tests ✓
- `__all__` updated → Task 1.6 ✓
- No changes to provider deserializers → confirmed ✓
- No changes to `Event` base typing → confirmed ✓

**Placeholder scan:** No "TBD"/"TODO"/"add appropriate error handling"/etc. All code blocks contain runnable code.

**Type/name consistency:**
- `GoalQualifier(value=True)` constructed consistently across Tasks 3, 4, 5.
- `event_id` format `own_goal_for-<source_id>` consistent in Task 4 generator and Task 5 assertion.
- `EventType.OWN_GOAL_FOR` value `"OWN_GOAL_FOR"` consistent.
- `event_name = "own_goal_for"` consistent.
- `SyntheticOwnGoalForGenerator` class name consistent across module, import path, and registration.
