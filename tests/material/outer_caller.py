from savethis import _inspect_utils


def here():
    return _inspect_utils.outer_caller_frameinfo(__name__)


def caller_module():
    return _inspect_utils.caller_module()


def caller_frame():
    return _inspect_utils.caller_frame()
