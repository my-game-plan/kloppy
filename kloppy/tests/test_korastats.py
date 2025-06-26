from collections import defaultdict
from datetime import timedelta
from typing import cast

import pytest

from kloppy import korastats
from kloppy.domain import (
    BallState,
    BodyPart,
    BodyPartQualifier,
    CarryResult,
    DuelQualifier,
    DuelResult,
    DuelType,
    EventDataset,
    FormationType,
    InterceptionResult,
    Orientation,
    PassResult,
    Point,
    Point3D,
    Provider,
    SetPieceQualifier,
    SetPieceType,
    ShotResult,
    SubstitutionEvent,
    Time,
)
from kloppy.domain.models import PositionType
from kloppy.domain.models.event import (
    EventType,
    GoalkeeperActionType,
    GoalkeeperQualifier,
    PassQualifier,
    PassType,
)


@pytest.fixture(scope="module")
def dataset(base_dir) -> EventDataset:
    dataset = korastats.load(
        event_data=base_dir / "files" / "korastats_events.json",
        squads_data=base_dir / "files" / "korastats_squads.json",
        coordinates="korastats",
    )

    return dataset


class TestKoraStatsMetadata:
    """Tests related to deserializing metadata"""

    def test_provider(self, dataset):
        """It should set the KoraStats provider"""
        assert dataset.metadata.provider == Provider.KORASTATS
