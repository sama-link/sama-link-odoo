from datetime import datetime
import pytz


class Converter:
    @staticmethod
    def float_to_time_obj(float_time):
        hours = int(float_time // 1)
        minutes = int((float_time % 1) * 60)
        time_str = f"{hours:02}:{minutes:02}:00"
        return datetime.strptime(time_str, "%H:%M:%S").time()

    @staticmethod
    def date_time_to_gmt_naive(date_obj, time_obj):
        cairo_tz = pytz.timezone("Africa/Cairo")
        gmt_tz = pytz.timezone("UTC")
        naive_datetime = datetime.combine(date_obj, time_obj)
        localized_datetime = cairo_tz.localize(naive_datetime)
        gmt_datetime = localized_datetime.astimezone(gmt_tz)
        return gmt_datetime.replace(tzinfo=None)