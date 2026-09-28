from typing import Optional

from kloppy.domain import (
    EventDataset,
    EventFactory,
    Orientation,
    Point,
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

            # The shot is in the own-goal scorer's team's attacking frame.
            # With a per-team orientation the beneficiary attacks the other
            # way, so its event is mirrored around the centre spot.
            coordinates = event.coordinates
            if (
                coordinates is not None
                and dataset.metadata.orientation
                == Orientation.ACTION_EXECUTING_TEAM
            ):
                pitch = dataset.metadata.pitch_dimensions
                coordinates = Point(
                    x=pitch.x_dim.min + pitch.x_dim.max - coordinates.x,
                    y=pitch.y_dim.min + pitch.y_dim.max - coordinates.y,
                )

            new_own_goal_for = self.event_factory.build_own_goal_for(
                event_id=new_event_id,
                coordinates=coordinates,
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
