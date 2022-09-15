from typing import Optional, Union
from django.conf import settings, ENVIRONMENT_VARIABLE

import functools
from contextlib import ContextDecorator
from datetime import datetime, timedelta, tzinfo, date, time
from threading import local
import pytz


def get_dj_base_path():
    """
    Gets the Django Base Folder Path using the django Environment variable that stores the module
    :return:
    """
    import os
    return os.path.dirname(os.path.dirname(os.path.abspath(os.environ.get(ENVIRONMENT_VARIABLE))))


def strip_html_tags(html):
    """
    Remove script and style from html
    :param html: the full html string to be parsed
    :return: the parsed html
    """
    import re
    return re.sub('{[^<]+?}', '',
                  re.sub('<[^<]+?>', '',
                         re.sub(r'<style.*?/style>', '',
                                re.sub(r'<(script).*?</\1>(?s)', '', html))))


def merge_request_data(request):
    """
    MERGE ALL REQUEST DATA. GET, POST, or api data
    :param request: Can be HTTP, or DRF request object
    :return: a dictionary with all data
    """
    data = {}
    if request.GET:
        for k in request.GET.keys():
            data[k] = request.GET.get(k)
    if request.POST:
        for k in request.POST.keys():
            data[k] = request.POST.get(k)
    if hasattr(request, 'data') and request.data:
        for k in request.data.keys():
            data[k] = request.data.get(k)
    return data


def data_from_request(request, possible_keys: Union[list, tuple, str], default_val=None):
    """
    Give me the request object, and the data key you want to find, and I'll find it.
    @param request: request object
    @param possible_keys: key, or keys to look under
    @param default_val: None by default
    @return: any data that was found
    """
    if type(possible_keys) is str:
        possible_keys = possible_keys.split(",")

    val = None
    for key in possible_keys:
        key = str(key).strip()  # remove spaces in front and behind of string
        val = request.GET.get(
            key, request.POST.get(
                key, request.data.get(key, default_val) if hasattr(request, 'data') else default_val))
        if val:
            break
    return val


def reset_connections():
    """
    Ask Django to close the connections that are invalid.
    (Mostly useful for expired shell db connections.)
    """
    from django.db import connections
    for conn in connections.all():
        conn.close_if_unusable_or_obsolete()


def is_valid_dict(d_obj: dict, key: str):
    """
    Used for parsing dictionary values passed from JSON-- checks if it exists with a VALID value
    :param d_obj: dictionary
    :param key: the key
    :return: Upper case value
    """
    val = d_obj.get(key, '')
    val = str(val).strip() if val else None
    return True if val and check_valid(val) else False


def check_valid(value):
    """
    Evaluate values to determine if it is valid (values from web)
    """
    val = str(value).upper().strip()
    return False if val == 'NONE' or val == 'NULL' or val == 'UNDEFINED' else True


class ExUtil:  # Django Exception Utilities

    BASE_DIR = get_dj_base_path()

    @classmethod
    def ex_to_str(cls, ex, debug=False, force_human=False):  # exception_to_string
        """
        Take any exception and convert to something more useful
        :param ex: Any Exception object
        :param debug: Always return full traceback detail if debug is enabled (also looks at django conf)
        :param force_human: gives a simplified traceback
        :return: A string if an exception is passed, otherwise, None
        """
        import traceback
        if type(ex) is BaseException:
            if not force_human and (settings.DEBUG or debug):
                return ''.join(traceback.format_exception(etype=type(ex), value=ex, tb=ex.__traceback__))
            else:
                return cls.get_human_traceback(ex)
        else:
            return None

    @staticmethod
    def traceback_file_to_module_path(filename, base_path):
        return str(filename).replace(base_path, '').replace('\\', '.').replace('/', '.').replace('.py', '')[1:]

    @classmethod
    def get_human_traceback(cls, ex: Optional[Exception]) -> str:
        """
        Return Text Detail of the first and last relevant frame.
        :param ex: Exception Object
        :return: a formatted string containing the first and last relevant frame
        """
        from traceback import TracebackException
        tbex = TracebackException.from_exception(ex) if ex else None

        exception_string = f"MESSAGE: {str(tbex) if tbex else 'No traceback available.'}"
        if tbex and not exception_string.endswith(":HIDE_FRAMES"):
            found_frames = False
            for summary in tbex.stack:
                if str(summary.filename).startswith(cls.BASE_DIR):
                    code_path = cls.traceback_file_to_module_path(summary.filename, cls.BASE_DIR)
                    exception_string += f'\r\nFIRST FRAME: {code_path}.{summary.name}:{str(summary.lineno)}'
                    found_frames = True
                    break
            if found_frames:
                for i in range(len(tbex.stack) - 1, -1, -1):  # reverse order (first piece of our code with an issue)
                    summary = tbex.stack[i]
                    if str(summary.filename).startswith(cls.BASE_DIR):
                        code_path = cls.traceback_file_to_module_path(summary.filename, cls.BASE_DIR)
                        exception_string += f'\r\nLAST FRAME: {code_path}.{summary.name}:{str(summary.lineno)}'
                        break
            else:
                first_frame = tbex.stack[0]
                last_frame = tbex.stack[len(tbex.stack) - 1]
                first_path = cls.traceback_file_to_module_path(first_frame.filename, cls.BASE_DIR)
                last_path = cls.traceback_file_to_module_path(last_frame.filename, cls.BASE_DIR)
                exception_string += f'\r\nFIRST FRAME: {first_path}.{first_frame.name}:{str(first_frame.lineno)}'
                exception_string += f'\r\nLAST FRAME: {last_path}.{last_frame.name}:{str(last_frame.lineno)}'
        elif exception_string.endswith("HIDE_FRAMES"):
            exception_string = exception_string.replace(":HIDE_FRAMES", "")

        return exception_string

    @classmethod
    def try_method(cls, func, *args, **kwargs):
        error = False
        message = "Success"
        debug = kwargs.pop('try_method_debug', False)
        force_human = kwargs.pop('try_method_force_human', False)
        default_value = kwargs.pop('try_method_default', None)

        try:
            method_result = func(*args, **kwargs)
        except BaseException as ex:
            error = True
            method_result = default_value
            message = cls.ex_to_str(ex, debug, force_human)
        return {'error': error, 'message': message, 'result': method_result}

    @classmethod
    def try_method_simple(cls, func, *args, **kwargs):
        return cls.try_method(func, *args, **kwargs).get('result')


class ModelUtil:
    @staticmethod
    def stp(str_val: str):
        """
        Strip out all extra spaces and "unprintable" values from a string
        :param str_val: The string value to clean up
        :return: The parsed string value
        """
        import string
        printable = set(string.printable)
        if str_val and type(str_val) is str:
            str_val = str_val.strip()
        if type(str_val) is str:
            str_val = ''.join(filter(lambda x: x in printable, str_val))
        return str_val

    @staticmethod
    def obj_int_if_possible(obj):
        obj_str = str(obj)
        try:
            obj_val = int(obj_str)
        except:
            obj_val = obj_str
        return obj_val

    @staticmethod
    def get_content_type(model_class):
        """
        Return the content type for the model
        """
        from django.contrib.contenttypes.models import ContentType
        return ContentType.objects.get_for_model(model_class, for_concrete_model=False)

    @staticmethod
    def m2m_update(model_obj, m2m: dict, pre_m2m: dict):
        """
        Used by save_model to gather changes for ManyToMany fields
        """
        updated_vals = {}
        if len(m2m.keys()) > 0:
            for k, v in m2m.items():
                sync_method = '{0}_sync'.format(k)
                field = getattr(model_obj, k)
                compare = [o.id for o in field.all()]
                difference = False
                if type(v) is list:
                    for val in v:
                        if val not in compare:
                            difference = True
                    if not difference:
                        for c in compare:
                            if c not in v:
                                difference = True
                else:
                    if v not in compare:
                        difference = True
                if difference:
                    updated_vals[k] = 1
                field.set(v)
                if hasattr(model_obj, sync_method) and callable(getattr(model_obj, sync_method)):
                    # call the custom m2m sync method
                    getattr(model_obj, sync_method)(
                        [int(i) for i in str(pre_m2m[k]).split(',')]
                        if pre_m2m and k in pre_m2m and len(pre_m2m[k]) > 0 else [])
        elif pre_m2m:
            for key in pre_m2m.keys():
                field = getattr(model_obj, key)
                compare = [o.id for o in field.all()]
                if compare:
                    updated_vals[key] = 0
                field.clear()
        return updated_vals


class DateUtil:
    """
    Timezone-related classes and functions.
    """
    # UTC time zone as a tzinfo instance.
    utc = pytz.utc

    # UTC and local time zones
    DT24_FMT_1 = "%B %d, %Y, %H:%M:%S"  # "September 18, 2017, 22:19:55"
    DT24_FMT_2 = "%Y-%m-%dT%H:%M:%SZ"  # "2018-03-12T10:12:45Z"
    DT24_FMT_3 = "%Y-%m-%dT%H:%M:%S.%fZ"
    DT24_FMT_3_D = "%Y-%m-%d"
    DT24_UGLY = "%Y%m%d%H%M%S%f%z"  # like DT24_FMT_3, but no separation
    DAY_UGLY = "%Y%m%d"

    UTC_FMT_1 = "%Y-%m-%dT%H:%M:%S+00:00"
    UTC_FMT_2 = "%Y-%m-%dT%H:%M:%S.%f+00:00"
    DT12_FMT_1 = "%b %d %Y at %I:%M%p"  # "Jun 28 2018 at 7:40AM"
    DT12_FMT_2 = "%a,%d/%m/%y,%I:%M%p"  # "Sun,05/12/99,12:30PM"
    CAL_FMT_1 = "%a, %d %B, %Y"  # "Mon, 21 March, 2015"

    DEFAULT_HUMAN_FMT = "%Y-%m-%d %I:%M %p"

    FORMAT_RETRY = [DT24_FMT_3, DT24_FMT_3_D, DT24_UGLY, DAY_UGLY, DT24_FMT_2, DT24_FMT_1]

    class FixedOffset(tzinfo):
        """
        Fixed offset in minutes east from UTC. Taken from Python's docs.

        Kept as close as possible to the reference version. __init__ was changed
        to make its arguments optional, according to Python's requirement that
        tzinfo subclasses can be instantiated without arguments.
        """

        def __init__(self, offset: Optional[int] = None, name: Optional[str] = None):
            if offset is not None:
                self.__offset = timedelta(minutes=offset)
            if name is not None:
                self.__name = name

        def utcoffset(self, dt: datetime):
            return self.__offset

        def tzname(self, dt: datetime):
            return self.__name

        def dst(self, dt: datetime):
            return timedelta(0)

    @classmethod
    def datetime_from_dt_string(cls, string_dt: Optional[str]) -> Optional[datetime]:
        if string_dt:
            return datetime.strptime(
                string_dt, cls.DEFAULT_HUMAN_FMT)
        else:
            return None

    @classmethod
    def date_from_human_dt_string(cls, string_date_time) -> datetime:
        return datetime.strptime(string_date_time, cls.DEFAULT_HUMAN_FMT)

    @classmethod
    def loads(cls, string_date: str, string_format: str = None) -> datetime:  # "%Y-%m-%dT%H:%M:%S.%fZ"
        """
        Meant to be used for quick datetime formatting
        :param string_date: the input date string
        :param string_format: the format string
        :return: a datetime object
        """
        if not string_format:
            out_ex = None
            for fmt in cls.FORMAT_RETRY:
                try:
                    out_val = datetime.strptime(string_date, fmt)
                    out_ex = None
                except ValueError as ex:
                    out_val = None
                    out_ex = ex
                if out_val is not None:
                    return out_val
            if out_ex is not None:
                raise ValueError("string_format was not detected. Please specify correct string_format.")

        return datetime.strptime(string_date, string_format)

    @classmethod
    def dumps(cls, in_date: Union[date, datetime], string_format: str = None) -> str:  # "%Y-%m-%dT%H:%M:%S.%fZ"
        """
        Quickly dump a date/datetime to a string
        :param in_date: the input date/datetime object
        :param string_format: the date format string
        :return: a date-formatted string
        """
        if not string_format:
            string_format = cls.DT24_FMT_3
        return in_date.strftime(string_format)

    @staticmethod
    def datespan(start_date, end_date, delta=timedelta(days=1)):
        """
        For iterating between two dates using a specific delta
        ex: for daytime in 'datespan':

        :param start_date: start date
        :param end_date: end date
        :param delta: the timedelta object
        :return: yields each datetime object
        """
        current_date = start_date
        while current_date < end_date:
            yield current_date
            current_date += delta

    @classmethod
    def mdelta(cls, delta: int, date_obj: datetime = None) -> datetime:
        if not date_obj:
            date_obj = cls.now()
        return cls.monthdelta(date_obj, delta)

    @staticmethod
    def week(in_date: datetime, offset_days=0) -> int:
        return int((in_date + timedelta(days=offset_days)).isocalendar()[1])

    @staticmethod
    def quarter(in_date: datetime) -> int:
        return (in_date.month + 2) // 3

    @staticmethod
    def monthdelta(in_date: datetime, delta: int) -> datetime:
        """
        Returns a datatime a certain number of months from the input datetime
        :param in_date: input datetime object
        :param delta: the difference in months (can be +/-)
        :return: the resulting datetime object
        """
        m, y = (in_date.month + delta) % 12, in_date.year + (in_date.month + delta - 1) // 12
        if not m:
            m = 12
        # return the day, but with caveats dependent on the number of total days in the new month
        d = min(in_date.day,  # input current day
                [31, 29 if y % 4 == 0 and (not y % 100 == 0 or y % 400 == 0) else 28,
                 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][
                    m - 1])  # last day of month each month, but just the current month
        return in_date.replace(day=d, month=m, year=y)

    @staticmethod
    def date_from_string(string_date: str, has_time: bool = False, long_time: bool = False) -> datetime:
        return datetime.strptime(
            string_date,
            "%Y-%m-%d{0}{1}{2}".format("T" if has_time and long_time else "",
                                       "{0}%H:%M:%S"
                                       "".format(" " if not long_time else "")
                                       if has_time else "",
                                       ".%f%z" if has_time and long_time else "")) if string_date else None

    @staticmethod
    def get_first_date_of_month(date_val: Union[date, datetime]):
        return date_val.replace(day=1)

    @staticmethod
    def get_last_date_of_month(date_val: Union[date, datetime]):
        next_month = date_val.replace(day=28) + timedelta(days=4)
        return next_month - timedelta(days=next_month.day)

    @classmethod
    def get_first_date_of_the_quarter(cls, date_val):
        q = cls.quarter(date_val)
        return datetime(date_val.year, 3 * q - 2, 1)

    @classmethod
    def get_last_date_of_the_quarter(cls, date_val):
        q = cls.quarter(date_val)
        month = 3 * q
        remaining = month / 12
        return datetime(date_val.year + remaining, month % 12 + 1, 1) - timedelta(days=1)

    @classmethod
    def dago_90(cls):
        return cls.date_to_string(cls.localdate() + timedelta(days=-90))

    @classmethod
    def dago_60(cls):
        return cls.date_to_string(cls.localdate() + timedelta(days=-60))

    @classmethod
    def dt_to_ms(cls, date_obj=None):
        if date_obj is None:
            date_obj = cls.now()
        return int(date_obj.timestamp() * 1000) if date_obj and type(date_obj) is datetime else None

    # noinspection PyIncorrectDocstring
    @classmethod
    def past(cls, **kwargs) -> datetime:
        """
        Accepts timedelta keyword arguments
        :param days: float
        :param seconds: float
        :param microseconds: float
        :param milliseconds: float
        :param minutes: float
        :param hours: float
        :param weeks: float
        :return: the past datetime
        """
        return cls.now() - timedelta(**kwargs)

    # noinspection PyIncorrectDocstring
    @classmethod
    def future(cls, **kwargs) -> datetime:
        """
        Accepts timedelta keyword arguments
        :param days: float
        :param seconds: float
        :param microseconds: float
        :param milliseconds: float
        :param minutes: float
        :param hours: float
        :param weeks: float
        :return: the future datetime
        """
        return cls.now() + timedelta(**kwargs)

    @staticmethod
    def date_to_string(in_date: Union[datetime, date], show_time=False, long_time=False, ampm_time=False) -> str:
        """
        Convert the datetime value to a string. Choose to show time in several ways, or just the date value.
        :param in_date: The datetime object to convert.
        :param show_time: Boolean, show the time value
        :param long_time: Boolean, show the long time value
        :param ampm_time: show am/pm
        :return: The datetime string
        """
        return in_date.strftime("%Y-%m-%d{0}{1}{2}".format(
            "T" if show_time and long_time else "",
            "{0}%I:%M %p".format(" " if not long_time else "")
            if ampm_time and show_time else
            "{0}%H:%M:%S".format(" " if not long_time else "")
            if show_time else "", ".%f%z" if show_time and long_time else "")) if in_date else None

    @classmethod
    def date_to_ugly(cls, in_date: Union[datetime, date]):
        return in_date.strftime(cls.DT24_UGLY)

    @classmethod
    def get_fixed_timezone(cls, offset: Union[timedelta, int]) -> FixedOffset:
        """Return a tzinfo instance with a fixed offset from UTC."""
        if isinstance(offset, timedelta):
            offset = offset.total_seconds() // 60
        sign = '-' if offset < 0 else '+'
        hhmm = '%02d%02d' % divmod(abs(offset), 60)
        name = sign + hhmm
        return cls.FixedOffset(offset, name)

    # In order to avoid accessing settings at compile time,
    # wrap the logic in a function and cache the result.
    @staticmethod
    @functools.lru_cache()
    def get_default_timezone():
        """
        Return the default time zone as a tzinfo instance.

        This is the time zone defined by settings.TIME_ZONE.
        """
        return pytz.timezone(settings.TIME_ZONE)

    # This function exists for consistency with get_current_timezone_name
    @classmethod
    def get_default_timezone_name(cls):
        """Return the name of the default time zone."""
        return cls._get_timezone_name(cls.get_default_timezone())

    _active = local()

    @classmethod
    def get_current_timezone(cls):
        """Return the currently active time zone as a tzinfo instance."""
        return getattr(cls._active, "value", cls.get_default_timezone())

    @classmethod
    def get_current_timezone_name(cls):
        """Return the name of the currently active time zone."""
        return cls._get_timezone_name(cls.get_current_timezone())

    @staticmethod
    def _get_timezone_name(timezone) -> object:
        """Return the name of ``timezone``."""
        return timezone.tzname(None)

    # Timezone selection functions.

    # These functions don't change os.environ['TZ'] and call time.tzset()
    # because it isn't thread safe.

    @classmethod
    def activate(cls, timezone: Union[tzinfo, str]):
        """
        Set the time zone for the current thread.

        The ``timezone`` argument must be an instance of a tzinfo subclass or a
        time zone name.
        """
        if isinstance(timezone, tzinfo):
            cls._active.value = timezone
        elif isinstance(timezone, str):
            cls._active.value = pytz.timezone(timezone)
        else:
            raise ValueError("Invalid timezone: %r" % timezone)

    @classmethod
    def deactivate(cls):
        """
        Unset the time zone for the current thread.

        Django will then use the time zone defined by settings.TIME_ZONE.
        """
        if hasattr(cls._active, "value"):
            del cls._active.value

    class override(ContextDecorator):
        """
        Temporarily set the time zone for the current thread.

        This is a context manager that uses django.utils.timezone.activate()
        to set the timezone on entry and restores the previously active timezone
        on exit.

        The ``timezone`` argument must be an instance of a ``tzinfo`` subclass, a
        time zone name, or ``None``. If it is ``None``, Django enables the default
        time zone.
        """

        def __init__(self, timezone):
            self.timezone = timezone

        def __enter__(self):
            self.old_timezone = getattr(DateUtil._active, 'value', None)
            if self.timezone is None:
                DateUtil.deactivate()
            else:
                DateUtil.activate(self.timezone)

        def __exit__(self, exc_type, exc_value, traceback):
            if self.old_timezone is None:
                DateUtil.deactivate()
            else:
                DateUtil._active.value = self.old_timezone

    # Templates

    @classmethod
    def template_localtime(cls, value, use_tz=None):
        """
        Check if value is a datetime and converts it to local time if necessary.

        If use_tz is provided and is not None, that will force the value to
        be converted (or not), overriding the value of settings.USE_TZ.

        This function is designed for use by the template engine.
        """
        should_convert = (
                isinstance(value, datetime) and
                (settings.USE_TZ if use_tz is None else use_tz) and
                not cls.is_naive(value) and
                getattr(value, 'convert_to_local_time', True)
        )
        return cls.localtime(value) if should_convert else value

    # Utilities
    @classmethod
    def now(cls):
        """
        Return an aware or naive datetime.datetime, depending on settings.USE_TZ.
        """
        if settings.USE_TZ:
            # timeit shows that datetime.now(tz=utc) is 24% slower
            return datetime.utcnow().replace(tzinfo=cls.utc)
        else:
            return datetime.now()

    @classmethod
    def localtime(cls, value=None, timezone=None):
        """
        Convert an aware datetime.datetime to local time.

        Only aware datetimes are allowed. When value is omitted, it defaults to
        now().

        Local time is defined by the current time zone, unless another time zone
        is specified.
        """
        if value is None:
            value = cls.now()
        if timezone is None:
            timezone = cls.get_current_timezone()
        # Emulate the behavior of astimezone() on Python < 3.6.
        if settings.USE_TZ:  # Trying to make the USE_TZ fully switchable (Agile)
            if cls.is_naive(value):
                raise ValueError("localtime() cannot be applied to a naive datetime")

            return value.astimezone(timezone)
        else:
            return value

    @classmethod
    def strptime(cls, string, str_format, default=localtime()):
        if string:
            return cls.make_aware(datetime.strptime(string, str_format))
        else:
            return default

    @classmethod
    def localdate(cls, value=None, timezone=None):
        """
        Convert an aware datetime to local time and return the value's date.

        Only aware datetimes are allowed. When value is omitted, it defaults to
        now().

        Local time is defined by the current time zone, unless another time zone is
        specified.
        """
        return cls.localtime(value, timezone).date()

    # By design, these four functions don't perform any checks on their arguments.
    # The caller should ensure that they don't receive an invalid value like None.

    @staticmethod
    def is_aware(value):
        """
        Determine if a given datetime.datetime is aware.

        The concept is defined in Python's docs:
        https://docs.python.org/library/datetime.html#datetime.tzinfo

        Assuming value.tzinfo is either None or a proper datetime.tzinfo,
        value.utcoffset() implements the appropriate logic.
        """
        return value.utcoffset() is not None

    @staticmethod
    def is_naive(value):
        """
        Determine if a given datetime.datetime is naive.

        The concept is defined in Python's docs:
        https://docs.python.org/library/datetime.html#datetime.tzinfo

        Assuming value.tzinfo is either None or a proper datetime.tzinfo,
        value.utcoffset() implements the appropriate logic.
        """
        return value.utcoffset() is None

    @classmethod
    def make_aware(cls, value, timezone=None, is_dst=None):
        """Make a naive datetime.datetime in a given time zone aware."""

        if settings.USE_TZ:  # Make timezones switchable!!
            if timezone is None:
                timezone = cls.get_current_timezone()
            if hasattr(timezone, 'localize'):
                # This method is available for pytz time zones.
                return timezone.localize(value, is_dst=is_dst)
            else:
                # Check that we won't overwrite the timezone of an aware datetime.
                if cls.is_aware(value):
                    raise ValueError(
                        "make_aware expects a naive datetime, got %s" % value)
                # This may be wrong around DST changes!
                return value.replace(tzinfo=timezone)
        else:
            return value

    @classmethod
    def make_naive(cls, value, timezone=None):
        """Make an aware datetime.datetime naive in a given time zone."""
        if timezone is None:
            timezone = cls.get_current_timezone()
        # Emulate the behavior of astimezone() on Python < 3.6.
        if cls.is_naive(value):
            raise ValueError("make_naive() cannot be applied to a naive datetime")
        return value.astimezone(timezone).replace(tzinfo=None)

    @staticmethod
    def calc_sec(dt: datetime):
        """
        Get total seconds since 1970
        :param dt: datetime object
        :return: seconds since 1970
        """
        epoch = datetime(1970, 1, 1, tzinfo=dt.tzinfo)
        return (dt - epoch).total_seconds()

    @staticmethod
    def calc_days(dt: date):
        """
        Get total days since 1970
        :param dt: datetime object
        :return: days since 1970
        """
        epoch = date(1970, 1, 1)
        delta: timedelta = (dt - epoch)
        return delta.days

    @classmethod
    def time_ago(cls, in_time=False):
        """
        Get a datetime object or a int() Epoch timestamp and return a
        pretty string like 'an hour ago', 'Yesterday', '3 months ago',
        'just now', etc
        Modified from: http://stackoverflow.com/a/1551394/141084
        """
        dt_now = cls.localtime()
        if type(in_time) is int:
            diff = dt_now - datetime.fromtimestamp(in_time)
        elif isinstance(in_time, datetime):
            in_time = datetime(in_time.year, in_time.month, in_time.day,
                               in_time.hour, in_time.minute, in_time.second)
            diff = dt_now - in_time
        elif not in_time:
            diff = dt_now - dt_now
        else:
            raise ValueError('invalid date %s of type %s' % (in_time, type(in_time)))
        second_diff = int(round(diff.seconds, 0))
        day_diff = int(round(diff.days, 0))

        if day_diff < 0:
            return ''

        if day_diff == 0:
            if second_diff < 10:
                return "just now"
            if second_diff < 60:
                return str(second_diff) + " seconds ago"
            if second_diff < 120:
                return "a minute ago"
            if second_diff < 3600:
                minute_val = int(round(second_diff / 60, 0))
                return str(minute_val) + " minutes ago" if minute_val > 1 else "one minute ago"
            if second_diff < 7200:
                return "an hour ago"
            if second_diff < 86400:
                hour_val = int(round(second_diff / 3600, 0))
                return str(hour_val) + " hours ago" if hour_val > 1 else "one hour ago"
        if day_diff == 1:
            return "Yesterday"
        if day_diff < 7:
            return str(day_diff) + " days ago" if day_diff > 1 else "one day ago"
        if day_diff < 31:
            week_val = int(round(day_diff / 7))
            return str(week_val) + " weeks ago" if week_val > 1 else "one week ago"
        if day_diff < 365:
            minute_val = int(round(day_diff / 30))
            return str(minute_val) + " months ago" if minute_val > 1 else "one month ago"
        return str(round(day_diff / 365)) + " years ago" if round(day_diff / 365) > 1 else "one year ago"

    @staticmethod
    def month_to_date_span(in_date):
        """ Get the current month start and end from the end date """
        return in_date.replace(day=1), in_date

    @classmethod
    def month_span(cls, in_date):
        """ Get the current date's month start and end """
        return in_date.replace(day=1), cls.get_last_date_of_month(in_date)

    @classmethod
    def months_span(cls, in_date, prev_months: int):
        """ Get the start and end of the span """
        return cls.monthdelta(in_date, -prev_months).replace(day=1), cls.get_last_date_of_month(in_date)

    @classmethod
    def months_to_date_span(cls, in_date, prev_months: int):
        """ Get the previous # of months start and end from the end date """
        return cls.monthdelta(in_date, -prev_months).replace(day=1), in_date
