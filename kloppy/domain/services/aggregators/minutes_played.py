from dataclasses import dataclass
from datetime import timedelta
from typing import List, NamedTuple, Optional

from kloppy.domain import EventDataset, Player, Team, Time, PositionType
from kloppy.domain.services.aggregators.aggregator import (
    EventDatasetAggregator,
)
from enum import Enum
class BreakdownKey(str, Enum):
    POSITION = "position"
    POSSESSION_STATE = "possession_state"

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

    def aggregate(
        self, dataset: EventDataset
    ) -> List[MinutesPlayed]:
        items = []

        for team in dataset.metadata.teams:
            if self.breakdown_key == BreakdownKey.POSITION:
                pass
            elif self.breakdown_key == BreakdownKey.POSSESSION_STATE:
                # To Do
                pass
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