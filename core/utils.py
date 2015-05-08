__author__ = 'Masutangu'
"""
    copy from apscheduler.util and python-rq
"""

import six
from inspect import isfunction, ismethod, getargspec
import signal
from datetime import date, datetime, time, timedelta, tzinfo
from pytz import timezone, utc
import re
from calendar import timegm


try:
    from inspect import signature
except ImportError:  # pragma: nocover
    try:
        from funcsigs import signature
    except ImportError:
        signature = None

_signames = dict((getattr(signal, signame), signame)
                 for signame in dir(signal)
                 if signame.startswith('SIG') and '_' not in signame)


def get_callable_name(func):
    """
    Returns the best available display name for the given function/callable.

    :rtype: str
    """

    # the easy case (on Python 3.3+)
    if hasattr(func, '__qualname__'):
        return func.__qualname__

    # class methods, bound and unbound methods
    f_self = getattr(func, '__self__', None) or getattr(func, 'im_self', None)
    if f_self and hasattr(func, '__name__'):
        f_class = f_self if isinstance(f_self, type) else f_self.__class__
    else:
        f_class = getattr(func, 'im_class', None)

    if f_class and hasattr(func, '__name__'):
        return '%s.%s' % (f_class.__name__, func.__name__)

    # class or class instance
    if hasattr(func, '__call__'):
        # class
        if hasattr(func, '__name__'):
            return func.__name__

        # instance of a class with a __call__ method
        return func.__class__.__name__

    raise TypeError('Unable to determine a name for %r -- maybe it is not a callable?' % func)


def obj_to_ref(obj):
    """
    Returns the path to the given object.

    :rtype: str
    """

    try:
        ref = '%s:%s' % (obj.__module__, get_callable_name(obj))
        obj2 = ref_to_obj(ref)
        if obj != obj2:
            raise ValueError
    except Exception:
        raise ValueError('Cannot determine the reference to %r' % obj)

    return ref


def ref_to_obj(ref):
    """
    Returns the object pointed to by ``ref``.

    :type ref: str
    """

    if not isinstance(ref, six.string_types):
        raise TypeError('References must be strings')
    if ':' not in ref:
        raise ValueError('Invalid reference')

    modulename, rest = ref.split(':', 1)
    try:
        obj = __import__(modulename)
    except ImportError:
        raise LookupError('Error resolving reference %s: could not import module' % ref)

    try:
        for name in modulename.split('.')[1:] + rest.split('.'):
            obj = getattr(obj, name)
        return obj
    except Exception:
        raise LookupError('Error resolving reference %s: error looking up object' % ref)

def check_callable_args(func, args, kwargs):
    """
    Ensures that the given callable can be called with the given arguments.

    :type args: tuple
    :type kwargs: dict
    """

    pos_kwargs_conflicts = []  # parameters that have a match in both args and kwargs
    positional_only_kwargs = []  # positional-only parameters that have a match in kwargs
    unsatisfied_args = []  # parameters in signature that don't have a match in args or kwargs
    unsatisfied_kwargs = []  # keyword-only arguments that don't have a match in kwargs
    unmatched_args = list(args)  # args that didn't match any of the parameters in the signature
    unmatched_kwargs = list(kwargs)  # kwargs that didn't match any of the parameters in the signature
    has_varargs = has_var_kwargs = False  # indicates if the signature defines *args and **kwargs respectively

    if signature:
        try:
            sig = signature(func)
        except ValueError:
            return  # signature() doesn't work against every kind of callable

        for param in six.itervalues(sig.parameters):
            if param.kind == param.POSITIONAL_OR_KEYWORD:
                if param.name in unmatched_kwargs and unmatched_args:
                    pos_kwargs_conflicts.append(param.name)
                elif unmatched_args:
                    del unmatched_args[0]
                elif param.name in unmatched_kwargs:
                    unmatched_kwargs.remove(param.name)
                elif param.default is param.empty:
                    unsatisfied_args.append(param.name)
            elif param.kind == param.POSITIONAL_ONLY:
                if unmatched_args:
                    del unmatched_args[0]
                elif param.name in unmatched_kwargs:
                    unmatched_kwargs.remove(param.name)
                    positional_only_kwargs.append(param.name)
                elif param.default is param.empty:
                    unsatisfied_args.append(param.name)
            elif param.kind == param.KEYWORD_ONLY:
                if param.name in unmatched_kwargs:
                    unmatched_kwargs.remove(param.name)
                elif param.default is param.empty:
                    unsatisfied_kwargs.append(param.name)
            elif param.kind == param.VAR_POSITIONAL:
                has_varargs = True
            elif param.kind == param.VAR_KEYWORD:
                has_var_kwargs = True
    else:
        if not isfunction(func) and not ismethod(func) and hasattr(func, '__call__'):
            func = func.__call__

        try:
            argspec = getargspec(func)
        except TypeError:
            return  # getargspec() doesn't work certain callables

        argspec_args = argspec.args if not ismethod(func) else argspec.args[1:]
        arg_defaults = dict(zip(reversed(argspec_args), argspec.defaults or ()))
        has_varargs = bool(argspec.varargs)
        has_var_kwargs = bool(argspec.keywords)
        for arg in argspec_args:
            if arg in unmatched_kwargs and unmatched_args:
                pos_kwargs_conflicts.append(arg)
            elif unmatched_args:
                del unmatched_args[0]
            elif arg in unmatched_kwargs:
                unmatched_kwargs.remove(arg)
            elif arg not in arg_defaults:
                unsatisfied_args.append(arg)

    # Make sure there are no conflicts between args and kwargs
    if pos_kwargs_conflicts:
        raise ValueError('The following arguments are supplied in both args and kwargs: %s' %
                         ', '.join(pos_kwargs_conflicts))

    # Check if keyword arguments are being fed to positional-only parameters
    if positional_only_kwargs:
        raise ValueError('The following arguments cannot be given as keyword arguments: %s' %
                         ', '.join(positional_only_kwargs))

    # Check that the number of positional arguments minus the number of matched kwargs matches the argspec
    if unsatisfied_args:
        raise ValueError('The following arguments have not been supplied: %s' % ', '.join(unsatisfied_args))

    # Check that all keyword-only arguments have been supplied
    if unsatisfied_kwargs:
        raise ValueError('The following keyword-only arguments have not been supplied in kwargs: %s' %
                         ', '.join(unsatisfied_kwargs))

    # Check that the callable can accept the given number of positional arguments
    if not has_varargs and unmatched_args:
        raise ValueError('The list of positional arguments is longer than the target callable can handle '
                         '(allowed: %d, given in args: %d)' % (len(args) - len(unmatched_args), len(args)))

    # Check that the callable can accept the given keyword arguments
    if not has_var_kwargs and unmatched_kwargs:
        raise ValueError('The target callable does not accept the following keyword arguments: %s' %
                         ', '.join(unmatched_kwargs))


def signal_name(signum):
    # Hackety-hack-hack: is there really no better way to reverse lookup the
    # signal name?  If you read this and know a way: please provide a patch :)
    try:
        return _signames[signum]
    except KeyError:
        return 'SIG_UNKNOWN'



def timedelta_seconds(delta):
    """
    Converts the given timedelta to seconds.

    :type delta: timedelta
    :rtype: float
    """
    return delta.days * 24 * 60 * 60 + delta.seconds + \
        delta.microseconds / 1000000.0


def astimezone(obj):
    """
    Interprets an object as a timezone.

    :rtype: tzinfo
    """

    if isinstance(obj, six.string_types):
        return timezone(obj)
    if isinstance(obj, tzinfo):
        if not hasattr(obj, 'localize') or not hasattr(obj, 'normalize'):
            raise TypeError('Only timezones from the pytz library are supported')
        if obj.zone == 'local':
            raise ValueError('Unable to determine the name of the local timezone -- use an explicit timezone instead')
        return obj
    if obj is not None:
        raise TypeError('Expected tzinfo, got %s instead' % obj.__class__.__name__)


_DATE_REGEX = re.compile(
    r'(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})'
    r'(?: (?P<hour>\d{1,2}):(?P<minute>\d{1,2}):(?P<second>\d{1,2})'
    r'(?:\.(?P<microsecond>\d{1,6}))?)?')


def convert_to_datetime(input, tz, arg_name):
    """
    Converts the given object to a timezone aware datetime object.
    If a timezone aware datetime object is passed, it is returned unmodified.
    If a native datetime object is passed, it is given the specified timezone.
    If the input is a string, it is parsed as a datetime with the given timezone.

    Date strings are accepted in three different forms: date only (Y-m-d),
    date with time (Y-m-d H:M:S) or with date+time with microseconds
    (Y-m-d H:M:S.micro).

    :param str|datetime input: the datetime or string to convert to a timezone aware datetime
    :param datetime.tzinfo tz: timezone to interpret ``input`` in
    :param str arg_name: the name of the argument (used in an error message)
    :rtype: datetime
    """

    if input is None:
        return
    elif isinstance(input, datetime):
        datetime_ = input
    elif isinstance(input, date):
        datetime_ = datetime.combine(input, time())
    elif isinstance(input, six.string_types):
        m = _DATE_REGEX.match(input)
        if not m:
            raise ValueError('Invalid date string')
        values = [(k, int(v or 0)) for k, v in m.groupdict().items()]
        values = dict(values)
        datetime_ = datetime(**values)
    else:
        raise TypeError('Unsupported type for %s: %s' % (arg_name, input.__class__.__name__))

    if datetime_.tzinfo is not None:
        return datetime_
    if tz is None:
        raise ValueError('The "tz" argument must be specified if %s has no timezone information' % arg_name)
    if isinstance(tz, six.string_types):
        tz = timezone(tz)

    try:
        return tz.localize(datetime_, is_dst=None)
    except AttributeError:
        raise TypeError('Only pytz timezones are supported (need the localize() and normalize() methods)')


def datetime_to_utc_timestamp(timeval):
    """
    Converts a datetime instance to a timestamp.

    :type timeval: datetime
    :rtype: float
    """

    if timeval is not None:
        return timegm(timeval.utctimetuple()) + timeval.microsecond / 1000000


def utc_timestamp_to_datetime(timestamp):
    """
    Converts the given timestamp to a datetime instance.

    :type timestamp: float
    :rtype: datetime
    """

    if timestamp is not None:
        return datetime.fromtimestamp(timestamp, utc)