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
