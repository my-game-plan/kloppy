from datetime import timedelta
from typing import List, NamedTuple, Optional

from kloppy.domain import EventDataset, Player, Team, Time, PositionType
from kloppy.domain.services.aggregators.aggregator import (
    EventDatasetAggregator,
)

class MinutesPlayedKey(NamedTuple):
    player: Optional[Player] = None
    team: Optional[Team] = None
    position: Optional[PositionType] = None

    def __new__(cls, player: Optional[Player] = None, team: Optional[Team] = None, position: Optional[PositionType] = None):
        if (player is None and team is None) or (player is not None and team is not None):
            raise ValueError("Either 'player' or 'team' must be provided, but not both.")
        return super().__new__(cls, player, team, position)


class MinutesPlayed(NamedTuple):
    key: MinutesPlayedKey
    start_time: Time
    end_time: Time
    duration: timedelta


class MinutesPlayedAggregator(EventDatasetAggregator):
    def __init__(self, include_position: bool = False):
        self.include_position = include_position

    def aggregate(
        self, dataset: EventDataset
    ) -> List[MinutesPlayed]:
        items = []

        for team in dataset.metadata.teams:
            for player in team.players:
                if not self.include_position:
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
                else:
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

        return items