from dataclasses import replace
from typing import List

from kloppy.domain import EventDataset

# register all of them
from . import builders as _builders  # noqa: F401
from .registered import create_state_builder

def _apply_single_state_builder(dataset: EventDataset, builder_key: str) -> EventDataset:
    """
    Apply a single state builder to the dataset.

    Arguments:
        dataset: The event dataset to enrich with state.
        builder_key: The key identifying which state builder to use.

    Returns:
        EventDataset with the specified state builder applied to all events.
    """
    builder = create_state_builder(builder_key)
    state = builder.initial_state(dataset)

    events = []
    for event in dataset.events:
        state = builder.reduce_before(state, event)

        # Merge NEW STATE slice into existing event.state
        event_state = event.state
        event_state[builder_key] = state

        events.append(replace(event, state=event_state))

        state = builder.reduce_after(state, event)

    builder.post_process(events)

    return replace(dataset, records=events)
def add_state(dataset: EventDataset, *builder_keys: List[str]) -> EventDataset:
    """
    Add state to events using one or more state builders.

    State builders are applied sequentially: the first builder enriches the dataset,
    and subsequent builders see the results of previous builders.

    Arguments:
        builder_keys: One or more of: 'lineup', 'score', 'sequence', 'formation', 'phase_of_play'

    Examples:
        >>> dataset = dataset.add_state('lineup', 'score')
        >>> dataset = dataset.add_state('sequence', 'phase_of_play')

    Returns:
        [`EventDataset`][kloppy.domain.models.event.EventDataset] with state information attached to events
    """
    if len(builder_keys) == 1 and isinstance(builder_keys[0], list):
        builder_keys = builder_keys[0]

    for builder_key in builder_keys:
        dataset = _apply_single_state_builder(dataset, builder_key)

    return dataset