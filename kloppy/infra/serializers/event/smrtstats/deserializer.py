import json
import logging
from datetime import timedelta
from typing import Dict, List, Tuple, NamedTuple, IO, Optional

from kloppy.domain import (
    BallOutEvent,
    BodyPart,
    BodyPartQualifier,
    CardEvent,
    CardType,
    CounterAttackQualifier,
    Dimension,
    DuelType,
    DuelQualifier,
    DuelResult,
    Event,
    EventDataset,
    EventType,
    FoulCommittedEvent,
    GenericEvent,
    GoalkeeperQualifier,
    GoalkeeperActionType,
    Ground,
    InterceptionResult,
    Metadata,
    Orientation,
    PassEvent,
    PassQualifier,
    PassResult,
    PassType,
    Period,
    PitchDimensions,
    Player,
    Point,
    Point3D,
    Provider,
    Qualifier,
    RecoveryEvent,
    SetPieceQualifier,
    SetPieceType,
    ShotEvent,
    ShotResult,
    TakeOnEvent,
    TakeOnResult,
    Team,
    FormationType,
    Score,
    BallState,
    PositionType,
)
from kloppy.exceptions import DeserializationError
from kloppy.utils import performance_logging

from ..deserializer import EventDataDeserializer

FORMATIONS = {
    111: FormationType.FOUR_ONE_FOUR_ONE,
    106: FormationType.THREE_FIVE_TWO,
    105: FormationType.THREE_FIVE_TWO,
    103: FormationType.THREE_THREE_THREE_ONE,
    96: FormationType.FOUR_FOUR_TWO,
    90: FormationType.THREE_FOUR_THREE,
    82: FormationType.FOUR_TWO_THREE_ONE,
    16: FormationType.FOUR_FOUR_TWO,
    3: FormationType.FOUR_THREE_THREE,
}

POSITIONS = {
    4: PositionType.Goalkeeper,  # GK
    5: PositionType.LeftCenterBack,  # LCD
    6: PositionType.RightCenterBack,  # RCD
    7: PositionType.RightBack,  # RD
    8: PositionType.LeftBack,  # LD
    9: PositionType.LeftCentralMidfield,  # LCM
    10: PositionType.CenterDefensiveMidfield,  # CDM
    11: PositionType.RightCentralMidfield,  # RCM
    12: PositionType.Striker,  # CF
    13: PositionType.LeftAttackingMidfield,  # LAM
    14: PositionType.RightAttackingMidfield,  # RAM
    # 15: None,  # Substitute Player
    17: PositionType.CenterAttackingMidfield,  # CAM
    18: PositionType.RightMidfield,  # RM
    19: PositionType.LeftMidfield,  # LM
    20: PositionType.Striker,  # LCF
    21: PositionType.Striker,  # RCF
    83: PositionType.RightDefensiveMidfield,  # RCDM
    84: PositionType.LeftDefensiveMidfield,  # LCDM
    91: PositionType.RightDefensiveMidfield,  # RDM
    92: PositionType.LeftAttackingMidfield,  # LCAM
    93: PositionType.CenterBack,  # CB
    94: PositionType.RightAttackingMidfield,  # RCAM
    95: PositionType.LeftDefensiveMidfield,  # LDM
    112: PositionType.CentralMidfield,  # CM
    198: PositionType.LeftForward,  # LF
    199: PositionType.RightForward,  # RF
}

BODY_PARTS = {
    1: BodyPart.RIGHT_FOOT,
    2: BodyPart.LEFT_FOOT,
    3: BodyPart.HEAD,
    4: BodyPart.OTHER,
    5: BodyPart.OTHER,
}
SET_PIECES = {
    1: None,  # Open-play
    2: SetPieceType.THROW_IN,
    3: SetPieceType.FREE_KICK,  # Indirect free kick
    4: SetPieceType.FREE_KICK,  # Free-kick attack
    5: SetPieceType.CORNER_KICK,
    6: SetPieceType.PENALTY,
    7: None,  # Broadcast interruption
    8: SetPieceType.GOAL_KICK,
}

FIRST_HALF = 1
ACCURATE_PASS = 2
BALL_RECEIVING = 25
INACCURATE_PASS = 26
LOST_BALL = 27
PASS_INTERCEPTION = 28
RECOVERED_BALL = 29
AERIAL_DUEL = 30
BALL_OUT_OF_THE_FIELD = 33
DUEL = 34
PICKING_UP = 35
INACCURATE_KEY_PASS = 36
TACKLE = 38
DRIBBLING = 39
INACCURATE_CROSS = 40
GK_INTERCEPTION_PLUS = 41
SHOT_WIDE = 44
DRIBBLE_PAST_OPPONENT_MINUS = 45
OFFSIDE = 47
CREATED_OFFSIDE_TRAP = 48
DRIBBLE_PAST_OPPONENT_PLUS = 50
FOUL = 51
BAD_BALL_CONTROL = 52
BLOCKED_SHOT = 53
YELLOW_CARD = 55
ACCURATE_CROSS = 57
ACCURATE_KEY_PASS = 58
GS_OPP_CREATED = 59
GRAVE_MISTAKE = 61
GK_INTERCEPTION_MINUS = 62
GS_OPP_NOT_SCORED = 63
GS_OPPORTUNITY_MINUS = 64
GOAL = 65
GS_OPPORTUNITY_PLUS = 66
GS_OPP_SCORED = 68
GRAVE_GOAL_MISTAKE = 69
SHOT_ON_TARGET = 70
EFFECTIVE_SAVE = 71
CROSS_INTERCEPTION = 73
HALF_TIME = 74
SECOND_HALF = 75
SUBSTITUTION = 77
ASSIST = 79
FIRST_HALF_ADDITIONAL_TIME_START = 81
SECOND_HALF_ADDITIONAL_TIME_START = 85
RED_CARD = 86
MATCH_END = 89
SHOT_INTO_THE_BAR_POST = 97
BLOCKED_SHOT_BY_FIELD_PLAYER = 98
OWN_GOAL = 100
CROSS = 104
CLEARANCE = 115
TOUCH = 130
KEY_PASS_INTERCEPTION = 201
PASS_INTO_DUEL_PLUS = 202
PASS_INTO_DUEL_MINUS = 203
BOUNCING_SAVE_PLUS = 204
BOUNCING_SAVE_MINUS = 205
YELLOW_RED_CARD = 206

# The markers that delimit periods rather than describe play. Used to tell
# "did anything actually happen between these two seconds?" apart from
# "were there any markers at all?".
PERIOD_BOUNDARY_ACTION_IDS = frozenset(
    {
        FIRST_HALF,
        SECOND_HALF,
        FIRST_HALF_ADDITIONAL_TIME_START,
        SECOND_HALF_ADDITIONAL_TIME_START,
        HALF_TIME,
        MATCH_END,
    }
)

# The `offsets` block of the feed, keyed by period id. It states where each
# period kicks off and ends, and is the only place the feed distinguishes
# the kickoff from the period-start marker. See
# _advance_starts_to_kickoff for when it can be believed.
OFFSET_KEY_BY_PERIOD = {
    1: "1st half",
    2: "2nd half",
    3: "1st half of additional time",
    4: "2nd half of additional time",
    5: "Penalty shootout",
}

# How close the first action of a period must sit to the kickoff the
# offsets block claims, for that claim to be believed. A kickoff pass
# follows the whistle within a second; 3 s absorbs whole-second stamping
# and a first marker that is a touch late without admitting anything that
# is not plausibly the restart itself.
KICKOFF_EVIDENCE_TOLERANCE = 3.0

# ...but a fixed tolerance has no power once the gap is itself that small:
# a claimed kickoff 2 s after the marker sits within 3 s of a first action
# at 0, so a flat test would wave through every small gap without the dead
# zone actually corroborating anything. Scaling the tolerance with the gap
# keeps the test meaningful all the way down, so a 1-2 s correction is
# taken when the evidence really is there and refused when it is not.
KICKOFF_EVIDENCE_RATIO = 0.5

# A period-start marker is stamped by hand, so the gap to the real kickoff
# is an operator's reaction time. Beyond a minute it is something else and
# the offsets block is describing a different timeline, not a late click.
MAX_KICKOFF_ADVANCE = 60.0

# Ball circulation: none of it is possible during a penalty shootout, which
# is kicks, saves and goals and nothing else. Real shootouts (720080,
# 671052) carry only shot, save and goal-state markers, while a half of
# football carries hundreds of passes and receptions. That makes the
# presence of open play a reliable, magnitude-free way to tell a shootout
# from a period of play whose boundary marker is misplaced.
OPEN_PLAY_ACTION_IDS = frozenset(
    {
        ACCURATE_PASS,
        INACCURATE_PASS,
        ACCURATE_KEY_PASS,
        INACCURATE_KEY_PASS,
        PASS_INTERCEPTION,
        KEY_PASS_INTERCEPTION,
        BALL_RECEIVING,
        LOST_BALL,
        RECOVERED_BALL,
        BAD_BALL_CONTROL,
        TOUCH,
        AERIAL_DUEL,
        DUEL,
        TACKLE,
        DRIBBLING,
        DRIBBLE_PAST_OPPONENT_PLUS,
        DRIBBLE_PAST_OPPONENT_MINUS,
        CROSS,
        ACCURATE_CROSS,
        INACCURATE_CROSS,
        CROSS_INTERCEPTION,
        BALL_OUT_OF_THE_FIELD,
        OFFSIDE,
        CREATED_OFFSIDE_TRAP,
        CLEARANCE,
    }
)

ACTION_IDS_TO_IGNORE = (
    [
        FIRST_HALF,
        RECOVERED_BALL,
        DRIBBLING,
        GS_OPP_CREATED,
        GS_OPP_NOT_SCORED,
        GS_OPPORTUNITY_MINUS,
        GS_OPPORTUNITY_PLUS,
        GS_OPP_SCORED,
        HALF_TIME,
        SECOND_HALF,
        FIRST_HALF_ADDITIONAL_TIME_START,
        SECOND_HALF_ADDITIONAL_TIME_START,
        MATCH_END,
        BALL_OUT_OF_THE_FIELD,
        LOST_BALL,
        CREATED_OFFSIDE_TRAP,
        BLOCKED_SHOT_BY_FIELD_PLAYER,
        BALL_RECEIVING,
        GRAVE_MISTAKE,
        GRAVE_GOAL_MISTAKE,
        ASSIST,  # This is added as a separate event besides the pass
    ]
    + list(FORMATIONS.keys())
    + list(POSITIONS.keys())
)
ACTION_IDS_TO_IGNORE += [TOUCH]

PASS_IDS = [
    ACCURATE_PASS,
    INACCURATE_PASS,
    ACCURATE_KEY_PASS,
    INACCURATE_KEY_PASS,
    CROSS,
    ACCURATE_CROSS,
    INACCURATE_CROSS,
    PASS_INTO_DUEL_PLUS,
    PASS_INTO_DUEL_MINUS,
    ASSIST,
]
PASS_ACCURATE_IDS = [
    ACCURATE_PASS,
    ACCURATE_KEY_PASS,
    ACCURATE_CROSS,
    PASS_INTO_DUEL_PLUS,
]
PASS_INACCURATE_IDS = [
    INACCURATE_PASS,
    INACCURATE_KEY_PASS,
    INACCURATE_CROSS,
    PASS_INTO_DUEL_MINUS,
]
CROSS_IDS = [CROSS, ACCURATE_CROSS, INACCURATE_CROSS]
SHOT_IDS = [
    SHOT_WIDE,
    BLOCKED_SHOT,
    GOAL,
    SHOT_ON_TARGET,
    SHOT_INTO_THE_BAR_POST,
    OWN_GOAL,
]
TWO_PEOPLE_DUEL_IDS = [AERIAL_DUEL, DUEL]
TAKE_ON_IDS = [
    DRIBBLING,
    DRIBBLE_PAST_OPPONENT_PLUS,
    DRIBBLE_PAST_OPPONENT_MINUS,
]
INTERCEPTION_IDS = [
    PASS_INTERCEPTION,
    CROSS_INTERCEPTION,
    KEY_PASS_INTERCEPTION,
]
GOALKEEPER_IDS = [
    GK_INTERCEPTION_PLUS,
    GK_INTERCEPTION_MINUS,
    EFFECTIVE_SAVE,
    BOUNCING_SAVE_PLUS,
    BOUNCING_SAVE_MINUS,
]
CARD_IDS = [YELLOW_CARD, RED_CARD, YELLOW_RED_CARD]
FOUL_IDS = [FOUL, OFFSIDE]

BALL_OWNING_IDS = PASS_IDS + TAKE_ON_IDS + SHOT_IDS

LINEUP_INFORMATION_EVENTS = (
    list(FORMATIONS.keys()) + list(POSITIONS.keys()) + [FIRST_HALF]
)

logger = logging.getLogger(__name__)


def _get_event_fingerprint(raw_event: Dict) -> str:
    """
    Create a content-based fingerprint for an event to detect duplicates.

    This fingerprint includes all meaningful event data except the ID,
    so events with the same content but different IDs will have the same fingerprint.
    """
    fingerprint_fields = [
        raw_event.get("action_id"),
        raw_event.get("creator_id"),
        raw_event.get("creator_team_id"),
        raw_event.get("recipient_id"),
        raw_event.get("second"),
        raw_event.get("relative_coord_x"),
        raw_event.get("relative_coord_y"),
        raw_event.get("relative_coord_x_destination"),
        raw_event.get("relative_coord_y_destination"),
        raw_event.get("set_piece_id"),
        raw_event.get("body_part_id"),
        raw_event.get("gate_coord_x"),
        raw_event.get("gate_coord_y"),
    ]
    return str(tuple(fingerprint_fields))


class SmrtStatsInputs(NamedTuple):
    raw_data: IO[bytes]
    pitch_length: Optional[float] = None
    pitch_width: Optional[float] = None


# Raw coord_* / relative_coord_* values are in metres on smrtstats's
# 105 x 68 pitch. coord_* is in the absolute pitch frame; relative_coord_*
# is in the action-executing team's attacking frame and is either equal to
# the absolute coord ("direct") or mirrored around the pitch centre
# ("mirrored") for every event the team plays.
SMRTSTATS_PITCH_LENGTH = 105
SMRTSTATS_PITCH_WIDTH = 68
_PITCH_DIMS = {"x": SMRTSTATS_PITCH_LENGTH, "y": SMRTSTATS_PITCH_WIDTH}


def _attack_direction_mirrored(raw_event: Dict) -> Optional[bool]:
    """Detect whether ``relative_coord_*`` is mirrored from ``coord_*`` for
    this event. Returns True if mirrored, False if direct, None if neither
    can be determined (e.g. every relative coord is null, or all pairs sit
    on the pitch midpoint where direct and mirrored values coincide).
    """
    for axis in ("x", "y"):
        dim = _PITCH_DIMS[axis]
        for suffix in ("", "_destination"):
            rel = raw_event.get(f"relative_coord_{axis}{suffix}")
            absolute = raw_event.get(f"coord_{axis}{suffix}")
            if rel is None or absolute is None:
                continue
            direct = abs(rel - absolute)
            mirrored = abs(rel - (dim - absolute))
            # Skip ambiguous midpoint where the two interpretations coincide.
            if abs(direct - mirrored) < 1.0:
                continue
            return mirrored < direct
    return None


def _resolve_relative_coord(
    raw_event: Dict, axis: str, is_destination: bool
) -> float:
    """Return ``relative_coord_<axis>[_destination]`` for use as a kloppy
    coordinate.

    Smrtstats emits ``relative_coord_*`` as null when the event sits on the
    boundary of the pitch (x=0/105 or y=0/68); the absolute ``coord_*`` is
    still populated. Recover the relative value from the absolute by
    checking the team's attacking-direction frame on any other non-null
    coord pair on the same event. Falls back to 0 when even the absolute
    is missing (matches the prior behaviour for malformed events).
    """
    suffix = "_destination" if is_destination else ""
    rel = raw_event.get(f"relative_coord_{axis}{suffix}")
    if rel is not None:
        return rel
    absolute = raw_event.get(f"coord_{axis}{suffix}")
    if absolute is None:
        return 0
    mirrored = _attack_direction_mirrored(raw_event)
    if mirrored is None:
        return absolute
    return (_PITCH_DIMS[axis] - absolute) if mirrored else absolute


def _get_event_set_piece_qualifier(
    set_piece_id: Optional[int],
) -> List[SetPieceQualifier]:
    return (
        [SetPieceQualifier(value=SET_PIECES[set_piece_id])]
        if SET_PIECES.get(set_piece_id)
        else []
    )


def _get_event_body_part_qualifier(
    body_part_id: Optional[int],
) -> List[BodyPartQualifier]:
    return (
        [BodyPartQualifier(value=BODY_PARTS[body_part_id])]
        if BODY_PARTS.get(body_part_id)
        else []
    )


def _get_event_qualifiers(raw_event: Dict) -> List[Qualifier]:
    set_piece_qualifiers = _get_event_set_piece_qualifier(
        raw_event["set_piece_id"]
    )
    body_part_qualifiers = _get_event_body_part_qualifier(
        raw_event["body_part_id"]
    )

    return set_piece_qualifiers + body_part_qualifiers


def _parse_take_on(raw_event: Dict, action_id: int) -> Dict:
    if action_id == DRIBBLE_PAST_OPPONENT_PLUS:
        result = TakeOnResult.COMPLETE
    elif action_id == DRIBBLE_PAST_OPPONENT_MINUS:
        result = TakeOnResult.INCOMPLETE
    else:
        result = None

    return dict(result=result, qualifiers=_get_event_qualifiers(raw_event))


def _parse_card(raw_event: Dict, action_id: int) -> Dict:
    qualifiers = _get_event_qualifiers(raw_event)

    if action_id == RED_CARD:
        card_type = CardType.RED
    elif action_id == YELLOW_CARD:
        card_type = CardType.FIRST_YELLOW
    elif action_id == YELLOW_RED_CARD:
        card_type = CardType.SECOND_YELLOW
    else:
        card_type = None

    return dict(result=None, qualifiers=qualifiers, card_type=card_type)


#
#
# def _parse_formation_change(raw_qualifiers: Dict[int, str]) -> Dict:
#     formation_id = int(raw_qualifiers[EVENT_QUALIFIER_TEAM_FORMATION])
#     formation = formations[formation_id]
#
#     return dict(formation_type=formation)


def _parse_shot(raw_event: Dict, action_id: int) -> Dict:
    result = None
    if action_id == OWN_GOAL:
        # Check whether own goal is marked at right position (diff from Opta)
        result = ShotResult.OWN_GOAL
    elif action_id == GOAL:
        result = ShotResult.GOAL
    elif action_id in [BLOCKED_SHOT, BLOCKED_SHOT_BY_FIELD_PLAYER]:
        result = ShotResult.BLOCKED
    elif action_id in [SHOT_WIDE, SHOT_INTO_THE_BAR_POST]:
        result = ShotResult.OFF_TARGET
    elif action_id == SHOT_ON_TARGET:
        result = ShotResult.SAVED

    qualifiers = _get_event_qualifiers(raw_event)
    if (
        result == ShotResult.BLOCKED
        or raw_event["gate_coord_x"] is None
        or raw_event["gate_coord_y"] is None
    ):
        result_coordinates = None
    else:
        result_coordinates = Point3D(
            x=105,
            y=34 + raw_event["gate_coord_x"],
            z=raw_event["gate_coord_y"],
        )

    return dict(
        result=result,
        result_coordinates=result_coordinates,
        qualifiers=qualifiers,
    )


def _get_goalkeeper_qualifiers(action_id: int) -> List[GoalkeeperQualifier]:
    if action_id == PICKING_UP:
        return [GoalkeeperQualifier(value=GoalkeeperActionType.PICK_UP)]
    elif action_id in [
        EFFECTIVE_SAVE,
        BOUNCING_SAVE_PLUS,
        BOUNCING_SAVE_MINUS,
    ]:
        return [GoalkeeperQualifier(value=GoalkeeperActionType.SAVE)]
    elif action_id in [GK_INTERCEPTION_PLUS, GK_INTERCEPTION_MINUS]:
        return [GoalkeeperQualifier(value=GoalkeeperActionType.CLAIM)]
    else:
        return []


def _parse_goalkeeper_events(raw_event: Dict, action_id: int) -> Dict:
    goalkeeper_qualifiers = _get_goalkeeper_qualifiers(action_id)
    overall_qualifiers = _get_event_qualifiers(raw_event)
    qualifiers = goalkeeper_qualifiers + overall_qualifiers

    return dict(result=None, qualifiers=qualifiers)


def _update_recipient_event_kwargs(
    generic_event_kwargs: Dict,
    raw_event: Dict,
    home_team: Team,
    away_team: Team,
) -> Dict:
    recipient_event_kwargs = generic_event_kwargs.copy()
    recipient_event_kwargs["event_id"] = f"opponent_duel-{raw_event['id']}"
    home_recipient_player = home_team.get_player_by_id(
        str(raw_event["recipient_id"])
    )
    away_recipient_player = away_team.get_player_by_id(
        str(raw_event["recipient_id"])
    )
    if home_recipient_player:
        recipient_event_kwargs["player"] = home_recipient_player
        recipient_event_kwargs["team"] = home_team
    elif away_recipient_player:
        recipient_event_kwargs["player"] = away_recipient_player
        recipient_event_kwargs["team"] = away_team
    else:
        logger.warning(f"Unexpected recipient id: {raw_event['recipient_id']}")
        # raise DeserializationError(f"Unexpected recipient id: {raw_event['recipient_id']}")

    return recipient_event_kwargs


def _parse_duel(raw_event: Dict, action_id: int) -> (Dict, Dict):
    duel_qualifiers = []
    if action_id == AERIAL_DUEL:
        duel_qualifiers.append(DuelQualifier(value=DuelType.AERIAL))
    else:
        duel_qualifiers.append(DuelQualifier(value=DuelType.GROUND))
    if action_id == TACKLE:
        duel_qualifiers.append(DuelQualifier(value=DuelType.TACKLE))

    event_qualifiers = _get_event_qualifiers(raw_event)
    qualifiers = duel_qualifiers + event_qualifiers

    duel_won_event_kwargs = dict(
        result=DuelResult.WON,
        qualifiers=qualifiers,
    )
    duel_lost_event_kwargs = dict(
        result=DuelResult.LOST,
        qualifiers=qualifiers,
    )

    return duel_won_event_kwargs, duel_lost_event_kwargs


def _parse_substitution(
    raw_event: Dict, generic_event_kwargs: Dict, team: Team
) -> (Dict, Dict):
    substitution_generic_event_kwargs = generic_event_kwargs.copy()
    player_on = team.get_player_by_id(str(raw_event["creator_id"]))
    player_off = team.get_player_by_id(str(raw_event["recipient_id"]))
    substitution_generic_event_kwargs["player"] = player_off
    substitution_kwargs = dict(
        replacement_player=player_on, result=None, qualifiers=None
    )

    return substitution_kwargs, substitution_generic_event_kwargs


def _parse_interception(raw_event: Dict) -> Dict:
    qualifiers = _get_event_qualifiers(raw_event)
    result = InterceptionResult.SUCCESS

    return dict(
        result=result,
        qualifiers=qualifiers,
    )


def _get_pass_qualifiers(action_id: int) -> List[PassQualifier]:
    qualifiers = []
    if action_id in CROSS_IDS:
        qualifiers.append(PassQualifier(value=PassType.CROSS))
    if action_id == ASSIST:
        qualifiers.append(PassQualifier(value=PassType.ASSIST))

    return qualifiers


def _parse_pass(raw_event: Dict, action_id: int, team: Team) -> Dict:
    result = None
    receiver_player = None
    # We could check whether next event is offside to set PassResult.OFFSIDE
    if action_id in PASS_INACCURATE_IDS:
        result = PassResult.INCOMPLETE
    elif action_id in PASS_ACCURATE_IDS:
        result = PassResult.COMPLETE
        receiver_player = team.get_player_by_id(str(raw_event["recipient_id"]))

    receiver_x = _resolve_relative_coord(raw_event, "x", is_destination=True)
    receiver_y = _resolve_relative_coord(raw_event, "y", is_destination=True)
    receiver_coordinates = Point(x=receiver_x, y=receiver_y)

    event_qualifiers = _get_event_qualifiers(raw_event)
    pass_qualifiers = _get_pass_qualifiers(action_id)

    qualifiers = pass_qualifiers + event_qualifiers

    return dict(
        result=result,
        receiver_coordinates=receiver_coordinates,
        receiver_player=receiver_player,
        receive_timestamp=None,
        qualifiers=qualifiers,
    )


def _advance_starts_to_kickoff(
    bounds: List[Tuple[int, float, float]],
    raw_events: Dict,
    play_seconds: List[float],
) -> List[Tuple[int, float, float]]:
    """Move a period start that was stamped before the ball was kicked.

    In some matches the period-start marker is clicked while the teams are
    still lining up, several seconds before the restart. Since every event
    timestamp is measured from the period start, the whole period then
    reads a few seconds late. Nothing in the data looks wrong - the match
    is internally consistent - and it only surfaces against video, where a
    clip cut at the event's timestamp opens after the action it should
    show. In 765331 (Hoogstraten - Merelbeke) the goals landed 6.9 s and
    11.8 s late against the club's own recording.

    The feed states the correction itself. Its ``offsets`` block gives each
    period's kickoff, and there the *end* values agree with the HALF_TIME
    and MATCH_END markers to within 0.2 s while the starts do not, so the
    block is on the same clock as the markers and disagrees only about
    where periods begin.

    The block cannot simply be believed, though: for matches where
    SmrtStats also deliver the video, it describes the cut they deliver
    rather than the timeline the markers are stamped in, and its starts run
    anywhere from 6 s to a minute ahead of period-start markers that are
    already correct. Adopting those would break periods that are fine.

    What separates the two is the dead zone. If the marker really was
    clicked early, the period opens with a stretch of nothing and the first
    action lands on the claimed kickoff: in 765331 the halves open at 8.33 s
    and 2846.62 s against claimed kickoffs of 8 and 2846. Where the block is
    describing a different cut, the first action sits right after the
    marker instead, seconds before the claimed kickoff. So the start is only
    advanced when the period's first action corroborates it.

    That test is what makes this safe to apply to every SmrtStats feed:
    it fails closed, and a period whose evidence does not line up is left
    exactly as the markers describe it.

    The tolerance scales with the gap so the test keeps its power at small
    ones - a flat window would swallow every 1-2 s claim, since a first
    action at 0 already sits inside it. It earns those small corrections
    rather than assuming them: across 1797 periods, a period whose gap is
    0 opens at a median of 0.0 s and p90 of 1.2 s, and against that
    baseline the corroboration rate runs 2-3x what chance alone would
    give at every gap size, 2-4 s included. A few seconds of sync is worth
    having, and this is the evidence that they are not coincidence.
    """
    offsets = raw_events.get("offsets") or {}
    if not offsets:
        return bounds

    advanced = []
    for pid, start, end in bounds:
        offset_key = OFFSET_KEY_BY_PERIOD.get(pid)
        kickoff = (
            (offsets.get(offset_key) or {}).get("start")
            if offset_key
            else None
        )
        own_play = [second for second in play_seconds if start <= second < end]
        if (
            kickoff is None
            or not start < kickoff < end
            or kickoff - start > MAX_KICKOFF_ADVANCE
            or not own_play
        ):
            advanced.append((pid, start, end))
            continue

        tolerance = min(
            KICKOFF_EVIDENCE_TOLERANCE,
            (kickoff - start) * KICKOFF_EVIDENCE_RATIO,
        )
        if abs(min(own_play) - kickoff) > tolerance:
            advanced.append((pid, start, end))
            continue
        advanced.append((pid, float(kickoff), end))
    return advanced


def _license_period_starts(
    boundaries: List[Tuple[int, float]],
    half_times: List[float],
    list_starts: set,
    open_play_between,
    open_play_after,
) -> List[Tuple[int, float]]:
    """Drop or relocate period starts that no half-time whistle accounts for.

    SmrtStats emits a spurious period-start marker in a meaningful minority
    of matches, and it lands in the middle of the period before it:

    * A stray SECOND_HALF inside the first half (727904 La Guaira-Bolivar
      at 2375 while the first half runs to 2818; 723555 at 2720 of 2997;
      687101 at 2595 of 3004). The claimed second half then swallows the
      rest of the first, and the first half is truncated by up to ten
      minutes. 14 of 97 sampled feeds carry this, 1288 events in total.
    * A stray FIRST_HALF_ADDITIONAL_TIME_START (e.g. 699940 at 2870, eleven
      seconds after the restart). The second half collapses to those eleven
      seconds and the real one is relabelled extra time, so anything
      aggregating regulation play loses it.

    The discriminator is not how far the marker sits from the truth. The
    stray markers span 20 s to 585 s from the real boundary, overlapping the
    range of ordinary stamping jitter, and a match whose halves are both
    dumped into ``first_half_markers`` (720080) puts its legitimate
    SECOND_HALF 2744 s before the end of that list. Any threshold on
    distance or on list membership therefore either misses real defects or
    rejects healthy feeds.

    What does separate them is the half-time whistle. Play cannot restart
    without a break, so every period start bar the first is paired with a
    HALF_TIME describing the same instant: the two carry the same second, or
    differ by a few seconds with no play in between. One whistle licenses
    one restart. A start with no whistle left to pair with did not happen.

    An unlicensed start is relocated rather than dropped when an
    unaccounted-for whistle can host it, which needs two independent things
    to agree: the whistle opens one of the marker lists, and open play
    follows it. The first rules out a whistle stamped twice inside
    continuous play (723447 has one on the restart and another eleven
    seconds later, mid-move); the second rules out the final whistle before
    a penalty shootout, which opens ``second_half_markers`` in exactly the
    same way but is followed only by kicks and saves. Where no whistle
    qualifies, the start is dropped and its events fall to the period that
    really contains them.
    """
    if len(boundaries) <= 1:
        return boundaries

    unclaimed = sorted(half_times)
    kept: List[Tuple[int, float]] = [boundaries[0]]
    # Whether the start we last kept has a whistle of its own. Only then can
    # a whistle be "used up", which is what makes the next start suspect.
    previous_has_whistle = False

    for idx in range(1, len(boundaries)):
        pid, start = boundaries[idx]
        next_start = (
            boundaries[idx + 1][1]
            if idx + 1 < len(boundaries)
            else float("inf")
        )

        # 1. The ordinary case: a whistle describing the same instant, in
        #    either stamping order.
        adjacent = None
        for whistle in unclaimed:
            lo, hi = (start, whistle) if start <= whistle else (whistle, start)
            if not open_play_between(lo, hi):
                adjacent = whistle
                break
        if adjacent is not None:
            unclaimed.remove(adjacent)
            kept.append((pid, start))
            previous_has_whistle = True
            continue

        # 2. A whistle inside the period this start claims, corroborated by
        #    a marker list opening there and by play resuming after it. The
        #    start was stamped early; the whistle is the real boundary.
        relocated = None
        for whistle in unclaimed:
            if (
                start < whistle < next_start
                and whistle in list_starts
                and open_play_after(whistle)
            ):
                relocated = whistle
                break
        if relocated is not None:
            unclaimed.remove(relocated)
            kept.append((pid, relocated))
            previous_has_whistle = True
            continue

        # 3. Drop only against positive evidence: the preceding start
        #    already used the whistle that would have to precede this one,
        #    and the ball stayed in play across it. Absent that, keep the
        #    start. Losing a period is far worse than mislabelling one, so
        #    silence in the feed must never cost a period.
        if previous_has_whistle and open_play_between(kept[-1][1], start):
            continue

        kept.append((pid, start))
        previous_has_whistle = False

    # Starts must stay ordered for every downstream boundary calculation.
    kept.sort(key=lambda item: item[1])
    return kept


class SmrtStatsDeserializer(EventDataDeserializer[SmrtStatsInputs]):
    @property
    def provider(self) -> Provider:
        return Provider.SMRTSTATS

    @staticmethod
    def mark_events_as_assists(events: List[Event]):
        """Mark pass events as assists when followed by a shot or goal."""
        for ix, event in enumerate(events):
            for i in range(1, 3):
                if event.event_type == EventType.SHOT and ix > i - 1:
                    potential_assist_event = events[ix - i]
                    is_pass_event = (
                        potential_assist_event.event_type == EventType.PASS
                    )
                    is_same_team_event = (
                        event.team == potential_assist_event.team
                    )
                    if is_pass_event and is_same_team_event:
                        potential_assist_event.qualifiers.append(
                            PassQualifier(value=PassType.SHOT_ASSIST)
                        )
                        if event.result == ShotResult.GOAL:
                            potential_assist_event.qualifiers.append(
                                PassQualifier(value=PassType.ASSIST)
                            )
                        break

    @staticmethod
    def create_team(team_info: Dict, ground: Ground) -> Team:
        team = Team(
            team_id=str(team_info["id"]), name=team_info["name"], ground=ground
        )

        return team

    @staticmethod
    def add_players(
        raw_events: Dict, home_team: Team, away_team: Team
    ) -> (Team, Team):
        def create_player(raw_event: Dict, team: Team) -> Player:
            starting = raw_event["second"] == 0.0
            position = POSITIONS[raw_event["action_id"]] if starting else None
            player_info = raw_event["creator"]
            first_name = player_info["name"]
            last_name = player_info["surname"]
            if first_name and last_name:
                full_name = player_info["name"] + " " + player_info["surname"]
            elif first_name:
                full_name = first_name
            elif last_name:
                full_name = last_name
            else:
                full_name = " "
            player = Player(
                player_id=str(player_info["id"]),
                team=team,
                jersey_no=player_info["number"],
                name=full_name,
                starting_position=position,
                starting=starting,
            )

            return player

        for idx, marker in enumerate(
            ["first_half_markers", "second_half_markers"]
        ):
            half_events = raw_events[marker]
            for event in half_events:
                action_id = event["action_id"]
                if action_id in POSITIONS:
                    if str(event["creator_team_id"]) == home_team.team_id:
                        player = create_player(event, home_team)
                        if player not in home_team.players:
                            home_team.players.append(player)
                    elif str(event["creator_team_id"]) == away_team.team_id:
                        player = create_player(event, away_team)
                        if player not in away_team.players:
                            away_team.players.append(player)
                    else:
                        raise DeserializationError(
                            f"Unexpected team id: {event['creator_team_id']}"
                        )
                elif action_id in FORMATIONS and idx == 0:
                    if str(event["creator_team_id"]) == home_team.team_id:
                        home_team.starting_formation = FORMATIONS[
                            event["action_id"]
                        ]
                    elif str(event["creator_team_id"]) == away_team.team_id:
                        away_team.starting_formation = FORMATIONS[
                            event["action_id"]
                        ]

        return home_team, away_team

    @staticmethod
    def create_periods(raw_events: Dict) -> List[Period]:
        """Build Period objects from the raw SmrtStats marker lists.

        SmrtStats stores events across up to four marker lists
        (``first_half_markers``, ``second_half_markers``,
        ``first_extra_time_markers``, ``second_extra_time_markers``).
        The extra-time lists are duplicates of subsets of
        ``second_half_markers``, which in every observed ET match contains
        the full 2nd-half-onward timeline including extra time and the
        penalty shootout. Two further deviations also occur:

        * Some matches (e.g. 720080 Argentinos-Barcelona, 720083
          Tolima-Tachira) dump both regulation halves into
          ``first_half_markers`` and put only the shootout into
          ``second_half_markers``.
        * MATCH_END (89) is always the final marker regardless of whether
          the match went to extra time or penalties.

        Rather than branch on these layouts, this routine pools markers
        from all four lists, deduplicates by id, and derives periods from
        SmrtStats's five boundary action_ids:

        ==================================================  ============
        action_id                                            Role
        ==================================================  ============
        1   FIRST_HALF                                       P1 start
        75  SECOND_HALF                                      P2 start
        81  FIRST_HALF_ADDITIONAL_TIME_START                 P3 start
        85  SECOND_HALF_ADDITIONAL_TIME_START                P4 start
        74  HALF_TIME                                        period end
        89  MATCH_END                                        dataset end
        ==================================================  ============

        A penalty shootout (P5) is detected when a HALF_TIME marker
        appears after the last period-start marker and non-MATCH_END
        events occur between that HALF_TIME and MATCH_END. P5 covers that
        range.

        HALF_TIME is not reliably ordered against the period-start marker
        it pairs with. Usually the two carry the same ``second``, but in a
        large minority of matches (e.g. 683623 Lens-Nantes, 687100
        Cesena-Padova, 686513 Cardiff-Bolton) HALF_TIME is stamped one to
        seven seconds *after* SECOND_HALF. Since there is only ever one
        HALF_TIME per file for regulation, a naive "first HALF_TIME after
        this period's start" rule then hands the second half a one-second
        end and hands the shootout detector the whole real second half:
        P2 collapses and ~1000 events move into a phantom P5, which
        ``exclude_penalty_shootouts`` (used by every MGP ingest) drops.

        So HALF_TIME markers are classified structurally rather than by a
        tolerance window, on two independent grounds:

        * A HALF_TIME with no play between it and the period start that
          precedes it closes the *previous* period, so it is not a
          candidate end for the period it nominally falls in.
        * A HALF_TIME with no period start after it can only be the final
          whistle, and a shootout is the only thing that may follow one.
          Since a shootout is kicks, saves and goals and contains no ball
          circulation, open play afterwards proves another period follows
          and the marker is misplaced. This catches the cases the first
          rule cannot, where a stray event or two lands inside the gap
          between the restart and its late HALF_TIME.

        Neither test depends on how large the discrepancy is, so neither
        needs tuning as provider noise changes. Both fail in the safe
        direction: at worst a genuine shootout stays inside the preceding
        period, mislabelling a few dozen events instead of discarding a
        half of ~1000.

        The period-start markers are unreliable in their own right, and
        independently of the above: a stray SECOND_HALF or ET1 lands in the
        middle of the period before it, moving a boundary by anything from
        20s to ten minutes. Since a restart needs a break to restart from,
        each start bar the first has to be accounted for by a half-time
        whistle; one whistle accounts for one restart. See
        :func:`_license_period_starts` for how an unaccounted-for start is
        relocated or dropped, and for why it fails open when the feed
        carries no whistles at all.

        Finally the derived boundaries are checked against an invariant
        that cannot silently fail: a period never ends before the last
        event that belongs to it.

        Kloppy convention: P1/P2 = regulation, P3/P4 = extra time,
        P5 = penalty shootout.
        """
        all_marker_keys = (
            "first_half_markers",
            "second_half_markers",
            "first_extra_time_markers",
            "second_extra_time_markers",
        )

        seen_ids: set = set()
        all_markers: List[Dict] = []
        for key in all_marker_keys:
            for event in raw_events.get(key, []) or []:
                event_id = event.get("id")
                if event_id is not None and event_id in seen_ids:
                    continue
                if event_id is not None:
                    seen_ids.add(event_id)
                all_markers.append(event)

        valid_seconds = [
            e["second"] for e in all_markers if e.get("second") is not None
        ]
        if not valid_seconds:
            return []

        def _first_second(action_id: int) -> Optional[float]:
            matches = [
                e["second"]
                for e in all_markers
                if e.get("action_id") == action_id
                and e.get("second") is not None
            ]
            return min(matches) if matches else None

        period_start_action_ids = [
            (1, FIRST_HALF),
            (2, SECOND_HALF),
            (3, FIRST_HALF_ADDITIONAL_TIME_START),
            (4, SECOND_HALF_ADDITIONAL_TIME_START),
        ]
        boundaries: List[Tuple[int, float]] = []
        for pid, aid in period_start_action_ids:
            start = _first_second(aid)
            if start is not None:
                boundaries.append((pid, start))

        # Fall back to the earliest event if no FIRST_HALF marker is present.
        if not boundaries or boundaries[0][0] != 1:
            boundaries.insert(0, (1, min(valid_seconds)))

        half_times = sorted(
            {
                e["second"]
                for e in all_markers
                if e.get("action_id") == HALF_TIME
                and e.get("second") is not None
            }
        )
        match_end_candidates = [
            e["second"]
            for e in all_markers
            if e.get("action_id") == MATCH_END and e.get("second") is not None
        ]
        match_end = min(match_end_candidates) if match_end_candidates else None
        max_second = max(valid_seconds)

        play_seconds = sorted(
            e["second"]
            for e in all_markers
            if e.get("action_id") not in PERIOD_BOUNDARY_ACTION_IDS
            and e.get("second") is not None
        )

        # The second each marker list opens at. SmrtStats splits the match
        # across these lists at the real period boundaries, so a list's
        # first second is independent corroboration for a boundary that the
        # in-band markers disagree about. Only used to confirm a whistle
        # that is already unaccounted for, never on its own: the lists are
        # not trustworthy in general, since ET matches routinely dump both
        # regulation halves into first_half_markers.
        list_starts = set()
        for key in all_marker_keys:
            seconds = [
                e["second"]
                for e in raw_events.get(key, []) or []
                if e.get("second") is not None
            ]
            if seconds:
                list_starts.add(min(seconds))

        def _played_between(lo: float, hi: float) -> bool:
            """Was there any play strictly between ``lo`` and ``hi``?

            Strict on both ends on purpose: the feed is stamped in whole
            seconds, so the last touch of a half routinely shares its
            second with the boundary marker itself.
            """
            return any(lo < second < hi for second in play_seconds)

        period_starts = [start for _, start in boundaries]

        def _closes_previous_period(half_time: float) -> bool:
            """Is this HALF_TIME the late-stamped twin of a period start?

            A HALF_TIME separates play from play. If nothing happened
            between the period start it follows and the HALF_TIME itself,
            then no part of that period elapsed before it, so it cannot be
            that period's end: it is the previous period's end, stamped
            after the restart it should precede.
            """
            preceding = [s for s in period_starts if s <= half_time]
            if not preceding:
                return False
            attached_to = max(preceding)
            if attached_to == period_starts[0]:
                # Nothing precedes the first period, so its HALF_TIME can
                # only be its own end however sparse the feed is.
                return False
            return not _played_between(attached_to, half_time)

        open_play_seconds = sorted(
            e["second"]
            for e in all_markers
            if e.get("action_id") in OPEN_PLAY_ACTION_IDS
            and e.get("second") is not None
        )

        def _open_play_after(second: float) -> bool:
            return any(s > second for s in open_play_seconds)

        def _open_play_between(lo: float, hi: float) -> bool:
            """Was the ball in play strictly between ``lo`` and ``hi``?

            Deliberately narrower than :func:`_played_between`. Asked when
            pairing a period start with its whistle, where the only thing
            that matters is whether football was played in the gap. A
            restart drags a dump of position and formation markers with it,
            and a substitution can be logged a second either side; none of
            that means the half had begun.
            """
            return any(lo < second < hi for second in open_play_seconds)

        def _can_be_the_final_whistle(half_time: float) -> bool:
            """Could the match (bar a shootout) be over at this HALF_TIME?

            Only asked of a HALF_TIME with no period start after it, where
            the alternatives are "final whistle" and "misplaced marker".
            Open play afterwards settles it: a shootout has none, so what
            follows is another period however the markers are stamped.
            """
            return not _open_play_after(half_time)

        # A period start is only real if a half-time whistle accounts for
        # it. See _license_period_starts for why this is checked and how.
        boundaries = _license_period_starts(
            boundaries,
            half_times,
            list_starts,
            _open_play_between,
            _open_play_after,
        )
        period_starts = [start for _, start in boundaries]

        # Only these can end the period they fall in or open a shootout.
        free_half_times = []
        for h in half_times:
            if _closes_previous_period(h):
                continue
            if not any(
                s > h for s in period_starts
            ) and not _can_be_the_final_whistle(h):
                continue
            free_half_times.append(h)

        last_period_start = boundaries[-1][1]
        shootout_start: Optional[float] = None
        ht_after_last_start = [
            h for h in free_half_times if h > last_period_start
        ]
        if ht_after_last_start:
            candidate = ht_after_last_start[0]
            # Confirm a shootout: real events (anything other than the
            # MATCH_END marker itself) between the candidate and the end.
            events_after_candidate = [
                e
                for e in all_markers
                if e.get("second") is not None
                and e["second"] > candidate
                and e.get("action_id") != MATCH_END
            ]
            if events_after_candidate:
                shootout_start = candidate

        def _period_end(start: float, next_start: Optional[float]) -> float:
            if next_start is not None:
                ht_in_range = [
                    h for h in free_half_times if start < h <= next_start
                ]
                if ht_in_range:
                    return ht_in_range[0]
                # No HALF_TIME of its own: the next period's start closes
                # this one. Covers the late-stamped HALF_TIME, which would
                # otherwise land past the restart it belongs before.
                return next_start
            # Last regulation/ET period with no shootout: end at the first
            # HALF_TIME after start, else MATCH_END, else max event second.
            ht_after = [h for h in free_half_times if h > start]
            if ht_after:
                return ht_after[0]
            if match_end is not None:
                return match_end
            return max_second

        bounds: List[Tuple[int, float, float]] = []
        for idx, (pid, start) in enumerate(boundaries):
            if idx + 1 < len(boundaries):
                end = _period_end(start, boundaries[idx + 1][1])
            elif shootout_start is not None:
                end = shootout_start
            else:
                end = _period_end(start, None)
            bounds.append((pid, start, end))

        if shootout_start is not None:
            p5_end = match_end if match_end is not None else max_second
            bounds.append((5, shootout_start, p5_end))

        # Invariant: a period never ends before the last event that belongs
        # to it. A boundary marker landing early truncates a period and
        # sends its events either into the next period or out of the
        # dataset entirely, and nothing downstream can tell that happened.
        # Extending the end is always safe: the following period's start is
        # the ceiling, so no event can change hands.
        checked: List[Tuple[int, float, float]] = []
        for idx, (pid, start, end) in enumerate(bounds):
            ceiling = bounds[idx + 1][1] if idx + 1 < len(bounds) else None
            own_play = [
                second
                for second in play_seconds
                if second >= start and (ceiling is None or second < ceiling)
            ]
            if own_play:
                end = max(end, max(own_play))
            checked.append((pid, start, end))

        # Last, so the evidence is read against boundaries that are already
        # settled: a start still liable to be relocated or dropped would be
        # the wrong thing to measure a kickoff against.
        checked = _advance_starts_to_kickoff(checked, raw_events, play_seconds)

        return [
            Period(
                id=pid,
                start_timestamp=timedelta(seconds=start),
                end_timestamp=timedelta(seconds=end),
            )
            for pid, start, end in checked
        ]

    def deserialize(self, inputs: SmrtStatsInputs) -> EventDataset:
        transformer = self.get_transformer(
            inputs.pitch_length, inputs.pitch_width
        )

        with performance_logging("load data", logger=logger):
            raw_data = json.load(inputs.raw_data)

        match_info = raw_data["match"]
        home_team = self.create_team(match_info["home_team"], Ground.HOME)
        away_team = self.create_team(match_info["away_team"], Ground.AWAY)
        home_team, away_team = self.add_players(raw_data, home_team, away_team)
        teams = {home_team.team_id: home_team, away_team.team_id: away_team}
        periods = self.create_periods(raw_data)
        score = Score(
            home=match_info["home_team_score"],
            away=match_info["away_team_score"],
        )
        possession_team = None

        events = []
        seen_fingerprints = set()
        seen_event_ids = set()
        # Iterate in preference order. For ET matches SmrtStats stores ET
        # events in two lists at once: the extra-time bucket
        # (first_extra_time_markers / second_extra_time_markers) AND
        # second_half_markers. The two copies share the event id but
        # disagree on relative_coord_* because each list encodes
        # coordinates in that period's attacking-direction frame (teams
        # switch ends between the 2nd half and ET1, and again between
        # ET1 and ET2). Iterating ET buckets first and deduping by id
        # ensures each ET event is emitted once, with coordinates in
        # its own period's frame.
        for period_events_title in (
            "first_half_markers",
            "first_extra_time_markers",
            "second_extra_time_markers",
            "second_half_markers",
        ):
            period_events = raw_data.get(period_events_title, []) or []
            for idx, raw_event in enumerate(period_events):
                # Id-based dedup: the same event may appear verbatim in
                # multiple SmrtStats marker lists.
                event_id = raw_event.get("id")
                if event_id is not None and event_id in seen_event_ids:
                    continue
                # Fingerprint-based dedup: SmrtStats also sometimes emits
                # the same content under different ids.
                fingerprint = _get_event_fingerprint(raw_event)
                if fingerprint in seen_fingerprints:
                    logger.debug(
                        f"Skipping duplicate event with id {raw_event['id']}"
                    )
                    continue
                if event_id is not None:
                    seen_event_ids.add(event_id)
                seen_fingerprints.add(fingerprint)
                action_id = raw_event["action_id"]
                action_title = raw_event["action"]["title"].lower()
                if (
                    action_id not in ACTION_IDS_TO_IGNORE
                    and raw_event["creator_team_id"]
                    and raw_event["creator_id"]
                ):
                    team = teams[str(raw_event["creator_team_id"])]
                    player = team.get_player_by_id(
                        str(raw_event["creator_id"])
                    )
                    event_second = raw_event["second"]
                    # Iterate periods in reverse so events on a shared
                    # boundary (e.g. second == HALF_TIME == SECOND_HALF
                    # start) land in the later period.
                    period = next(
                        (
                            p
                            for p in reversed(periods)
                            if p.start_timestamp.total_seconds()
                            <= event_second
                            <= p.end_timestamp.total_seconds()
                        ),
                        min(
                            periods,
                            key=lambda p: min(
                                abs(
                                    event_second
                                    - p.start_timestamp.total_seconds()
                                ),
                                abs(
                                    event_second
                                    - p.end_timestamp.total_seconds()
                                ),
                            ),
                        ),
                    )
                    if action_id in BALL_OWNING_IDS:
                        possession_team = team

                    if (
                        raw_event["coord_x"] is None
                        or raw_event["coord_y"] is None
                    ):
                        pass

                    x = _resolve_relative_coord(
                        raw_event, "x", is_destination=False
                    )
                    y = _resolve_relative_coord(
                        raw_event, "y", is_destination=False
                    )
                    coordinates = Point(x=x, y=y)
                    timestamp = timedelta(
                        seconds=max(
                            0,
                            raw_event["second"]
                            - period.start_timestamp.total_seconds(),
                        )
                    )
                    generic_event_kwargs = dict(
                        period=period,
                        timestamp=timestamp,
                        ball_owning_team=possession_team,
                        ball_state=None,
                        event_id=str(raw_event["id"]),
                        team=team,
                        player=player,
                        coordinates=coordinates,
                        raw_event=raw_event,
                    )

                    if action_id in PASS_IDS:
                        pass_event_args = _parse_pass(
                            raw_event, action_id, team
                        )
                        event = self.event_factory.build_pass(
                            **pass_event_args, **generic_event_kwargs
                        )
                    elif action_id in SHOT_IDS:
                        shot_event_kwargs = _parse_shot(raw_event, action_id)
                        event = self.event_factory.build_shot(
                            **shot_event_kwargs, **generic_event_kwargs
                        )
                    elif action_id in INTERCEPTION_IDS:
                        interception_kwargs = _parse_interception(raw_event)
                        event = self.event_factory.build_interception(
                            **interception_kwargs, **generic_event_kwargs
                        )
                    elif action_id in TAKE_ON_IDS:
                        take_on_kwargs = _parse_take_on(raw_event, action_id)
                        event = self.event_factory.build_take_on(
                            **take_on_kwargs, **generic_event_kwargs
                        )
                    elif action_id == CLEARANCE:
                        event = self.event_factory.build_clearance(
                            **dict(
                                qualifiers=_get_event_qualifiers(raw_event),
                                result=None,
                            ),
                            **generic_event_kwargs,
                        )
                    elif action_id == PICKING_UP:
                        event = self.event_factory.build_recovery(
                            result=None,
                            qualifiers=None,
                            **generic_event_kwargs,
                        )
                    elif action_id in FOUL_IDS:
                        event = self.event_factory.build_foul_committed(
                            result=None,
                            qualifiers=None,
                            **generic_event_kwargs,
                        )
                    elif action_id in CARD_IDS:
                        card_event_kwargs = _parse_card(raw_event, action_id)
                        event = self.event_factory.build_card(
                            **card_event_kwargs,
                            **generic_event_kwargs,
                        )
                    elif action_id in GOALKEEPER_IDS:
                        # EFFECTIVE_SAVE can be performed by field players
                        # In that case, create a recovery event instead
                        # Try to get current position from positions container,
                        # fall back to starting position
                        current_position = player.starting_position

                        if (
                            action_id == EFFECTIVE_SAVE
                            and current_position != PositionType.Goalkeeper
                        ):
                            event = self.event_factory.build_recovery(
                                result=None,
                                qualifiers=_get_event_qualifiers(raw_event),
                                **generic_event_kwargs,
                            )
                        else:
                            goalkeeper_kwargs = _parse_goalkeeper_events(
                                raw_event, action_id
                            )
                            event = self.event_factory.build_goalkeeper_event(
                                **goalkeeper_kwargs, **generic_event_kwargs
                            )
                    elif action_id == TACKLE:
                        (
                            duel_won_event_kwargs,
                            duel_lost_event_kwargs,
                        ) = _parse_duel(raw_event, action_id)
                        event = self.event_factory.build_duel(
                            **duel_won_event_kwargs, **generic_event_kwargs
                        )
                    elif action_id in TWO_PEOPLE_DUEL_IDS:
                        (
                            duel_won_event_kwargs,
                            duel_lost_event_kwargs,
                        ) = _parse_duel(raw_event, action_id)
                        duel_won_event = self.event_factory.build_duel(
                            **duel_won_event_kwargs, **generic_event_kwargs
                        )
                        recipient_generic_event_kwargs = (
                            _update_recipient_event_kwargs(
                                generic_event_kwargs,
                                raw_event,
                                home_team,
                                away_team,
                            )
                        )
                        duel_lost_event = self.event_factory.build_duel(
                            **duel_lost_event_kwargs,
                            **recipient_generic_event_kwargs,
                        )
                        if self.should_include_event(
                            duel_won_event
                        ) and self.should_include_event(duel_lost_event):
                            events.extend(
                                [
                                    transformer.transform_event(
                                        duel_won_event
                                    ),
                                    transformer.transform_event(
                                        duel_lost_event
                                    ),
                                ]
                            )
                        continue
                    elif action_id == SUBSTITUTION:
                        (
                            substitution_event_kwargs,
                            updated_generic_event_kwargs,
                        ) = _parse_substitution(
                            raw_event, generic_event_kwargs, team
                        )
                        event = self.event_factory.build_substitution(
                            **substitution_event_kwargs,
                            **updated_generic_event_kwargs,
                        )
                    else:
                        event = self.event_factory.build_generic(
                            **generic_event_kwargs,
                            result=None,
                            qualifiers=None,
                            event_name=action_title,
                        )

                    if self.should_include_event(event):
                        events.append(transformer.transform_event(event))

        self.mark_events_as_assists(events)

        metadata = Metadata(
            teams=[home_team, away_team],
            periods=periods,
            pitch_dimensions=transformer.get_to_coordinate_system().pitch_dimensions,
            score=score,
            orientation=Orientation.ACTION_EXECUTING_TEAM,
            flags=None,
            provider=Provider.SMRTSTATS,
            coordinate_system=transformer.get_to_coordinate_system(),
        )

        dataset = EventDataset(
            metadata=metadata,
            records=events,
        )
        dataset = self.remove_penalty_shootout_data(dataset)

        return dataset
