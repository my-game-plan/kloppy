from kloppy.config import get_config
from kloppy.infra.serializers.event.korastats import (
    KoraStatsDeserializer,
    KoraStatsInputs,
)
from kloppy.domain import EventDataset, Optional, List, EventFactory
from kloppy.io import open_as_file, FileLike, Source


def load(
    event_data: FileLike,
    squads_data: FileLike,
    home_formation_data: Optional[FileLike] = None,
    away_formation_data: Optional[FileLike] = None,
    event_types: Optional[List[str]] = None,
    coordinates: Optional[str] = None,
    event_factory: Optional[EventFactory] = None,
    exclude_penalty_shootouts: bool = False,
) -> EventDataset:
    """
    Load KoraStats event data into a [`EventDataset`][kloppy.domain.models.event.EventDataset]

    Parameters:
        event_data: filename of json containing the events
        squads_data: filename of json containing the lineup information
        home_formation_data: optional json of the home team's MatchFormation feed,
            used for the starting formation
        away_formation_data: optional json of the away team's MatchFormation feed,
            used for the starting formation
        event_types:
        coordinates:
        event_factory:
    """
    deserializer = KoraStatsDeserializer(
        event_types=event_types,
        coordinate_system=coordinates,
        event_factory=event_factory or get_config("event_factory"),
        exclude_penalty_shootouts=exclude_penalty_shootouts,
    )
    with open_as_file(event_data) as event_data_fp, open_as_file(
        squads_data
    ) as squads_data_fp, open_as_file(
        Source.create(home_formation_data, optional=True)
    ) as home_formation_data_fp, open_as_file(
        Source.create(away_formation_data, optional=True)
    ) as away_formation_data_fp:
        return deserializer.deserialize(
            inputs=KoraStatsInputs(
                event_data=event_data_fp,
                meta_data=squads_data_fp,
                home_formation_data=home_formation_data_fp,
                away_formation_data=away_formation_data_fp,
            )
        )
