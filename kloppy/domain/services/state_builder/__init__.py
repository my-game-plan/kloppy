from dataclasses import replace
from typing import List

from kloppy.domain import EventDataset

# register all of them
from . import builders as _builders  # noqa: F401
from .registered import create_state_builder

def _apply_single_state_builder(dataset: EventDataset, builder_key: str) -> EventDataset:
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
    Add state sequentially.
    First builder enriches the dataset,
    the second builder sees the results of the first, etc.
    """
    if len(builder_keys) == 1 and isinstance(builder_keys[0], list):
        builder_keys = builder_keys[0]

    for builder_key in builder_keys:     # <-- sequential loop
        dataset = _apply_single_state_builder(dataset, builder_key)

    return dataset