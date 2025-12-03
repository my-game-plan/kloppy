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


class PhaseOfPlayType(Enum):
    TRANSITION = "transition"
    BUILD_UP = "build_up"
    COUNTER_ATTACK = "counter_attack"
    ESTABLISHED_POSSESSION = "established_possession"
    SET_PLAY = "set_play"

@dataclass
class PhaseOfPlay:
    phase: PhaseOfPlayType
    team: Optional[Team]

# ------------------------------------------------------------
# Spatial Utility Functions
# ------------------------------------------------------------
def is_defending_half(event: Event) -> bool:
    """Check if the event is in the defending half."""
    pitch_min = event.dataset.metadata.pitch_dimensions.x_dim.min
    pitch_max = event.dataset.metadata.pitch_dimensions.x_dim.max
    pitch_length = pitch_max - pitch_min
    return event.coordinates.x < pitch_min + pitch_length / 2


def is_first_third(event: Event) -> bool:
    """Check if the event is in the first third."""
    pitch_min = event.dataset.metadata.pitch_dimensions.x_dim.min
    pitch_max = event.dataset.metadata.pitch_dimensions.x_dim.max
    pitch_length = pitch_max - pitch_min
    return event.coordinates.x < pitch_min + pitch_length / 3

def is_final_third(event: Event) -> bool:
    """Check if the event is in the final third."""
    pitch_min = event.dataset.metadata.pitch_dimensions.x_dim.min
    pitch_max = event.dataset.metadata.pitch_dimensions.x_dim.max
    pitch_length = pitch_max - pitch_min
    return event.coordinates.x > pitch_min + 2 * (pitch_length / 3)

def distance_to_goal(event: Event) -> float:
    """Distance to opponent goal."""
    dims = event.dataset.metadata.pitch_dimensions
    goal_point = Point(
        dims.x_dim.max,
        (dims.y_dim.max + dims.y_dim.min) / 2,
    )
    return dims.distance_between(Point(event.coordinates.x, event.coordinates.y), goal_point)

def close_to_goal(event: Event,) -> bool:
    """Distance to opponent goal under threshold."""
    return distance_to_goal(event) <= 35.0  # meters

# ------------------------------------------------------------
# Possession / Counter Attack Logic Helpers
# ------------------------------------------------------------
def find_last_possession_gain(event: Event, team: Team):
    """Walk backward to find the most recent possession gain for team."""
    cursor = event.prev_record

    while cursor and cursor.period == event.period:
        switch = cursor.get_qualifier_value(PossessionSwitchQualifier)
        if switch == PossessionSwitchType.GAIN and cursor.team == team:
            return cursor
        cursor = cursor.prev_record

    return None

def check_ball_progression(
    event: Event,
    team: Team
) -> bool:
    """
    Returns True if ball has advanced AT LEAST `meters` in the last `seconds`.
    Progression = change in x-coordinate (toward opponent's goal).
    """
    current_time = event.timestamp
    start_time = current_time - timedelta(seconds=10)
    current_distance = distance_to_goal(event)
    furthest_distance = 0

    cursor = event.prev_record

    # Find earliest event inside the time window
    while cursor and cursor.period == event.period:
        if cursor.timestamp < start_time:
            break
        # Consider only events in transition or counter attack from same team
        if cursor.team == team and cursor.state["phase_of_play"].phase in [PhaseOfPlayType.COUNTER_ATTACK, PhaseOfPlayType.TRANSITION]:
            furthest_distance = max(distance_to_goal(cursor), furthest_distance)

        cursor = cursor.prev_record

    if not furthest_distance or not cursor or cursor.state["phase_of_play"].phase != PhaseOfPlayType.COUNTER_ATTACK :
        return True # not enough info → assume progression OK to avoid false positives

    return furthest_distance - current_distance >= 10.0  # meters progressed

def find_last_event_before_transition(event):
    """Walk backward to find the last event before transition started."""
    cursor = event.prev_record

    while cursor and cursor.period == event.period:
        if cursor.state["phase_of_play"].phase != PhaseOfPlayType.TRANSITION:
            return cursor
        cursor = cursor.prev_record

    return None

def find_last_sequence_possessing_event_in_final_third(event: Event, team: Team):
    """Walk backward to find the last possessing event in the same sequence in the final third for team."""
    cursor = event.prev_record

    while cursor and cursor.period == event.period:
        other_sequence = cursor.state["sequence"].sequence_id and cursor.state["sequence"].sequence_id != event.state[
            "sequence"].sequence_id
        if other_sequence:
            break
        if is_possessing_event(cursor) and cursor.team == team and is_final_third(cursor):
            return cursor
        cursor = cursor.prev_record

    return None

def find_first_close_to_goal_event(event: Event, team: Team):
    """Walk forward until: close-to-goal condition OR turnover OR opponent gains ball."""
    cursor = event.next_record

    while cursor and cursor.period == event.period:
        switch = cursor.get_qualifier_value(PossessionSwitchQualifier)

        if switch == PossessionSwitchType.LOSE and cursor.team == team:
            return None  # turnover ends counter attempt

        if is_possessing_event(cursor):
            if cursor.team != team:
                return None  # opponent gains ball
            if close_to_goal(cursor):
                return cursor  # good event found

        cursor = cursor.next_record

    return None

def find_sustaining_event(event: Event, team: Team):
    """Look forward for another strong offensive action within close range."""
    cursor = event.next_record

    while cursor and cursor.period == event.period:
        if (
            is_possessing_event(cursor)
            and cursor.team == team
            and close_to_goal(cursor)
        ):
            return cursor
        cursor = cursor.next_record

    return None

def detect_counter_attack(event: Event, state: PhaseOfPlay):
    """
    Full counter-attack detection logic — cleanly isolated.
    Returns True if conditions satisfied, else False.
    """
    gain_event = find_last_possession_gain(event, state.team)
    if not gain_event or not is_defending_half(gain_event):
        return False

    last_event_before_transition = find_last_event_before_transition(event)
    if last_event_before_transition.team == event.team:
        return False

    possession_gain_time = gain_event.timestamp
    gained_in_own_third = is_first_third(gain_event)

    close_goal_event = find_first_close_to_goal_event(event, state.team)
    if not close_goal_event:
        return False

    allowed_seconds = 20 if gained_in_own_third else 15
    if close_goal_event.timestamp - possession_gain_time > timedelta(seconds=allowed_seconds):
        return False

    # If shot happens immediately inside window → definite counter attack
    if isinstance(close_goal_event, ShotEvent):
        return True

    sustaining_event = find_sustaining_event(close_goal_event, state.team)
    if not sustaining_event:
        return False

    if sustaining_event.timestamp - close_goal_event.timestamp <= timedelta(seconds=15):
        return True

    return False

def determine_phase_change(
    event: Event,
    state: PhaseOfPlay
) -> Optional[PhaseOfPlayType]:
    """
    Determine whether a given event triggers a phase-of-play transition.

    This function evaluates the current phase (transition, build-up,
    counter-attack, established possession, or set play) and checks whether
    the new event satisfies the criteria to move into a different phase.
    Phase-change detection is driven by:

    - possession gains/losses (via PossessionSwitchQualifier)
    - spatial context (own half, final third, ball progression)
    - set-piece events
    - counter-attack recognition (fast progression after a possession gain)
    - stability of possession (e.g., two consecutive controlling actions)
    - the last known phase and team in possession

    Parameters
    ----------
    event : Event
        The current event being processed.
    state : PhaseOfPlay
        The current phase state before processing this event.

    Returns
    -------
    Optional[PhaseOfPlayType]
        The new phase if a transition is detected, otherwise None
        (meaning the current phase continues unchanged).

    Notes
    -----
    The detailed logic for each phase is documented inline in the respective
    section blocks below (TRANSITION, BUILD-UP, COUNTER-ATTACK,
    ESTABLISHED POSSESSION, SET PLAY).
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

    # ---------------- TRANSITION LOGIC ---------------- #
    if state.phase == PhaseOfPlayType.TRANSITION:
        # --- Transition -> Counter Attack --- #
        if detect_counter_attack(event, state):
            return PhaseOfPlayType.COUNTER_ATTACK

        # Re-check if transition should restart
        last_possession_event = event.prev_record
        while last_possession_event and not is_possessing_event(last_possession_event):
            last_possession_event = last_possession_event.prev_record

        if last_possession_event:
            switch = last_possession_event.get_qualifier_value(PossessionSwitchQualifier)
            if switch == PossessionSwitchType.GAIN:
                return PhaseOfPlayType.TRANSITION

        # Transition -> Build-Up / Established Possession
        # Transition ends when two consecutive team possession actions occur
        same_team_prev = (
            last_possession_event
            and last_possession_event.team == event.team
            and is_possessing_event(last_possession_event)
        )
        if same_team_prev and is_possessing_event(event):
            return (
                PhaseOfPlayType.BUILD_UP
                if is_defending_half(event)
                else PhaseOfPlayType.ESTABLISHED_POSSESSION
            )


    # ---------------- BUILD-UP LOGIC ------------------- #
    if state.phase == PhaseOfPlayType.BUILD_UP:
        # Build-up -> Transition
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION

        # Build-up -> Established Possession
        # build up ends when ball goes over the halfway line
        if not is_defending_half(event) and event.team == state.team:
            return PhaseOfPlayType.ESTABLISHED_POSSESSION


    # ------------ COUNTER ATTACK LOGIC ----------------- #
    if state.phase == PhaseOfPlayType.COUNTER_ATTACK:
        # Counter Attack -> Transition
        # check if counter attack becomes build_up again
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION

        # Transition -> Build Up or Established Possession
        last_final_third_event = find_last_sequence_possessing_event_in_final_third(event, state.team)
        if last_final_third_event and event.team == state.team:
            if is_defending_half(event):
                return PhaseOfPlayType.BUILD_UP
            if is_possessing_event(event) and not is_final_third(event) and not check_ball_progression(event, state.team):
                return PhaseOfPlayType.ESTABLISHED_POSSESSION

    # ---------------- ESTABLISHED POSSESSION ---------------- #
    if state.phase == PhaseOfPlayType.ESTABLISHED_POSSESSION:
        # Established Possession -> Transition
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION

        # Established Possession -> Build Up
        if event.team == state.team and is_defending_half(event):
            return PhaseOfPlayType.BUILD_UP

    # -------------------- SET PLAY -------------------------- #
    if state.phase == PhaseOfPlayType.SET_PLAY:
        # Set Play -> Transition
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION
        prev_event = event.prev_record
        while prev_event and isinstance(prev_event, EXCLUDED_OFF_BALL_EVENTS):
            prev_event = prev_event.prev_record



        if prev_event:
            # Set Play -> Build Up / Established Possession
            prev_event_set_piece_type = prev_event.get_qualifier_value(SetPieceQualifier)
            same_team_prev = (
                prev_event.team == event.team
                and is_possessing_event(prev_event)
            )
            # exit set-play when two consecutive possessing actions from same team occur after set piece
            if not prev_event_set_piece_type and same_team_prev and is_possessing_event(event):
                return (
                    PhaseOfPlayType.BUILD_UP
                    if is_defending_half(event)
                    else PhaseOfPlayType.ESTABLISHED_POSSESSION
                )

    # Default: stay in the same phase
    return None



# ----------------------------------------------------------------------
# State Builder Skeleton
# ----------------------------------------------------------------------

class PhaseOfPlayStateBuilder(StateBuilder):

    def initial_state(self, dataset: EventDataset) -> PhaseOfPlay:
        """Determine initial phase before the first event."""
        # Check if sequence in the state
        if not dataset.events[0].state.get("sequence"):
            raise ValueError(
                "PhaseOfPlayStateBuilder requires 'sequence' state builder to be applied first."
            )
        first_team = dataset.events[0].team
        return PhaseOfPlay(phase=PhaseOfPlayType.BUILD_UP, team=first_team)

    def reduce_before(self, state: PhaseOfPlay, event: Event) -> PhaseOfPlay:
        """Update state before applying the event."""
        new_phase_type = determine_phase_change(event, state)
        if new_phase_type:
            state = replace(state, phase=new_phase_type, team=event.team)
        return state

    def reduce_after(self, state: PhaseOfPlay, event: Event) -> PhaseOfPlay:
        """Update state after applying the event."""
        return state

    def post_process(self, events: List[Event]):
        """Optional post-processing once all events have been assigned phases."""
        pass
