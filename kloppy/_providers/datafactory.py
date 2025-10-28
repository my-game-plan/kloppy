from kloppy.config import get_config
from kloppy.infra.serializers.event.datafactory import (
    DatafactoryDeserializer,
    DatafactoryInputs,
)
from kloppy.domain import EventDataset, Optional, List, EventFactory
from kloppy.io import open_as_file, FileLike


def load(
    event_data: FileLike,
    event_types: Optional[List[str]] = None,
    coordinates: Optional[str] = None,
    event_factory: Optional[EventFactory] = None,
    exclude_penalty_shootouts: bool = False,
) -> EventDataset:
    """
    Load DataFactory event data into a [`EventDataset`][kloppy.domain.models.event.EventDataset]

    Args:
        event_data: JSON feed with the raw event data of a game.
        event_types: A list of event types to load.
        coordinates: The coordinate system to use.
        event_factory: A custom event factory.
        exclude_penalty_shootouts: If True, excludes events from penalty shootouts (period 5).

    Returns:
        The parsed event data.
    """
    deserializer = DatafactoryDeserializer(
        event_types=event_types,
        coordinate_system=coordinates,
        event_factory=event_factory or get_config("event_factory"),
        exclude_penalty_shootouts=exclude_penalty_shootouts,
    )
    with open_as_file(event_data) as event_data_fp:
        return deserializer.deserialize(
            inputs=DatafactoryInputs(event_data=event_data_fp),
        )
