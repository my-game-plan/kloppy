import collections
import json
import warnings
from collections import OrderedDict
from dataclasses import replace
from typing import Dict, List, NamedTuple, IO, Optional, Tuple
from datetime import timedelta, datetime
import logging

from kloppy.domain import (
    EventDataset,
    Team,
    Period,
    Point,
    BallState,
    DatasetFlag,
    Orientation,
    PassResult,
    ShotResult,
    EventType,
    Ground,
    Score,
    Provider,
    Metadata,
    Player,
    SetPieceQualifier,
    SetPieceType,
    BodyPartQualifier,
    BodyPart,
    Qualifier,
    CardType,
    PositionType,
    Official,
    OfficialType,
    FormationType,
    SubstitutionEvent,
    Event,
    PassQualifier,
    PassType,
    PassEvent,
    ShotEvent,
    PitchDimensions,
    CoordinateSystem,
)
from kloppy.exceptions import DeserializationError
from kloppy.infra.serializers.event.deserializer import EventDataDeserializer
from kloppy.infra.serializers.event.korastats.specification import (
    create_korastats_events,
    event_decoder,
)
from kloppy.utils import performance_logging

logger = logging.getLogger(__name__)

position_types_mapping: Dict[str, PositionType] = {
    "GK": PositionType.Goalkeeper,
    "SW": PositionType.CenterBack,
    "LB": PositionType.LeftBack,
    "LCB": PositionType.LeftCenterBack,
    "CB": PositionType.CenterBack,
    "RCB": PositionType.RightCenterBack,
    "RB": PositionType.RightBack,
    "LWB": PositionType.LeftWingBack,
    "RWB": PositionType.RightWingBack,
    "LDM": PositionType.LeftDefensiveMidfield,
    "DM": PositionType.CenterDefensiveMidfield,
    "RDM": PositionType.RightDefensiveMidfield,
    "LCM": PositionType.LeftCentralMidfield,
    "CM": PositionType.CenterMidfield,
    "RCM": PositionType.RightCentralMidfield,
    "LM": PositionType.LeftMidfield,
    "RM": PositionType.RightMidfield,
    "LAM": PositionType.LeftAttackingMidfield,
    "AM": PositionType.CenterAttackingMidfield,
    "RAM": PositionType.RightAttackingMidfield,
    "LW": PositionType.LeftWing,
    "SS": PositionType.Striker,
    "RW": PositionType.RightWing,
    "LCF": PositionType.LeftForward,
    "CF": PositionType.Striker,
    "RCF": PositionType.RightForward,
}


def parse_formation(raw_formation: Optional[str]) -> FormationType:
    """Convert a KoraStats formation string into a `FormationType`.

    KoraStats writes formations goalkeeper-first and without separators, so
    "1-433" is a 4-3-3 and "1-4240" a 4-2-4-0. Strings that do not describe a
    goalkeeper plus ten outfield players are treated as missing, since the
    provider also emits partial ones (e.g. "1-53", " - ").
    """
    if not raw_formation:
        return FormationType.UNKNOWN

    lines = raw_formation.strip()
    if not lines.startswith("1-"):
        logger.warning(f"Unexpected KoraStats formation {raw_formation!r}")
        return FormationType.UNKNOWN

    lines = lines[2:]
    if not lines.isdigit() or sum(int(line) for line in lines) != 10:
        logger.warning(
            f"KoraStats formation {raw_formation!r} does not describe eleven players"
        )
        return FormationType.UNKNOWN

    try:
        return FormationType("-".join(lines))
    except ValueError:
        logger.warning(f"Unknown KoraStats formation {raw_formation!r}")
        return FormationType.UNKNOWN


def parse_starting_formations(
    formation_data: List[Optional[IO[bytes]]],
) -> Dict[str, FormationType]:
    """Map team id to starting formation from the MatchFormation feeds.

    Each feed covers a single team and names it, so the formations are keyed by
    team id rather than by the order in which the feeds were passed in.
    """
    starting_formations = {}
    for formation_data_fp in formation_data:
        if formation_data_fp is None:
            continue

        formation = json.load(formation_data_fp)
        team_id = formation.get("teamId")
        if team_id is None:
            logger.warning(
                "Skipping KoraStats formation feed without a team id"
            )
            continue

        starting_formations[str(team_id)] = parse_formation(
            formation.get("startingLineupFormation")
        )

    return starting_formations


class KoraStatsInputs(NamedTuple):
    event_data: IO[bytes]
    meta_data: IO[bytes]
    home_formation_data: Optional[IO[bytes]] = None
    away_formation_data: Optional[IO[bytes]] = None


class KoraStatsDeserializer(EventDataDeserializer[KoraStatsInputs]):
    @property
    def provider(self) -> Provider:
        return Provider.KORASTATS

    def deserialize(self, inputs: KoraStatsInputs) -> EventDataset:
        # Initialize coordinate system transformer
        self.transformer = self.get_transformer()

        with performance_logging("load data", logger=logger):
            metadata = json.load(inputs.meta_data)
            event_data = json.load(inputs.event_data)

        raw_events = event_data["events"]
        self.pair_substitutions(raw_events)

        with performance_logging("parse data", logger=logger):
            starting_formations = parse_starting_formations(
                [inputs.home_formation_data, inputs.away_formation_data]
            )
            teams = self.create_teams_and_players(
                metadata, starting_formations
            )

        # Create periods
        with performance_logging("parse periods", logger=logger):
            periods = self.create_periods(raw_events)

        # Create events
        with performance_logging("parse events", logger=logger):
            events = []
            for ix, raw_event in enumerate(raw_events):
                prior_event = raw_events[ix - 1] if ix > 0 else None
                next_event = (
                    raw_events[ix + 1] if ix < len(raw_events) - 1 else None
                )
                korastats_event = event_decoder(raw_event)
                if korastats_event:
                    kloppy_events = korastats_event.set_refs(
                        periods, teams
                    ).deserialize(
                        self.event_factory, teams, prior_event, next_event
                    )
                    for event in kloppy_events:
                        if self.should_include_event(event):
                            # Transform event to the coordinate system
                            event = self.transformer.transform_event(event)
                            events.append(event)

            self.mark_events_as_assists(events)

        metadata = Metadata(
            teams=teams,
            periods=periods,
            pitch_dimensions=self.transformer.get_to_coordinate_system().pitch_dimensions,
            orientation=Orientation.ACTION_EXECUTING_TEAM,
            flags=DatasetFlag.BALL_OWNING_TEAM | DatasetFlag.BALL_STATE,
            provider=Provider.KORASTATS,
            coordinate_system=self.transformer.get_to_coordinate_system(),
        )
        dataset = EventDataset(metadata=metadata, records=events)
        dataset = self.remove_penalty_shootout_data(dataset)

        return dataset

    @staticmethod
    def create_teams_and_players(
        metadata: Dict,
        starting_formations: Optional[Dict[str, FormationType]] = None,
    ) -> List[Team]:
        starting_formations = starting_formations or {}

        def create_team(team_info: Dict, ground: Ground) -> Team:
            team_id = str(team_info["team"]["id"])

            team = Team(
                team_id=team_id,
                name=team_info["team"]["name"],
                ground=ground,
                starting_formation=starting_formations.get(
                    team_id, FormationType.UNKNOWN
                ),
            )

            players = []
            for player_info in team_info["squad"]:
                starting_position = position_types_mapping[
                    player_info["position"]["name"]
                ]
                players.append(
                    Player(
                        player_id=str(player_info["id"]),
                        team=team,
                        name=player_info["name"],
                        jersey_no=player_info["shirt_number"],
                        starting_position=(
                            starting_position
                            if player_info["lineup"]
                            else None
                        ),
                        starting=True if player_info["lineup"] else False,
                    )
                )

            team.players = players

            return team

        home_team = create_team(metadata["home"], Ground.HOME)
        away_team = create_team(metadata["away"], Ground.AWAY)

        return [home_team, away_team]

    @staticmethod
    def pair_substitutions(raw_events: List[Dict]) -> None:
        """Annotate each SubstituteOut with its replacement player id.

        KoraStats emits a separate SubstituteOut and SubstituteIn event per
        substitution. They are usually adjacent, but when both teams sub at the
        same stoppage the pairs get bracketed (two SubstituteOut events before
        their SubstituteIn events), so the out/in pair is no longer adjacent.
        Pair each out with the nearest unconsumed in of the same team in the
        same half and store the replacement on the out event, so the
        deserializer never has to rely on adjacency.
        """
        sub_ins_by_team = collections.defaultdict(list)
        for ix, event in enumerate(raw_events):
            if event.get("extra") == "SubstituteIn":
                sub_ins_by_team[event.get("team_id")].append(ix)

        consumed = set()
        for ix, event in enumerate(raw_events):
            if event.get("extra") != "SubstituteOut":
                continue
            best = None
            for j in sub_ins_by_team.get(event.get("team_id"), []):
                if j in consumed or raw_events[j].get("half") != event.get(
                    "half"
                ):
                    continue
                if best is None or abs(j - ix) < abs(best - ix):
                    best = j
            if best is not None:
                consumed.add(best)
                event["_replacement_player_id"] = raw_events[best]["player_id"]

    @staticmethod
    def create_periods(raw_events: List[Dict]) -> List[Period]:
        periods = []

        for idx, raw_event in enumerate(raw_events):
            next_period_id = None
            if (idx + 1) < len(raw_events):
                next_event = raw_events[idx + 1]
                next_period_id = next_event["half"]

            timestamp = timedelta(seconds=raw_event["timeInSec"])
            period_id = raw_event["half"]

            if len(periods) == 0 or periods[-1].id != period_id:
                periods.append(
                    Period(
                        id=period_id,
                        start_timestamp=(
                            timedelta(seconds=0)
                            if len(periods) == 0
                            else periods[-1].end_timestamp
                        ),
                        end_timestamp=None,
                    )
                )

            if next_period_id != period_id:
                if len(periods) == 1:
                    periods[-1] = replace(
                        periods[-1],
                        end_timestamp=timestamp,
                    )
                else:
                    periods[-1] = replace(
                        periods[-1],
                        end_timestamp=periods[-2].end_timestamp + timestamp,
                    )

        return periods

    @staticmethod
    def mark_events_as_assists(events: List[Event]):
        for ix, event in enumerate(events):
            for i in range(1, 3):
                if event.event_type == EventType.SHOT and ix > i - 1:
                    potential_assist_event = events[ix - i]
                    is_pass_event = (
                        potential_assist_event.event_type == EventType.PASS
                    )
                    # For own goals the shot is attributed to the conceding
                    # team, but the assisting pass comes from the opponent.
                    if event.result == ShotResult.OWN_GOAL:
                        is_assisting_team_event = (
                            event.team != potential_assist_event.team
                        )
                    else:
                        is_assisting_team_event = (
                            event.team == potential_assist_event.team
                        )
                    if is_pass_event and is_assisting_team_event:
                        potential_assist_event.qualifiers.append(
                            PassQualifier(value=PassType.SHOT_ASSIST)
                        )
                        break
