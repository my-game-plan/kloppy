from datetime import timedelta
from enum import Enum
from typing import Dict, List, Union

from kloppy.domain import (
    BallState,
    BodyPart,
    BodyPartQualifier,
    CardQualifier,
    CardType,
    CarryResult,
    DuelQualifier,
    DuelResult,
    DuelType,
    Event,
    EventFactory,
    GoalkeeperActionType,
    GoalkeeperQualifier,
    InterceptionResult,
    PassQualifier,
    PassResult,
    PassType,
    SetPieceQualifier,
    SetPieceType,
    Team,
    Point,
)
from kloppy.exceptions import DeserializationError
from kloppy.infra.serializers.event.korastats.helpers import (
    get_period_by_id,
    get_team_by_id,
    check_pass_receiver,
)


class EVENT_TYPE(Enum):
    """The list of event types that compose all of KoraStats data."""

    PASS = "Pass"
    LONG_PASS = "LongPass"


class EVENT:
    """Base class for KoraStats events.

    This class is used to deserialize KoraStats events into kloppy events.
    This default implementation is used for all events that do not have a
    specific implementation. They are deserialized into a generic event.

    Args:
        raw_event: The raw JSON event.
    """

    def __init__(self, raw_event: Dict):
        self.raw_event = raw_event

    def set_refs(self, periods, teams, events):
        self.period = get_period_by_id(self.raw_event["half"], periods)
        self.team = (
            get_team_by_id(self.raw_event["team_id"], teams)
            if self.raw_event["team_id"]
            else None
        )
        self.player = (
            self.team.get_player_by_id(self.raw_event["player_id"])
            if self.raw_event["player_id"]
            else None
        )

        return self

    def deserialize(
        self, event_factory: EventFactory, teams: List[Team]
    ) -> List[Event]:
        """Deserialize the event.

        Args:
            event_factory: The event factory to use to build the event.
            periods: The periods in the match.
            teams: The teams in the match.
            events: All events in the match.

        Returns:
            A list of kloppy events.
        """
        generic_event_kwargs = self._parse_generic_kwargs()
        events = self._create_events(
            event_factory, teams, **generic_event_kwargs
        )

        return events

    def _parse_generic_kwargs(self) -> Dict:
        return {
            "period": self.period,
            "timestamp": timedelta(seconds=self.raw_event["timeInSec"]),
            # "ball_owning_team": self.possession_team,
            "ball_state": BallState.ALIVE,
            "event_id": str(self.raw_event["id"]),
            "team": self.team,
            "player": self.player,
            "coordinates": Point(self.raw_event["x"], self.raw_event["y"]),
            # "related_event_ids": self.raw_event.get("related_events", []),
            "raw_event": self.raw_event,
        }

    def _create_events(
        self,
        event_factory: EventFactory,
        teams: List[Team],
        next_event: Dict,
        **generic_event_kwargs,
    ) -> List[Event]:
        generic_event = event_factory.build_generic(
            result=None,
            qualifiers=None,
            event_name=self.raw_event["event"],
            **generic_event_kwargs,
        )
        return [generic_event]


pass_result_mapping = {
    "Success": PassResult.COMPLETE,
    "Fail": PassResult.INCOMPLETE,
}


class PASS(EVENT):
    """KoraStats Pass event."""

    def _create_events(
        self,
        event_factory: EventFactory,
        teams: List[Team],
        next_event: Dict,
        **generic_event_kwargs,
    ) -> List[Event]:
        result = pass_result_mapping[self.raw_event["result"]]
        if result == PassResult.COMPLETE:
            receiver_player, receiver_coordinates = check_pass_receiver(
                self.raw_event, next_event, teams
            )
        else:
            receiver_player = None
            receiver_coordinates = None
        receive_timestamp = None

        pass_event = event_factory.build_pass(
            result=result,
            receive_timestamp=receive_timestamp,
            receiver_coordinates=receiver_coordinates,
            receiver_player=receiver_player,
            **generic_event_kwargs,
        )

        return [pass_event]


def create_korastats_events(
    raw_events: List[Dict],
) -> Dict[str, Union[EVENT, Dict]]:
    korastats_events = {}
    for raw_event in raw_events:
        korastats_events[raw_event["id"]] = event_decoder(raw_event)

    return korastats_events


def event_decoder(raw_event: Dict) -> Union[EVENT, Dict]:
    type_to_event = {
        EVENT_TYPE.PASS: PASS,
        EVENT_TYPE.LONG_PASS: LONG_PASS,
        # EVENT_TYPE.CROSS: CROSS,
        # EVENT_TYPE.CORNER_CROSS: CORNER_CROSS,
        # EVENT_TYPE.CORNER_PASS: CORNER_PASS,
        # EVENT_TYPE.FREEKICK_CROSS: FREEKICK_CROSS,
        # EVENT_TYPE.FREEKICK_PASS: FREEKICK_PASS,
        # EVENT_TYPE.FREEKICK_LONG_PASS: FREEKICK_LONG_PASS,
        # EVENT_TYPE.GOALKICK_PASS: GOALKICK_PASS
        # EVENT_TYPE.GOALKICK_LONG_PASS: GOALKICK_LONG_PASS,
        # EVENT_TYPE.AERIAL_BALL: AERIAL_BALL,
    }
    event_type = EVENT_TYPE(raw_event["actionType"])
    event_creator = type_to_event.get(event_type, EVENT)
    return event_creator(raw_event)
