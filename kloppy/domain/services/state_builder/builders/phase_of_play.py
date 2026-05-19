from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Optional, List

from kloppy.domain import (
    Event,
    Team,
    EventDataset,
    Point,
)
from kloppy.domain.models.event import (
    PossessionSwitchQualifier,
    PossessionSwitchType,
    SetPieceQualifier,
    SetPieceType,
    ShotEvent,
)
from .sequence import is_possessing_event, EXCLUDED_OFF_BALL_EVENTS
from ..builder import StateBuilder

from enum import Enum

CLOSE_TO_GOAL_THRESHOLD_METERS = 35.0
BALL_PROGRESSION_TIME_SECONDS = 10
BALL_PROGRESSION_THRESHOLD_METERS = 10.0
COUNTER_ATTACK_MAX_TIME_CLOSE_TO_GOAL_SECONDS = 15
COUNTER_ATTACK_EXTRA_TIME_CLOSE_TO_GOAL_SECONDS = 5
COUNTER_ATTACK_SUSTAIN_POSSESSION_MAX_TIME_SECONDS = 15
SET_PLAY_MIN_DURATION_SECONDS = 7

class PhaseOfPlayType(Enum):
    TRANSITION = "transition"
    BUILD_UP = "build_up"
    COUNTER_ATTACK = "counter_attack"
    ESTABLISHED_POSSESSION = "established_possession"
    SET_PLAY = "set_play"

@dataclass
class PhaseOfPlay:
    """
    Represents the current phase of play for a team.

    Attributes
    ----------
    phase : PhaseOfPlayType
        Type of the current phase (e.g., TRANSITION, BUILD_UP, COUNTER_ATTACK).
    team : Optional[Team]
        Team currently in possession during this phase.
    """
    phase: PhaseOfPlayType
    team: Optional[Team]

# ------------------------------------------------------------
# Spatial Utility Functions
# ------------------------------------------------------------
def is_defending_half(event: Event) -> bool:
    """Return True if the event occurs in the defending half of the pitch."""
    pitch_min = event.dataset.metadata.pitch_dimensions.x_dim.min
    pitch_max = event.dataset.metadata.pitch_dimensions.x_dim.max
    pitch_length = pitch_max - pitch_min
    return event.coordinates.x < pitch_min + pitch_length / 2

def is_first_third(event: Event) -> bool:
    """Return True if the event occurs in the team's own first third of the pitch."""
    pitch_min = event.dataset.metadata.pitch_dimensions.x_dim.min
    pitch_max = event.dataset.metadata.pitch_dimensions.x_dim.max
    pitch_length = pitch_max - pitch_min
    return event.coordinates.x < pitch_min + pitch_length / 3

def is_final_third(event: Event) -> bool:
    """Return True if the event occurs in the attacking final third of the pitch."""
    pitch_min = event.dataset.metadata.pitch_dimensions.x_dim.min
    pitch_max = event.dataset.metadata.pitch_dimensions.x_dim.max
    pitch_length = pitch_max - pitch_min
    return event.coordinates.x > pitch_min + 2 * (pitch_length / 3)

def distance_to_goal(event: Event) -> float:
    """Compute the distance from the event location to the opponent's goal."""
    dims = event.dataset.metadata.pitch_dimensions
    goal_point = Point(
        dims.x_dim.max,
        (dims.y_dim.max + dims.y_dim.min) / 2,
    )
    return dims.distance_between(Point(event.coordinates.x, event.coordinates.y), goal_point)

def close_to_goal(event: Event) -> bool:
    """Return True if the event is within a close-to-goal threshold."""
    return distance_to_goal(event) <= CLOSE_TO_GOAL_THRESHOLD_METERS

# ------------------------------------------------------------
# Possession / Counter Attack Logic Helpers
# ------------------------------------------------------------
def find_last_possession_gain(event: Event, team: Team) -> Optional[Event]:
    """Traverse backwards to find the last possession gain event for a team."""
    cursor = event.prev_record
    while cursor and cursor.period == event.period:
        switch = cursor.get_qualifier_value(PossessionSwitchQualifier)
        if switch == PossessionSwitchType.GAIN and cursor.team == team:
            return cursor
        cursor = cursor.prev_record
    return None

def check_ball_progression(event: Event, team: Team) -> bool:
    """
    Check if the ball has advanced at least BALL_PROGRESSION_THRESHOLD_METERS
    in the last BALL_PROGRESSION_TIME_SECONDS seconds, relative to the opponent's goal.

    Returns
    -------
    bool
        True if progression meets or exceeds the threshold, False otherwise.
    """
    current_time = event.timestamp
    start_time = current_time - timedelta(seconds=BALL_PROGRESSION_TIME_SECONDS)
    current_distance = distance_to_goal(event)
    furthest_distance = 0

    cursor = event.prev_record

    while cursor and cursor.period == event.period:
        if cursor.timestamp < start_time:
            break
        if cursor.team == team and cursor.state["phase_of_play"].phase in [PhaseOfPlayType.COUNTER_ATTACK, PhaseOfPlayType.TRANSITION]:
            furthest_distance = max(distance_to_goal(cursor), furthest_distance)
        cursor = cursor.prev_record

    if not furthest_distance or not cursor or cursor.state["phase_of_play"].phase != PhaseOfPlayType.COUNTER_ATTACK:
        return True  # assume progression OK if insufficient info

    return furthest_distance - current_distance >= BALL_PROGRESSION_THRESHOLD_METERS

def find_last_event_before_transition(event):
    """Traverse backwards to find the last event before the current transition phase."""
    cursor = event.prev_record
    while cursor and cursor.period == event.period:
        if cursor.state["phase_of_play"].phase != PhaseOfPlayType.TRANSITION:
            return cursor
        cursor = cursor.prev_record
    return None

def find_last_sequence_possessing_event_in_final_third(event: Event, team: Team):
    """
    Traverse backwards to find the last possessing event in the same sequence
    in the final third for the given team.
    """
    cursor = event.prev_record
    while cursor and cursor.period == event.period:
        other_sequence = cursor.state["sequence"].sequence_id and cursor.state["sequence"].sequence_id != event.state["sequence"].sequence_id
        if other_sequence:
            break
        if is_possessing_event(cursor) and cursor.team == team and is_final_third(cursor):
            return cursor
        cursor = cursor.prev_record
    return None

def find_first_close_to_goal_event(event: Event, team: Team):
    """
    Traverse forward to find the first event that is close to goal, until
    a turnover or opponent possession occurs.
    """
    cursor = event.next_record
    while cursor and cursor.period == event.period:
        switch = cursor.get_qualifier_value(PossessionSwitchQualifier)
        if switch == PossessionSwitchType.LOSE and cursor.team == team:
            return None
        if is_possessing_event(cursor):
            if cursor.team != team:
                return None
            if close_to_goal(cursor) or isinstance(cursor, ShotEvent):
                return cursor
        cursor = cursor.next_record
    return None

def find_sustaining_event(event: Event, team: Team):
    """Look forward for another strong offensive event in close proximity."""
    cursor = event.next_record
    while cursor and cursor.period == event.period:
        if is_possessing_event(cursor) and cursor.team == team and close_to_goal(cursor):
            return cursor
        cursor = cursor.next_record
    return None

def get_previous_on_ball_event(event: Event) -> Optional[Event]:
    """Get the last on ball event in the same period"""
    prev_event = event.prev_record
    while prev_event and event.period == prev_event.period and isinstance(prev_event, EXCLUDED_OFF_BALL_EVENTS):
        prev_event = prev_event.prev_record
    return prev_event

def get_last_possession_event(event) -> Optional[Event]:
    last_possession_event = event.prev_record
    while last_possession_event and last_possession_event.period == event.period and not is_possessing_event(last_possession_event):
        last_possession_event = last_possession_event.prev_record
    return last_possession_event


def detect_counter_attack(event: Event, state: PhaseOfPlay):
    """
    Detect a counter-attack based on possession gain, pitch location,
    and speed of progression.

    Returns
    -------
    bool
        True if a counter-attack is detected, False otherwise.
    """
    gain_event = find_last_possession_gain(event, state.team)
    if not gain_event or not is_defending_half(gain_event):
        return False

    last_event_before_transition = find_last_event_before_transition(event)
    if not last_event_before_transition or last_event_before_transition.team == event.team:
        return False

    possession_gain_time = gain_event.timestamp
    gained_in_own_third = is_first_third(gain_event)

    close_goal_event = find_first_close_to_goal_event(event, state.team)
    if not close_goal_event:
        return False

    allowed_seconds = COUNTER_ATTACK_MAX_TIME_CLOSE_TO_GOAL_SECONDS + COUNTER_ATTACK_EXTRA_TIME_CLOSE_TO_GOAL_SECONDS if gained_in_own_third else COUNTER_ATTACK_MAX_TIME_CLOSE_TO_GOAL_SECONDS
    if close_goal_event.timestamp - possession_gain_time > timedelta(seconds=allowed_seconds):
        return False

    if isinstance(close_goal_event, ShotEvent):
        return True

    sustaining_event = find_sustaining_event(close_goal_event, state.team)
    if not sustaining_event:
        return False

    if sustaining_event.timestamp - close_goal_event.timestamp <= timedelta(seconds=COUNTER_ATTACK_SUSTAIN_POSSESSION_MAX_TIME_SECONDS):
        return True

    return False

def detect_possession_to_transition(event: Event):
    """
    Detect if build up or established possession should change to transition.
    Returns
    -------
    bool
        True if a transition is detected, False otherwise.
    """
    if event.get_qualifier_value(PossessionSwitchQualifier) == PossessionSwitchType.GAIN:
        return True
    # Previous event was a possession loss
    prev_on_ball_event = get_previous_on_ball_event(event)
    if prev_on_ball_event and prev_on_ball_event.get_qualifier_value( PossessionSwitchQualifier) == PossessionSwitchType.LOSE:
        return True
    return False

def detect_exit_transition(event: Event, last_possession_event: Optional[Event]) -> bool:
    """
    Detect if transition should end based on consecutive possessing events from the same team but different players.
    """
    same_team_prev = last_possession_event and last_possession_event.team == event.team
    if same_team_prev and is_possessing_event(event) and last_possession_event.player != event.player:
        return True
    return False

def detect_exit_set_play(event: Event) -> bool:
    """
    Detect if set-play should end based on consecutive possessing events from
    the same team but different players.

    The set-play phase persists for at least SET_PLAY_MIN_DURATION_SECONDS
    after a set piece *in the attacking final third*, so that a blocked
    /saved/missed shot followed by a same-team rebound does not end the
    phase. Set pieces outside the final third (e.g. midfield throw-ins or
    free kicks) don't get this extension — they fall through to the
    player-change rule immediately, since the rebound dynamics that
    motivate the extension don't apply away from goal.
    """
    cursor = event.prev_record
    while cursor and cursor.period == event.period:
        if event.timestamp - cursor.timestamp >= timedelta(
            seconds=SET_PLAY_MIN_DURATION_SECONDS
        ):
            break
        if (
            cursor.get_qualifier_value(SetPieceQualifier)
            and is_final_third(cursor)
        ):
            return False
        cursor = cursor.prev_record

    last_possession_event = get_last_possession_event(event)
    if last_possession_event.get_qualifier_value(SetPieceQualifier):
        return False
    prev_event = get_previous_on_ball_event(event)
    if not prev_event or prev_event.team != event.team:
        return False

    same_team_prev = last_possession_event and last_possession_event.team == event.team
    if same_team_prev and is_possessing_event(event) and last_possession_event.player != event.player:
        return True
    return False

def determine_phase_change(event: Event, state: PhaseOfPlay) -> Optional[PhaseOfPlayType]:
    """
    Determine if an event triggers a phase-of-play transition.

    Considers:
    - Possession gains/losses
    - Spatial context (own half, final third)
    - Set-piece events
    - Counter-attack detection
    - Stability of possession
    - Previous phase and team in possession

    Parameters
    ----------
    event : Event
        The event being evaluated.
    state : PhaseOfPlay
        The current phase state.

    Returns
    -------
    Optional[PhaseOfPlayType]
        The new phase if a transition occurs, else None.
    """
    # ignore excluded off-ball events
    if isinstance(event, EXCLUDED_OFF_BALL_EVENTS):
        return None

    # set-piece events always trigger phase changes
    set_piece_type = event.get_qualifier_value(SetPieceQualifier)
    if set_piece_type in (SetPieceType.GOAL_KICK, SetPieceType.KICK_OFF):
        return PhaseOfPlayType.BUILD_UP
    elif set_piece_type:
        return PhaseOfPlayType.SET_PLAY

    # TRANSITION
    if state.phase == PhaseOfPlayType.TRANSITION:
        # --- Transition -> Counter Attack --- #
        if detect_counter_attack(event, state):
            return PhaseOfPlayType.COUNTER_ATTACK

        # Re-check if transition should restart
        last_possession_event = get_last_possession_event(event)
        if last_possession_event:
            switch = last_possession_event.get_qualifier_value(PossessionSwitchQualifier)
            if switch == PossessionSwitchType.GAIN:
                return PhaseOfPlayType.TRANSITION


        # Transition -> Build-Up / Established Possession
        if detect_exit_transition(event, last_possession_event):
            return PhaseOfPlayType.BUILD_UP if is_defending_half(event) else PhaseOfPlayType.ESTABLISHED_POSSESSION

    # BUILD-UP
    if state.phase == PhaseOfPlayType.BUILD_UP:
        # Build-up -> Transition
        if detect_possession_to_transition(event):
            return PhaseOfPlayType.TRANSITION


        # Build-up -> Established Possession
        # build up ends when ball goes over the halfway line
        if not is_defending_half(event) and event.team == state.team:
            return PhaseOfPlayType.ESTABLISHED_POSSESSION

    # COUNTER ATTACK
    if state.phase == PhaseOfPlayType.COUNTER_ATTACK:
        # Counter Attack -> Transition
        if event.get_qualifier_value(PossessionSwitchQualifier) == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION


        # Counter Attack -> Build Up or Established Possession
        last_final_third_event = find_last_sequence_possessing_event_in_final_third(event, state.team)
        if last_final_third_event and event.team == state.team:
            if is_defending_half(event):
                return PhaseOfPlayType.BUILD_UP
            if is_possessing_event(event) and not is_final_third(event) and not check_ball_progression(event, state.team):
                return PhaseOfPlayType.ESTABLISHED_POSSESSION

    # ESTABLISHED POSSESSION
    if state.phase == PhaseOfPlayType.ESTABLISHED_POSSESSION:
        # Established Possession -> Transition
        if detect_possession_to_transition(event):
            return PhaseOfPlayType.TRANSITION


        # Established Possession -> Build Up
        if event.team == state.team and is_defending_half(event):
            return PhaseOfPlayType.BUILD_UP

    # SET PLAY
    if state.phase == PhaseOfPlayType.SET_PLAY:
        # Set Play -> Transition

        if event.get_qualifier_value(PossessionSwitchQualifier) == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION


        if detect_exit_set_play(event):
            return PhaseOfPlayType.BUILD_UP if is_defending_half(event) else PhaseOfPlayType.ESTABLISHED_POSSESSION

    # Default: stay in the same phase
    return None

# ----------------------------------------------------------------------
# State Builder Skeleton
# ----------------------------------------------------------------------

class PhaseOfPlayStateBuilder(StateBuilder):
    """State builder that tracks the current phase of play across events."""

    def initial_state(self, dataset: EventDataset) -> PhaseOfPlay:
        """Return the initial phase state before processing any events."""
        if not dataset.events[0].state.get("sequence"):
            raise ValueError(
                "PhaseOfPlayStateBuilder requires 'sequence' state builder to be applied first."
            )
        first_team = dataset.events[0].team
        return PhaseOfPlay(phase=PhaseOfPlayType.BUILD_UP, team=first_team)

    def reduce_before(self, state: PhaseOfPlay, event: Event) -> PhaseOfPlay:
        """Update the state based on the event before applying it."""
        new_phase_type = determine_phase_change(event, state)
        if new_phase_type:
            state = replace(state, phase=new_phase_type, team=event.team)
        return state

    def reduce_after(self, state: PhaseOfPlay, event: Event) -> PhaseOfPlay:
        """Return the state after processing the event."""
        return state

    def post_process(self, events: List[Event]):
        """Optional post-processing after all events have been assigned phases."""
        pass
