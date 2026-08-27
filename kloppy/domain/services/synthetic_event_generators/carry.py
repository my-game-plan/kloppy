from datetime import timedelta
from typing import Optional

from kloppy.domain import (
    EventDataset,
    BodyPart,
    CarryResult,
    Unit,
    EventFactory,
    PassEvent,
    ShotEvent,
    TakeOnEvent,
    InterceptionEvent,
    DuelEvent,
    RecoveryEvent,
    MiscontrolEvent,
    GoalkeeperEvent,
    GenericEvent,
)
from kloppy.domain.models.event import PassResult, PressureEvent, SetPieceQualifier
from kloppy.domain.services.synthetic_event_generators.synthetic_event_generator import (
    SyntheticEventGenerator,
)

VALID_EVENT = (
    PassEvent,
    ShotEvent,
    TakeOnEvent,
    InterceptionEvent,
    DuelEvent,
    RecoveryEvent,
    MiscontrolEvent,
    GoalkeeperEvent,
)


class SyntheticCarryGenerator(SyntheticEventGenerator):
    def __init__(self, event_factory: Optional[EventFactory] = None, **kwargs):
        self.event_factory = event_factory or EventFactory()
        self.min_length_meters = kwargs.get("min_length_meters") or 3
        self.max_length_meters = kwargs.get("max_length_meters") or 60
        self.max_duration = kwargs.get("max_duration") or timedelta(seconds=10)
        self.max_speed_mps = kwargs.get("max_speed_mps") or 12.0
        # an estimate of the velocity of a pass (expressed in meters/second),
        # matching SyntheticBallReceiptGenerator
        self.pass_velocity_estimate_ms = (
            kwargs.get("pass_velocity_estimate_ms") or 13
        )

    def _estimated_arrival(self, event, pitch):
        """When the ball plausibly reached the receiver, from its flight time.

        Used when the provider's own arrival time is not usable because it was
        taken from the next action rather than measured.
        """
        receiver_coordinates = getattr(event, "receiver_coordinates", None)
        if receiver_coordinates is None or event.coordinates is None:
            return event.timestamp
        return event.timestamp + timedelta(
            seconds=pitch.distance_between(
                event.coordinates, receiver_coordinates, Unit.METERS
            )
            / self.pass_velocity_estimate_ms
        )

    def add_synthetic_event(self, dataset: EventDataset) -> EventDataset:
        pitch = dataset.metadata.pitch_dimensions

        for idx, event in enumerate(dataset.events):
            if not isinstance(event, VALID_EVENT):
                continue
            if isinstance(event, PassEvent) and event.result != PassResult.COMPLETE:
                continue
            idx_plus = 1
            next_event = None
            while idx + idx_plus < len(dataset.events):
                next_event = dataset.events[idx + idx_plus]

                if isinstance(next_event, (GenericEvent, PressureEvent)):
                    idx_plus += 1
                    continue
                else:
                    break

            if not isinstance(next_event, VALID_EVENT):
                continue
            if not event.team.team_id == next_event.team.team_id:
                continue
            if next_event.get_qualifier_value(SetPieceQualifier) is not None:
                continue
            if hasattr(event, "end_coordinates"):
                last_coord = event.end_coordinates
            elif hasattr(event, "receiver_coordinates"):
                last_coord = event.receiver_coordinates
            else:
                last_coord = event.coordinates

            new_coord = next_event.coordinates

            distance_meters = pitch.distance_between(
                new_coord, last_coord, Unit.METERS
            )
            # Not far enough
            if distance_meters < self.min_length_meters:
                continue
            # Too far
            if distance_meters > self.max_length_meters:
                continue

            dt = next_event.timestamp - event.timestamp
            # not same phase
            if dt > self.max_duration:
                continue
            # not same period
            if not event.period.id == next_event.period.id:
                continue

            # not headed shot
            if isinstance(next_event, ShotEvent) and any(
                qualifier.name == "body_part"
                and qualifier.value in [BodyPart.HEAD, BodyPart.HEAD_OTHER]
                for qualifier in next_event.qualifiers or []
            ):
                continue

            if (
                hasattr(event, "end_timestamp")
                and event.end_timestamp is not None
            ):
                last_timestamp = event.end_timestamp
            elif (
                hasattr(event, "receive_timestamp")
                and event.receive_timestamp is not None
            ):
                last_timestamp = event.receive_timestamp
            else:
                last_timestamp = (
                    event.timestamp
                    + (next_event.timestamp - event.timestamp) / 10
                )

            # Some providers stamp the ball's arrival at the moment of the next
            # action rather than when it actually arrived - Opta does this for
            # every completed pass, since `receive_timestamp` is taken from the
            # next on-ball event. That leaves no room for the carry in between,
            # so it would be emitted with zero (or negative) duration and an
            # infinite implied speed. Fall back to the ball's estimated flight
            # time, the same estimate the ball-receipt generator uses.
            if last_timestamp >= next_event.timestamp:
                last_timestamp = min(
                    self._estimated_arrival(event, pitch),
                    next_event.timestamp,
                )

            carry_duration = next_event.timestamp - last_timestamp
            # implausible speed (teleport between disconnected events), and
            # zero-length carries the estimate above could not rescue
            carry_seconds = carry_duration.total_seconds()
            if carry_seconds <= 0:
                continue
            if distance_meters / carry_seconds > self.max_speed_mps:
                continue

            generic_event_args = {
                "event_id": f"carry-{event.event_id}",
                "coordinates": last_coord,
                "team": next_event.team,
                "player": next_event.player,
                "ball_owning_team": next_event.ball_owning_team,
                "ball_state": event.ball_state,
                "period": next_event.period,
                "timestamp": last_timestamp,
                "raw_event": None,
            }
            carry_event_args = {
                "result": CarryResult.COMPLETE,
                "qualifiers": None,
                "end_coordinates": new_coord,
                "end_timestamp": next_event.timestamp,
            }
            new_carry = self.event_factory.build_carry(
                **carry_event_args, **generic_event_args
            )
            dataset.insert(new_carry, before_event_id=next_event.event_id)
        return dataset
