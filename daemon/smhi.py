# import requests module
from datetime import timezone, datetime, time
import logging
import requests
from daemon.weather import Forecast, RawForecast


logger = logging.getLogger("daemon.smhi")


class SMHI:
    """pulls data from SMHI API
    Authentication: None
    API documentation: https://opendata.smhi.se/apidocs/metfcst/parameters.html#parameter-cloud-cover"""
    long = 17.870
    lat = 59.386

    @staticmethod
    def get_weather_descr() -> str:
        try:
            raw = SMHI.__get_weather_forecast()
            forecast = SMHI._parse_weather_json(raw)
            return SMHI._forecast_as_str(forecast)
        except Exception as e:
            logger.error(e)
        return ""

    # weather today is {cloudy|Halfclear|sunny}, temperatures averaging {avgT}, lows/highs about {c_high}
    # with {light|moderate|heavy}} {rain|rain+snow(sleet)|} during {whole,morning,afternoon,evening}
    # {lightning likely} {wind}

    @staticmethod
    def _forecast_as_str(f: Forecast) -> str:
        winterTime = (
            True if datetime.now().month > 9 or datetime.now().month < 4 else False
        )
        tempstr = (
            f"lows about {int(round(f.low_c))}"
            if winterTime
            else f"highs about {int(round(f.high_c))}, "
        )
        msg = f"Weather today is {f.sky}, "
        msg += f"temperatures averaging {int(round(f.avg_c))}, {tempstr}, "
        msg += f"{f.downfall} {f.lightning} {f.wind}"
        return msg

    @staticmethod
    def _parse_weather_json(raw: dict) -> Forecast:
        rf = RawForecast(raw)
        today = datetime.now(timezone.utc)
        d = SMHI.__filter_by_date(rf.timeSeries, today)
        if len(d) > 6:
            d = SMHI._filter_by_time(d, 7, 21)

        forecast = Forecast()
        forecast.temp(*SMHI._get_temp(d))
        forecast.sky = SMHI._get_cloudiness(d)
        forecast.lightning = SMHI._get_lightningdescr(d)
        forecast.wind = SMHI._get_wind_descr(d)
        forecast.downfall = SMHI._get_downfall_descr(d)
        return forecast
        pass

    @staticmethod
    def _get_downfall_descr(timeSeries) -> str:
        msg = ""
        snow_avg = 0
        rain_avg = 0

        rrain = [
            obj
            for obj in timeSeries
            if any(
                param["name"] == "pcat" and 2 < param["values"][0] <= 6
                for param in obj["parameters"]
            )
        ]

        rsnow = [
            obj
            for obj in timeSeries
            if any(
                param["name"] == "pcat" and 1 <= param["values"][0] < 3
                for param in obj["parameters"]
            )
        ]
        if len(rrain) > 0:
            rainmm_min = sum(SMHI._get_val_by_parameter(rrain, "pmin"))
            rainmm_max = sum(SMHI._get_val_by_parameter(rrain, "pmax"))
            rain_avg = (rainmm_min + rainmm_max) / len(rrain)

        if len(rsnow) > 0:
            snowmm_min = sum(SMHI._get_val_by_parameter(rsnow, "pmin"))
            snowmm_max = sum(SMHI._get_val_by_parameter(rsnow, "pmax"))
            snow_avg = (snowmm_min + snowmm_max) / len(rsnow)

        if rain_avg > 0.1:
            if rain_avg < 4:
                msg += "some rain"
            elif rain_avg >= 4 and rain_avg < 10:
                msg += "rain"
            else:
                msg += "heavy rain"
            if len(rrain) < 4:
                msg += " part of the day."
            elif rain_avg > 0.2:
                msg += " most of the day."

        if snow_avg > 0.1:
            if snow_avg < 3:
                msg += "some snow"
            elif snow_avg >= 3 and snow_avg < 10:
                msg += "snowy"
            else:
                msg += "heavy snowing"
            if len(rsnow) < 4:
                "part of the day."
            elif snow_avg > 0.3:
                msg += " most of the day."
        return msg

    @staticmethod
    def _get_wind_descr(timeSeries) -> str:
        t = SMHI._get_val_by_parameter(timeSeries, "ws")
        avg = sum(t) / len(t)
        if avg < 10:
            return ""
        if avg > 10 and avg <= 14:
            return "wind: strong breeze"
        if avg > 14 and avg <= 17.2:
            return "wind: Moderate gale"
        if avg > 17.2 and avg <= 20.6:
            return "wind: fresh gale"
        if avg > 20.6 and avg <= 24.4:
            return "wind: Sever gale"
        if avg > 24.4 and avg <= 28.4:
            return "wind: Storm!"
        if avg > 28.4 and avg <= 32.6:
            return "wind: Violent Storm!"
        if avg > 28.4 and avg <= 32.6:
            return "wind: Hurricane-force!"

    @staticmethod
    def _get_lightningdescr(timeSeries) -> str:
        t = SMHI._get_val_by_parameter(timeSeries, "tstm")
        c_thunder = sum(1 for x in t if x > 30)
        if c_thunder == 0:
            return ""
        avg_thunder = sum(x for x in t if x >= 30) / c_thunder
        return "" if avg_thunder < 30 else ", lightning likely today,"

    @staticmethod
    def _get_cloudiness(timeSeries) -> str:
        t = SMHI._get_val_by_parameter(timeSeries, "tcc_mean")
        c = len(t)
        if c == 0:
            return "sunny"
        c_notcloudy = sum(1 for x in t if x < 3) / c
        c_medcloudy = sum(1 for x in t if x >= 3 and x < 7) / c
        c_verycloudy = sum(2 for x in t if x >= 6) / c

        if c_notcloudy > 0 and (c_medcloudy + c_verycloudy) < 0.3:
            return "sunny"
        if abs(c_notcloudy - (c_medcloudy + c_verycloudy)) < 0.2:
            return "half clear"
        else:
            return "cloudy"

    @staticmethod
    def _get_temp(timeSeries) -> tuple[int, int, int]:
        """Returns the lowest, avg and highest temperture
        found in the series"""
        t = SMHI._get_val_by_parameter(timeSeries, "t")
        min_val = min(t)
        max_val = max(t)
        avg = sum(t) / len(t)
        return (min_val, avg, max_val)

    @staticmethod
    def _filter_by_time(timeSeries, start_h: int, end_h: int):
        """Returns items that fall within (inclusive) the hour
        start and end range"""
        items = []
        for ts in timeSeries:
            if ts["validTime"].time() >= time(hour=start_h) and ts[
                "validTime"
            ].time() <= time(hour=end_h):
                items.append(ts)
        return items

    @staticmethod
    def _get_val_by_parameter(timeSeries, name: str):
        items = []
        for ts in timeSeries:
            for p in ts["parameters"]:
                if p["name"] == name:
                    for v in p["values"]:
                        items.append(v)
        return items

    @staticmethod
    def __filter_by_date(timeSeries, date: datetime):
        items = []
        for ts in timeSeries:
            validTime = datetime.fromisoformat(ts["validTime"])
            ts["validTime"] = validTime
            if validTime.date() == date.date():
                items.append(ts)
        return items

    @staticmethod
    def __get_weather_forecast() -> str:
        """Calls SMHI API for the defined LONG/LAT and
        returns the raw response body containing a weather forecast
        for that geographic location"""
        base_url = "https://opendata-download-metfcst.smhi.se/"
        endpoint = (
            "api/category/pmp3g/version/2/geotype/point/lon/{long}/lat/{lat}/data.json"
        )
        complete_url = base_url + endpoint.format(long=SMHI.long, lat=SMHI.lat)
        return requests.get(complete_url).text


if __name__ == "__main__":
    SMHI.get_weather_descr()
