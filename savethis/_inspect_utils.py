"""Utilities for inspecting frames. """
# TODO: change name
import ast
import dis
import inspect
import sys
import types
from typing import Literal
from typing import Callable, Optional
try:
    from pydevd_tracing import SetTrace
except ImportError:
    SetTrace = sys.settrace

from . import _ast_utils, _dumper, _source_utils, _scope
from ._scope import Scope


class CallInfo:
    """Get information about the calling context.

    Contains the following information:
        - the function from which that call was made
        - the scope (see :class:`_scope.Scope`)

    Example:

    >>> def f():  # doctest: +SKIP
    ...     return CallInfo('here')
    >>> print(f().scope)  # doctest: +SKIP
    'Scope[__main__.f]'

    :param origin: Where to look for the call, can be
        - "nextmodule": use the first frame not in the module the object was created in
        - "here": use the frame the object was created in
    :param drop_n: Drop *n* levels from the calling scope.
    :param ignore_scope: Don't try to determine the scope (use the toplevel scope instead).
    """

    def __init__(self, origin: Literal['nextmodule', 'here'] = 'nextmodule',
                 drop_n: int = 0, ignore_scope: bool = False):
        assert isinstance(origin, inspect.FrameInfo) or origin in ('nextmodule', 'here')
        if isinstance(origin, inspect.FrameInfo):
            caller_frameinfo = origin
        if origin == 'nextmodule':
            calling_module_name = inspect.currentframe().f_back.f_globals['__name__']
            caller_frameinfo = outer_caller_frameinfo(calling_module_name)
        elif origin == 'here':
            caller_frameinfo = inspect.stack()[1]

        # TODO: is it redundant to keep the function? (as it is contained in the scope?)
        self.function: str = caller_frameinfo.function

        self.scope: Scope = self._determine_scope(caller_frameinfo, drop_n, ignore_scope)

    def _determine_scope(self, caller_frameinfo: inspect.FrameInfo,
                         drop_n: int, ignore_scope: bool) -> Scope:
        """Determine the scope of the caller frame. """
        module = _module(caller_frameinfo.frame)

        if self.function == '<module>' or ignore_scope:
            return Scope(module, inspect.getsource(caller_frameinfo.frame), [])

        return _get_scope_from_frame(caller_frameinfo.frame, drop_n)

    @property
    def module(self):
        """The calling module. """
        return self.scope.module


def _parent_frame(frame):
    """Get the parent (calling) frame of *frame*.

    This skips all frames that have a variable called "__SKIP_THIS_FRAME" in their locals.
    """
    parent = frame.f_back
    if parent is None or '__SKIP_THIS_FRAME' not in parent.f_locals:
        return parent
    return _parent_frame(parent)


# exclude these modules from detailed scope analysis (as that slows testing down in python 3.7.)
# TODO: remove when dropping 3.7 support?
_EXCLUDED_MODULES = ['pytest', 'pluggy', '_pytest']


def _get_scope_from_frame(frame, drop_n):
    """Get the :class:`~Scope` from the frame object *frame*. """
    module = _module(frame)
    # don't dive deeper for excluded modules
    parent = _parent_frame(frame)
    if any(module.__name__.startswith(excluded_module) for excluded_module in _EXCLUDED_MODULES):
        return Scope.toplevel(module)
    # don't dive deeper if parent is None
    if parent is None:
        return Scope.toplevel(module)
    # don't dive deeper after main
    if module.__name__ == '__main__' and _module(parent) != module:
        return Scope.toplevel(module)
    # don't dive deeper if not a call
    if frame.f_code.co_name == '<module>':
        return Scope.toplevel(module)

    try:
        call_source, locs = get_segment_from_frame(parent, 'call', return_locs=True)
    except (RuntimeError, FileNotFoundError, AttributeError, OSError):
        return Scope.toplevel(module)
    try:
        definition_source = _source_utils.get_source(frame.f_code.co_filename)
    except FileNotFoundError:
        return Scope.toplevel(module)
    calling_scope = _get_scope_from_frame(parent, 0)
    scope = Scope.from_source(definition_source, frame.f_lineno,
                                        call_source, module, drop_n,
                                        calling_scope, frame, locs)
    assert len(scope) <= 1, 'scope longer than 1 currently not supported'
    return scope


def non_init_caller_frameinfo(obj) -> inspect.FrameInfo:
    """Get the FrameInfo for the first outer frame that is not of an "__init__" method of *obj*.

    :param obj: The object to compare against.
    """
    stack = inspect.stack()
    frameinfo = None
    for frameinfo in stack[1:]:
        if frameinfo.function != '__init__':
            break
        if all(v != obj for v in frameinfo.frame.f_locals.values()):
            # if the frame is an __init__ method and the locals don't contain the
            # object, it's not not a super __init__
            break
    assert frameinfo is not None, 'frameinfo not found'
    return frameinfo


def trace_this(tracefunc: Callable, frame: Optional[types.FrameType] = None, *args, **kwargs):
    # TODO: do we need this?
    """Call in a function body to trace the rest of the function execution with function
    *tracefunc*. *tracefunc* must match the requirements for the argument of `sys.settrace`
    (in the documentation of which more details can be found).

    Example:

    >>> def tracefunc(frame, event, arg):
    ...     if event == 'return':
    ...         print('returning', arg)

    >>> def myfunction():
    ...     [...]
    ...     _trace_this(tracefunc)
    ...     return 123

    :param tracefunc: Trace function (see documentation of `sys.settrace` for details).
    :param frame: The frame to trace (defaults to the caller's frame).
    """
    previous_tracefunc = sys.gettrace()

    if frame is None:
        # default is the caller's frame
        frame = inspect.currentframe().f_back

    def trace(frame, event, arg):
        tracefunc(frame, event, arg, *args, **kwargs)
        if event == 'return':
            SetTrace(previous_tracefunc)
        if previous_tracefunc is not None:
            previous_tracefunc(frame, event, arg)

    if previous_tracefunc is None:
        # set global tracefunc to something, this is required to enable local tracing
        SetTrace(lambda _a, _b, _c: None)

    frame.f_trace = trace


def _instructions_up_to_call(x) -> list:
    """Get all instructions up to last CALL FUNCTION. """
    instructions = list(dis.get_instructions(x))
    i = 0
    for i, instruction in enumerate(instructions[::-1]):
        if instruction.opname.startswith('CALL_'):
            break
    return instructions[:-i]


def _instructions_in_name(x) -> list:
    """Get all LOAD_NAME and LOAD_ATTR instructions. """
    instructions = list(dis.get_instructions(x))
    i = 0
    for i, instruction in enumerate(instructions):
        if instruction.opname not in ('LOAD_NAME', 'LOAD_ATTR'):
            break
    return instructions[:i]


def _instructions_in_getitem(x) -> list:
    instructions = list(dis.get_instructions(x))
    return instructions[:-1]


def _instructions_up_to_offset(x, lasti: int) -> list:
    """Get all instructions up to offset *lasti*. """
    instructions = []
    for instruction in dis.get_instructions(x):
        instructions.append(instruction)
        if instruction.offset == lasti:
            break
    return instructions


def _module(frame: types.FrameType) -> types.ModuleType:
    """Get module of *frame*. """
    try:
        return frame.f_globals['_pd_module']
    except KeyError:
        return sys.modules[frame.f_globals['__name__']]


def outer_caller_frameinfo(module_name: str) -> inspect.FrameInfo:
    """Get the first level of the stack before entering the module with name *module_name*. """
    stack = inspect.stack()
    before = True
    for frameinfo in stack:
        if frameinfo.frame.f_globals['__name__'] == module_name:
            before = False
            continue
        if before:
            continue
        return frameinfo


def caller_module() -> types.ModuleType:
    """Get the module of the caller. """
    calling_module_name = inspect.currentframe().f_back.f_globals['__name__']
    return _module(outer_caller_frameinfo(calling_module_name).frame)


def caller_frame(n_back=1) -> types.FrameType:
    """Get the callers frame. """
    frame = inspect.currentframe()
    for _ in range(n_back):
        frame = frame.f_back
    calling_module_name = frame.f_globals['__name__']
    return outer_caller_frameinfo(calling_module_name).frame


def instructions_are_the_same(instr: dis.Instruction, target_instr: dis.Instruction,
                              frame=None):
    """Check if the disassembled instructions *instr* and *target_instr* are (basically) the same.

    Mainly this checks if the *opname* and *argval* of the two instructions are the same,
    additionally accounting for some subtleties involving code object - argvals and LOAD-operators.

    :param instr: Candidate instruction that should be matched to the target.
    :param target_instr: Target instruction.
    :param frame: Frame the target instruction came from.
    """
    # for the LOAD_FAST operator, get the argval from the frame's locals
    if (frame is not None and target_instr.opname == 'LOAD_FAST'
            and target_instr.argval in frame.f_locals
            and target_instr.argval in frame.f_code.co_varnames):
        argval = frame.f_locals[target_instr.argval]
    else:
        argval = target_instr.argval

    # if the instruction's argval contains code objects, compare the code
    instr_argval = getattr(instr.argval, 'co_code', instr.argval)
    target_argval = getattr(target_instr.argval, 'co_code', target_instr.argval)

    if instr_argval not in (target_argval, argval):
        return False

    if instr.opname == target_instr.opname:
        return True

    # load operations can have many different name, accept if both are load ops regardless
    # of which kind exactly
    load_ops = ('LOAD_NAME', 'LOAD_FAST', 'LOAD_GLOBAL', 'LOAD_CONST', 'LOAD_DEREF')
    return instr.opname in load_ops and target_instr.opname in load_ops


def get_segment_from_frame(caller_frame: types.FrameType, segment_type, return_locs=False) -> str:
    """Get a segment of a given type from a frame.

    *NOTE*: All this is rather hacky and should be changed as soon as python 3.11 becomes widely
    available as then it will be possible to get column information from frames
    (see inline comments).

    *segment_type* can be 'call', 'attribute', 'getitem'.
    """
    if segment_type == 'call':
        node_type = ast.Call
        instructions_finder = _instructions_up_to_call
    elif segment_type == 'attribute':
        node_type = ast.Attribute
        instructions_finder = _instructions_in_name
    elif segment_type == 'getitem':
        node_type = ast.Subscript
        instructions_finder = _instructions_in_getitem
    else:
        raise ValueError('Segment type not supported (must be one of "call", "attribute", '
                         '"getitem".')
    # we want to extract the precise init statement here (e.g. `MyClass(1, 2, 3)`
    # , for python 3.11 (currently in development) this can be done via co_positions
    # (see https://www.python.org/dev/peps/pep-0657/),
    # for now, as 3.11 isn't widely used, this requires the following hack:
    # extract the source of the class init statement
    try:
        full_source = caller_frame.f_globals['_pd_source']
    except KeyError:
        full_source = _source_utils.get_source(caller_frame.f_code.co_filename)

    lineno = caller_frame.f_lineno

    # disassemble and get the instructions up to the current position
    target_instrs = _instructions_up_to_offset(caller_frame.f_code,
                                               caller_frame.f_lasti)
    # filter out EXTENDED_ARG (instruction used for very large args in target_instrs, this won't
    # be present in instrs)
    target_instrs = [x for x in target_instrs if x.opname != 'EXTENDED_ARG']

    def check_segment(segment):
        # for each candidate, disassemble and compare the instructions to what we
        # actually have, a match means this is the correct statement
        instrs = instructions_finder(segment)
        if len(instrs) > len(target_instrs):
            return False
        for instr, target_instr in zip(instrs, target_instrs[-len(instrs):]):
            if not instructions_are_the_same(instr, target_instr, caller_frame):
                return False
        return True

    def check_statement(statement_node, source):
        # iterate over nodes of the correct type found in the statement and check them
        for node in _dumper.Finder(node_type).find(statement_node):
            segment = _ast_utils.unparse(node)
            if check_segment(segment):
                return _ast_utils.get_position(source, node)
        return None

    # get all segments in the source that correspond to calls and might thus
    # potentially be the class init
    locs = get_statement_at_line(_source_utils.original(full_source), lineno, check_statement)

    corrected_locs = (
        locs.lineno - 1,
        locs.end_lineno - 1,
        locs.col_offset,
        locs.end_col_offset
    )

    # cutting is necessary instead of just using the segment from above for support of
    # `_source_utils.ReplaceString`s
    cut_segment = _source_utils.cut(full_source, *corrected_locs)

    if return_locs:
        return (
            cut_segment, corrected_locs
        )

    assert cut_segment
    return cut_segment


def get_statement_at_line(source: str, lineno: int, checker):
    """Get statements at line *lineno* from a source string.

    :param source: The source to get the statements from.
    :param lineno: Line number which the statement must include. Counted from 1.
    :param checker: A function that checks each statement. It must return *None* if the check
        fails. If anything else is returned, that becomes the return value of this function.
    :returns: A list of tuples of string with the found statements and and offset between the
        beginning of the match and *lineno*.
    """
    module = _ast_utils.cached_parse(source)
    for stmt in module.body:
        position = _ast_utils.get_position(source, stmt)
        if position.lineno <= lineno <= position.end_lineno:
            res = checker(stmt, source)
            if res is not None:
                return res
    raise RuntimeError('Statement not found.')


def get_call_signature(calling_frame):
    """Get the call signature from *calling_frame*.

    Returns a tuple of

        - list of positional arguments
        - dict of keyword arguments
        - value of *args (as a string)
        - value of **kwargs (as a string)
    """
    call_source = get_segment_from_frame(calling_frame, 'call')
    return _scope._get_call_signature(call_source)


def get_my_call_signature():
    """Call from within a function to get its call signature.

    Returns a tuple of

        - list of positional arguments
        - dict of keyword arguments
        - value of *args (as a string)
        - value of **kwargs (as a string)

    (see also :func:`_scope._get_call_signature`).

    Example:

    >>> def f(a, *args, b=1, **kwargs): return get_my_call_signature()
    >>> f(1, 2, *[1, 2], b="hello", c=123, **{'1': 1, '2': 2})
    (['1', '2'], {'b': '"hello"', 'c': '123'}, '[1, 2]', "{'1': 1, '2': 2}")
    """
    return get_call_signature(inspect.currentframe().f_back.f_back)


def get_argument_assignments(*args, **kwargs):
    frame = caller_frame(2)
    signature = get_call_signature(frame)
    return _scope.Signature(*args, **kwargs, ignore_extra_kwargs=True) \
        .get_call_assignments(*signature)
