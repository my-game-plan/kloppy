from dataclasses import dataclass
from datetime import timedelta
from typing import List, NamedTuple, Optional

from kloppy.domain import EventDataset, Player, Team, Time, PositionType, BallState, BallOutEvent, FoulCommittedEvent, \
    ShotEvent, ShotResult, PassResult, PassEvent, SubstitutionEvent, CardEvent, PlayerOnEvent, PlayerOffEvent, \
    TakeOnEvent, TakeOnResult
from kloppy.domain.services.aggregators.aggregator import (
    EventDatasetAggregator,
)
from enum import Enum
class BreakdownKey(Enum):
    POSITION = "position"
    POSSESSION_STATE = "possession_state"

class PossessionState(Enum):
    IN_POSSESSION = 'in-possession'
    OUT_OF_POSSESSION = 'out-of-possession'
    BALL_DEAD = 'ball-dead'


EVENT_TYPES_CAUSING_DEAD_BALL = (
    FoulCommittedEvent,
    SubstitutionEvent,
    CardEvent,
    PlayerOnEvent,
    PlayerOffEvent,
)

@dataclass(frozen=True)
class MinutesPlayedKey:
    player: Optional[Player] = None
    team: Optional[Team] = None
    position: Optional[PositionType] = None

    def __post_init__(self):
        if (self.player is None and self.team is None) or (self.player is not None and self.team is not None):
            raise ValueError("Either 'player' or 'team' must be provided, but not both.")




class MinutesPlayed(NamedTuple):
    key: MinutesPlayedKey
    start_time: Time
    end_time: Time
    duration: timedelta


class MinutesPlayedAggregator(EventDatasetAggregator):
    def __init__(self, breakdown_key: Optional[BreakdownKey] = None):
        self.breakdown_key = breakdown_key

    def get_possession_state(self, ball_state, ball_owning_team, team):
        """Determine the possession state."""
        if ball_state == BallState.DEAD or ball_owning_team is None:
            return PossessionState.BALL_DEAD
        return (
            PossessionState.IN_POSSESSION
            if ball_owning_team == team
            else PossessionState.OUT_OF_POSSESSION
        )

    def finalize_period(self, period, start_time, ball_state, ball_owning_team, team, time_per_possession_state):
        """Finalize the possession state for a period."""
        if not period:
            return
        possession_state = self.get_possession_state(ball_state, ball_owning_team, team)
        end_time = period.end_timestamp-period.start_timestamp
        time_per_possession_state[possession_state] += end_time - start_time


    def aggregate(
        self, dataset: EventDataset
    ) -> List[MinutesPlayed]:
        items = []

        for team in dataset.metadata.teams:
            if self.breakdown_key == BreakdownKey.POSITION:
                pass # no breakdown by position for teams
            elif self.breakdown_key == BreakdownKey.POSSESSION_STATE:
                time_per_possession_state = {
                    state: timedelta(0) for state in PossessionState
                }
                start_time = None
                ball_owning_team = None
                ball_state = None
                period = None
                for event in dataset.events:
                    actual_event_ball_state = (
                        BallState.DEAD
                        if isinstance(event, EVENT_TYPES_CAUSING_DEAD_BALL) or
                           (event.result and event.result.value == PassResult.OFFSIDE)
                        else event.ball_state
                    )
                    if event.period != period:
                        self.finalize_period(period, start_time, ball_state, ball_owning_team, team, time_per_possession_state)
                        start_time = event.timestamp
                        period = event.period
                        ball_state = actual_event_ball_state
                        ball_owning_team = event.ball_owning_team

                    if actual_event_ball_state != ball_state or event.ball_owning_team != ball_owning_team:
                        possession_state = self.get_possession_state(ball_state, ball_owning_team, team)

                        time_per_possession_state[possession_state] += event.timestamp - start_time

                        start_time = event.timestamp
                        ball_state = actual_event_ball_state
                        ball_owning_team = event.ball_owning_team


                # Handle the last event in the period
                self.finalize_period(period, start_time, ball_state, ball_owning_team, team, time_per_possession_state)

            else:
                _start_time = dataset.metadata.periods[0].start_time
                _end_time = dataset.metadata.periods[1].end_time

                items.append(
                    MinutesPlayed(
                        key=MinutesPlayedKey(team=team),
                        start_time=_start_time,
                        end_time=_end_time,
                        duration=_end_time - _start_time,
                    )
                )
            for player in team.players:
                if self.breakdown_key == BreakdownKey.POSITION:
                    for (
                        start_time,
                        end_time,
                        position,
                    ) in player.positions.ranges():
                        items.append(
                            MinutesPlayed(
                                key=MinutesPlayedKey(player=player, position=position),
                                start_time=start_time,
                                end_time=end_time,
                                duration=end_time - start_time,
                            )
                        )
                elif self.breakdown_key == BreakdownKey.POSSESSION_STATE:
                    # To Do
                    pass
                else:
                    _start_time = None
                    end_time = None
                    for (
                            start_time,
                            end_time,
                            position,
                    ) in player.positions.ranges():
                        if not _start_time:
                            _start_time = start_time

                    if _start_time:
                        items.append(
                            MinutesPlayed(
                                key=MinutesPlayedKey(player=player),
                                start_time=_start_time,
                                end_time=end_time,
                                duration=end_time - _start_time,
                            )
                        )

        return items