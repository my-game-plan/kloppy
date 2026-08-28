from abc import ABC, abstractmethod

from kloppy.domain import EventDataset

# Estimated velocity of a pass, in meters per second. Used to place the ball's
# arrival when a provider does not measure it.
PASS_VELOCITY_ESTIMATE_MS = 13


class SyntheticEventGenerator(ABC):
    @abstractmethod
    def add_synthetic_event(self, dataset: EventDataset) -> EventDataset:
        raise NotImplementedError
