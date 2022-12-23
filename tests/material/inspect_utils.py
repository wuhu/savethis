from savethis import _inspect_utils


def call_info_nextmodule():
    return _inspect_utils.CallInfo('nextmodule')

def call_info_here():
    return _inspect_utils.CallInfo('here')

def arg_assignments(a, b, c):
    return _inspect_utils.get_argument_assignments(['a', 'b', 'c'])
