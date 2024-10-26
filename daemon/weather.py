from dataclasses import dataclass
import datetime
import json


class RawForecast(object):
    def __init__(self, j):
        self.__dict__ = json.loads(j)


# @dataclass
class Forecast:
    date: datetime.datetime
    sky: str
    downfall: str
    """textual repr. of rain|snow|sleet downfall. Empty if none"""
    lightning: str
    """Lightning chance. empty if no lightning forecast"""
    wind: str
    """empty if calm, otherwise a textual representation"""
    low_c: int
    """Lowest temperature during the day"""
    high_c: int
    """Highest temperature during the day"""
    avg_c: int
    """Average temperature during the day"""
    today: bool
    """True == forecast for today. False = Forecast for tomorrow"""
    summary: str
    """textual representation of weather forecast"""

    def temp(self, min: int, avg: int, high: int) -> None:
        self.low_c = min
        self.avg_c = avg
        self.high_c = high

