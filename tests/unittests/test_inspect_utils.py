import inspect
import pytest
import sys

from savethis import _inspect_utils, _ast_utils
from savethis._source_utils import get_source

from tests.material import inspect_utils


toplevel_callinfo = _inspect_utils.CallInfo('here')
toplevel_frame = inspect.currentframe()


def nested_frame(a, b, c=3, **kwargs):
    f = inspect.stack()[0].frame
    return _inspect_utils._get_scope_from_frame(f, 0)


def chain_nested(x=1):
    return nested_frame(x, 1)


def nested_builder():
    return _inspect_utils.CallInfo('here')


def double_nested_builder():
    def inner_builder():
        return _inspect_utils.CallInfo('here')
    return inner_builder()


class TestCallInfo:
    def test_toplevel(self):
        assert toplevel_callinfo.module.__name__ == __name__
        assert toplevel_callinfo.scope.scopelist == []
        assert toplevel_callinfo.function == '<module>'

    def test_nested(self):
        nested_callinfo = nested_builder()
        assert nested_callinfo.module.__name__ == __name__
        assert len(nested_callinfo.scope) == 1
        assert nested_callinfo.scope.scopelist[0][0] == 'nested_builder'
        assert nested_callinfo.function == 'nested_builder'

    def test_double_nested(self):
        with pytest.raises(AssertionError):
            double_nested_builder()

    def test_nextmodule(self):
        nextmodule_callinfo = inspect_utils.call_info_nextmodule()
        here_callinfo = inspect_utils.call_info_here()
        assert nextmodule_callinfo.scope == \
            'Scope[tests.unittests.test_inspect_utils.TestCallInfo::test_nextmodule]'
        assert here_callinfo.scope == \
            'Scope[tests.material.inspect_utils.call_info_here]'

    def test_pass_frameinfo(self):
        callinfo = _inspect_utils.CallInfo(inspect.stack()[0])
        assert callinfo.scope == \
            'Scope[tests.unittests.test_inspect_utils.TestCallInfo::test_pass_frameinfo]'


def parent_frame_a():
    return parent_frame_c()


def parent_frame_b():
    __SKIP_THIS_FRAME = True
    return parent_frame_c()


def parent_frame_c():
    return inspect.stack()[0].frame


class Test_ParentFrame:
    def test_simple_1(self):
        frame = _inspect_utils._parent_frame(parent_frame_c())
        assert frame.f_code.co_name == 'test_simple_1'

    def test_simple_2(self):
        frame = _inspect_utils._parent_frame(parent_frame_a())
        assert frame.f_code.co_name == 'parent_frame_a'

    def test_skip(self):
        frame = _inspect_utils._parent_frame(parent_frame_b())
        assert frame.f_code.co_name == 'test_skip'


class Test_GetScopeFromFrame:
    def test_toplevel(self):
        scope = _inspect_utils._get_scope_from_frame(toplevel_frame, 0)
        assert scope.is_global()
        assert scope == 'Scope[tests.unittests.test_inspect_utils]'

    def test_nested(self):
        e = 1
        scope = nested_frame(e, 2, u=123)
        assert scope.def_source == get_source(__file__)
        assigns = scope.scopelist[0][1].body[:4]
        unparsed = [_ast_utils.unparse(x).strip() for x in assigns]
        assert 'a = e' in unparsed
        assert 'b = 2' in unparsed
        assert 'c = 3' in unparsed
        assert "kwargs = {'u': 123}" in unparsed
        assert all(x.value._scope == 'Scope[tests.unittests.test_inspect_utils.Test_GetScopeFromFrame::test_nested]'
                   for x in assigns)

    def test_chain_nested(self):
        e = 1
        scope = chain_nested(e)
        assert scope == \
            'Scope[tests.unittests.test_inspect_utils.nested_frame]'
        chain_scope = scope.scopelist[0][1].body[0].value._scope
        assert chain_scope == \
            'Scope[tests.unittests.test_inspect_utils.chain_nested]'
        outer_scope = chain_scope.scopelist[0][1].body[0].value._scope
        assert outer_scope == \
            'Scope[tests.unittests.test_inspect_utils.Test_GetScopeFromFrame::test_chain_nested]'
        assign = outer_scope.scopelist[0][1].body[1]
        assert _ast_utils.unparse(assign).strip() == 'e = 1'
        assign = chain_scope.scopelist[0][1].body[0]
        assert _ast_utils.unparse(assign).strip() == 'x = e'
        assign = scope.scopelist[0][1].body[0]
        assert _ast_utils.unparse(assign).strip() == 'a = x'

    def test_scope_too_long_raises(self):
        def x():
            def y():
                def z():
                    f = inspect.stack()[0].frame
                    return _inspect_utils._get_scope_from_frame(f, 0)
                return z
            return y

        with pytest.raises(AssertionError):
            x()()()


class A:
    def __init__(self):
        self.frameinfo = _inspect_utils.non_init_caller_frameinfo(self)


class B(A):
    def __init__(self):
        super().__init__()


class C:
    def __init__(self):
        a = A()
        self.a = a
        self.frameinfo = inspect.stack()[0]


class TestNonInitCallerFrameinfo:
    def test_trivial(self):
        here = inspect.stack()[0]
        there = _inspect_utils.non_init_caller_frameinfo(self)
        assert here.filename == there.filename
        assert here.function == there.function

    def test_class_init(self):
        here = inspect.stack()[0]
        there = A().frameinfo
        assert here.filename == there.filename
        assert here.function == there.function

    def test_child_class_init(self):
        here = inspect.stack()[0]
        there = B().frameinfo
        assert here.filename == there.filename
        assert here.function == there.function

    def test_different_class_init(self):
        c = C()
        in_c = c.frameinfo
        a_caller = c.a.frameinfo
        assert in_c.filename == a_caller.filename
        assert in_c.function == a_caller.function

class TestTraceThis:
    def test_works(self):
        import sys
        if sys.gettrace() is not None and 'coverage' in str(sys.gettrace()):
            return  # this doesn't work with coverage -- disabling

        def tracefunc(frame, event, arg):
            if event == 'return':
                assert arg == 123
                assert 0, 'this works'

        def to_trace(x):
            _inspect_utils.trace_this(tracefunc)
            return x

        with pytest.raises(AssertionError) as exc_info:
            to_trace(123)

        exc_info.match('this works')


class Test_InstructionsUpToCall:
    def test_from_string(self):
        s = 'b = 1; a(); f = 123'
        ix = _inspect_utils._instructions_up_to_call(s)
        assert [i.opname for i in ix] == ['LOAD_CONST', 'STORE_NAME', 'LOAD_NAME', 'CALL_FUNCTION']

    def test_from_code(self):
        def f():
            return _inspect_utils._instructions_up_to_call(inspect.currentframe().f_back.f_code)

        a = 1
        b = 2
        ix = f()

        assert ix[-1].opname == 'CALL_FUNCTION'


class Test_InstructionsInName:
    def test_from_string(self):
        s = 'a.b.c.d'
        ix = _inspect_utils._instructions_in_name(s)
        assert [i.opname for i in ix] == ['LOAD_NAME', 'LOAD_ATTR', 'LOAD_ATTR', 'LOAD_ATTR']


class Test_InstructionsInGetitem:
    ...


class Test_InstructionsUpToOffset:
    def test_from_string(self):
        s = 'b = 1; a(); f = 123'
        ix = _inspect_utils._instructions_up_to_offset(s, 6)
        assert ix[-1].offset == 6
        ix = _inspect_utils._instructions_up_to_offset(s, 2)
        assert ix[-1].offset == 2


class Test_Module:
    def test_works(self):
        m = _inspect_utils._module(toplevel_frame)
        assert m == sys.modules[__name__]


class TestOuterCallerFrameinfo:
    def test_here(self):
        from tests.material import outer_caller
        m = outer_caller.here()
        assert m.function == 'test_here'

    def test_there(self):
        from tests.material import outer_caller_1
        m = outer_caller_1.there()
        assert m.function == 'there'


class TestCallerModule:
    def test_here(self):
        from tests.material import outer_caller
        assert outer_caller.caller_module().__name__ == __name__


class TestCallerFrame:
    def test_here(self):
        from tests.material import outer_caller
        assert outer_caller.caller_frame().f_code.co_filename == __file__


class TestGetArgumentAssignments:
    def test_one(self):
        assignments = inspect_utils.arg_assignments(1, b=2, c=123)
        assert assignments == {'a': '1', 'b': '2', 'c': '123'}
