# GoalQualifier + OwnGoalForEvent + OwnGoalForGenerator

**Date:** 2026-05-07
**Branch target:** `mgp-fork/v11`

## Motivation

Kloppy already deserializes own-goal shots with `ShotResult.OWN_GOAL`, but downstream consumers that want to count "goals scored by team X" cannot uniformly query for goals: a goal credited to a team can come either from a successful `ShotEvent` (result=GOAL, on the scoring team) or from an opponent's `ShotEvent` (result=OWN_GOAL, on the opposing team). This design unifies the two by:

1. Adding a `GoalQualifier` that marks any event as "this scored a goal for the team owning this event."
2. Attaching `GoalQualifier` to every `ShotEvent` whose `result == ShotResult.GOAL` at parse time.
3. Adding an opt-in synthetic `OwnGoalForEvent` (carrying `GoalQualifier`) inserted on the beneficiary team after every `OWN_GOAL` shot.

After this change, a single query — "all events whose qualifiers contain `GoalQualifier`" — returns every goal credited to a team, regardless of provider or original event type.

## Scope

- New `GoalQualifier` (BoolQualifier subclass).
- New `OwnGoalForEvent` class and `EventType.OWN_GOAL_FOR` enum member.
- New `EventFactory.build_own_goal_for` builder.
- New `SyntheticOwnGoalForGenerator` registered in `EventDataset.add_synthetic_event`.
- New shared post-load step `EventDataset._attach_goal_qualifiers()` invoked from `EventDataset.__post_init__`.
- Tests covering qualifier attachment, generator behavior (including idempotence), and at least one provider parser end-to-end.

Explicitly **out of scope:**

- No changes to provider deserializers.
- No changes to `Event` base class typing.
- No new generator config knobs.
- No refactor of `synthetic_event_generators/` directory layout.

## Design

### 1. `GoalQualifier`

`kloppy/domain/models/event.py`, near `CounterAttackQualifier`:

```python
@dataclass
class GoalQualifier(BoolQualifier):
    """
    Marks an event that scored a goal for the team owning this event.

    Attached automatically to ShotEvents with result == ShotResult.GOAL,
    and to synthetic OwnGoalForEvents (where the team is the beneficiary
    of an opponent's own goal).

    Note: ShotEvents with result == ShotResult.OWN_GOAL do NOT receive
    this qualifier — the synthetic OwnGoalForEvent on the opposing team
    carries it instead.
    """
    pass
```

Inheriting `BoolQualifier` gives `name == "goal"` and `to_dict() == {"is_goal": True}` for free.

### 2. `OwnGoalForEvent` and `EventType.OWN_GOAL_FOR`

In `kloppy/domain/models/event.py`:

```python
# In EventType enum
OWN_GOAL_FOR = "OWN_GOAL_FOR"

# Near BallReceiptEvent
@dataclass(repr=False)
@docstring_inherit_attributes(Event)
class OwnGoalForEvent(Event):
    """
    Synthetic event representing a goal credited to a team via an
    opponent's own goal. Inserted after the source ShotEvent whose
    result == ShotResult.OWN_GOAL.

    Attributes:
        event_type (EventType): EventType.OWN_GOAL_FOR
        event_name (str): "own_goal_for"
    """
    event_type: EventType = EventType.OWN_GOAL_FOR
    event_name: str = "own_goal_for"
```

No `result` field. `player` is passed `None` at construction; the base class annotation `player: Player` is not enforced at runtime.

Update `__all__` to export `GoalQualifier` and `OwnGoalForEvent`.

### 3. Post-load `GoalQualifier` attachment

In `EventDataset` (`event.py`):

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

- Runs automatically for every provider via `EventDataset` construction.
- Idempotent: the `any(isinstance(...))` guard prevents duplicates if `__post_init__` runs twice.
- Skips `ShotResult.OWN_GOAL` deliberately.

### 4. `EventFactory.build_own_goal_for`

In `kloppy/domain/services/event_factory.py`:

```python
def build_own_goal_for(self, **kwargs) -> OwnGoalForEvent:
    return create_event(OwnGoalForEvent, **kwargs)
```

Add `OwnGoalForEvent` to imports from `kloppy.domain.models.event`.

### 5. `SyntheticOwnGoalForGenerator`

New file `kloppy/domain/services/synthetic_event_generators/own_goal_for.py`:

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
            dataset.insert(new_own_goal_for, after_event_id=event.event_id)
            existing_ids.add(new_event_id)

        return dataset
```

Notes:
- Iterates a snapshot (`list(dataset.events)`) so newly-inserted events aren't traversed.
- Idempotent via deterministic `event_id` (`own_goal_for-<source_id>`) plus `existing_ids` set check.
- `event_id` collision with the source `event.event_id` is impossible because of the `own_goal_for-` prefix.

### 6. Wire-up in `EventDataset.add_synthetic_event`

Add a branch alongside `CARRY` and `BALL_RECEIPT`:

```python
elif event_type_ == EventType.OWN_GOAL_FOR:
    from kloppy.domain.services.synthetic_event_generators.own_goal_for import (
        SyntheticOwnGoalForGenerator,
    )
    synthetic_event_generator = SyntheticOwnGoalForGenerator(
        event_factory_, **kwargs
    )
```

Update the docstring to list `OWN_GOAL_FOR`.

### 7. Tests

In `kloppy/tests/test_synthetic_event_generator.py`:

**`test_goal_qualifier_attached_to_goal_shots`**
- Load a statsbomb fixture.
- Find every `ShotEvent` with `result == ShotResult.GOAL`; assert each has a `GoalQualifier` in `qualifiers`.
- Find every `ShotEvent` with `result == ShotResult.OWN_GOAL`; assert none has a `GoalQualifier`.

**`test_synthetic_own_goal_for_generator_no_own_goals`**
- Load a statsbomb fixture without own goals (or filter them out).
- Run `dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)`.
- Assert `find_all("own_goal_for")` is empty.

**`test_synthetic_own_goal_for_generator_creates_event`**
- Construct or load a dataset with at least one `OWN_GOAL` shot.
- Run the generator.
- Assert exactly one `OwnGoalForEvent` exists per source own-goal shot.
- Assert each synthetic event:
  - is positioned immediately after the source shot,
  - `team == opponent_team(source.team)`,
  - `player is None`,
  - `coordinates == source.coordinates`,
  - `GoalQualifier` is in `qualifiers`,
  - `related_event_ids == [source.event_id]`.

**`test_synthetic_own_goal_for_generator_is_idempotent`**
- Load same dataset, run generator twice, assert second run produced no additional events (deterministic ids + duplicate guard).

**Provider parser test** — locate a provider whose fixture emits `ShotResult.OWN_GOAL`. Candidates by inspection: statsperform `ma13` (existing fixture under `tests/files/`) or sportec. Add an assertion in that provider's existing test module that, after `add_synthetic_event(EventType.OWN_GOAL_FOR)`, the dataset contains an `OwnGoalForEvent` on the beneficiary team. If no fixture currently has an own goal, the smallest fixture mod is to add a single own-goal entry to an existing fixture rather than create a new one.

## Risk & failure modes

- **Aggregators or serializers crash on `player=None`:** Possible. Mitigation: tests run `to_pandas()` (if applicable) on the post-generator dataset to exercise the full path. If a downstream blowup is found, the smallest fix is at the call site that assumes `event.player is not None`, not the base class.
- **Idempotence breaks if `__post_init__` re-runs after generator inserts events:** No — generator inserts via `dataset.insert(...)` on an existing instance; `__post_init__` does not re-run.
- **Two-team assumption (`opponent_team`):** Football is exactly two teams. Safe.
- **`set_refs` on inserted events:** `dataset.insert()` already handles `prev`/`next_` ref bookkeeping (see `_update_formations_and_positions` callers); no extra handling needed.

## Files changed

- `kloppy/domain/models/event.py` — add enum, qualifier, event class, `_attach_goal_qualifiers`, `__post_init__` override, exports.
- `kloppy/domain/services/event_factory.py` — add `build_own_goal_for`, import.
- `kloppy/domain/services/synthetic_event_generators/own_goal_for.py` — new file.
- `kloppy/tests/test_synthetic_event_generator.py` — three new tests.
- One provider test file — assertion that own-goal fixture produces an OwnGoalForEvent.
- (If needed) one provider fixture — add an own-goal event to an existing fixture.
