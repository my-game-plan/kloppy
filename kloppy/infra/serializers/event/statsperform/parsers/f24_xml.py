"""XML parser for Opta F24 feeds."""

from datetime import datetime
from typing import List, Optional

import pytz

from .base import OptaEvent, OptaXMLParser


def _parse_naive(dt_str: str) -> datetime:
    def zero_pad_milliseconds(timestamp):
        parts = timestamp.split(".")
        if len(parts) == 1:
            return timestamp + ".000"
        return ".".join(parts[:-1] + [f"{int(parts[-1]):03d}"])

    return datetime.strptime(
        zero_pad_milliseconds(dt_str), "%Y-%m-%dT%H:%M:%S.%f"
    )


def _parse_f24_datetime(
    dt_str: str, utc_dt_str: Optional[str] = None
) -> datetime:
    """Parse an F24 wall-clock time into an aware UTC datetime.

    F24's `timestamp` is London local time, which is ambiguous for the hour
    the clocks go back (01:00-01:59 occurs once in BST and again in GMT) and
    pytz silently resolves every such time as GMT. A match played across that
    hour then has its BST stretch pushed an hour later, which makes the first
    half end before it starts. Opta ships `timestamp_utc` alongside, so read
    that whenever it is there and fall back to the London time only for feeds
    that predate it.
    """
    if utc_dt_str:
        return pytz.utc.localize(_parse_naive(utc_dt_str))
    naive_datetime = _parse_naive(dt_str)
    timezone = pytz.timezone("Europe/London")
    aware_datetime = timezone.localize(naive_datetime)
    return aware_datetime.astimezone(pytz.utc)


class F24XMLParser(OptaXMLParser):
    """Extract data from a Opta F24 data stream."""

    def extract_events(self) -> List[OptaEvent]:
        game_elm = self.root.find("Game")
        return [
            OptaEvent(
                id=event.attrib["id"],
                event_id=int(event.attrib["event_id"]),
                type_id=int(event.attrib["type_id"]),
                period_id=int(event.attrib["period_id"]),
                time_min=int(event.attrib["min"]),
                time_sec=int(event.attrib["sec"]),
                x=float(event.attrib["x"]),
                y=float(event.attrib["y"]),
                timestamp=_parse_f24_datetime(
                    event.attrib["timestamp"],
                    event.attrib.get("timestamp_utc"),
                ),
                last_modified=_parse_f24_datetime(
                    event.attrib["last_modified"]
                ),
                contestant_id=event.attrib.get("team_id"),
                player_id=event.attrib.get("player_id"),
                outcome=int(event.attrib["outcome"])
                if "outcome" in event.attrib
                else None,
                qualifiers={
                    int(
                        qualifier.attrib["qualifier_id"]
                    ): qualifier.attrib.get("value")
                    for qualifier in event.iterchildren("Q")
                },
            )
            for event in game_elm.iterchildren("Event")
        ]

    def extract_date(self) -> Optional[datetime]:
        """Return the date of the game."""
        game_elm = self.root.find("Game")
        if game_elm is not None and "game_date_utc" in game_elm.attrib:
            return pytz.utc.localize(
                datetime.strptime(
                    game_elm.attrib["game_date_utc"], "%Y-%m-%dT%H:%M:%S"
                )
            )
        if game_elm is not None and "game_date" in game_elm.attrib:
            naive_datetime = datetime.strptime(
                game_elm.attrib["game_date"], "%Y-%m-%dT%H:%M:%S"
            )
            timezone = pytz.timezone("Europe/London")
            aware_datetime = timezone.localize(naive_datetime)
            return aware_datetime.astimezone(pytz.utc)
        else:
            return None

    def extract_game_week(self) -> Optional[str]:
        """Return the game_week of the game."""
        game_elm = self.root.find("Game")
        if game_elm is not None and "matchday" in game_elm.attrib:
            return game_elm.attrib["matchday"]
        else:
            return None

    def extract_game_id(self) -> Optional[str]:
        """Return the game_id of the game."""
        game_elm = self.root.find("Game")
        if game_elm is not None and "id" in game_elm.attrib:
            return game_elm.attrib["id"]
        else:
            return None
