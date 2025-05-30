"""XML parser for Stats Perform MA3 feeds."""

from datetime import datetime, timezone
from typing import List

from .base import OptaEvent, OptaXMLParser


def _parse_ma3_datetime(dt_str: str) -> datetime:
    try:
        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )


class MA3XMLParser(OptaXMLParser):
    """Extract data from a Stats Perform MA3 data stream."""

    def extract_events(self) -> List[OptaEvent]:
        live_data = self.root.liveData
        return [
            OptaEvent(
                id=event.attrib["id"],
                event_id=int(event.attrib["eventId"]),
                type_id=int(event.attrib["typeId"]),
                period_id=int(event.attrib["periodId"]),
                time_min=int(event.attrib["timeMin"]),
                time_sec=int(event.attrib["timeSec"]),
                x=float(event.attrib["x"]),
                y=float(event.attrib["y"]),
                timestamp=_parse_ma3_datetime(event.attrib["timeStamp"]),
                last_modified=_parse_ma3_datetime(
                    event.attrib["lastModified"]
                ),
                contestant_id=event.attrib.get("contestantId"),
                player_id=event.attrib.get("playerId"),
                outcome=(
                    int(event.attrib["outcome"])
                    if "outcome" in event.attrib
                    else None
                ),
                qualifiers={
                    int(qualifier.attrib["qualifierId"]): qualifier.attrib.get(
                        "value"
                    )
                    for qualifier in event.iterchildren("qualifier")
                },
            )
            for event in live_data.events.iterchildren("event")
        ]
