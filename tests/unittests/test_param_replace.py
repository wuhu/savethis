from textwrap import dedent
import pytest

from savethis import _param_replace
from savethis import _scope
from savethis._ast_utils import Position

from tests.material import param_replace_variables


class TestParam:
    def test_input_is_output(self):
        assert 1 == _param_replace.param('a', 1)


class TestParams:
    def test_output_is_di_param_replace(self):
        assert {'a': 1, 'b': 2, 'c': 3} == _param_replace.params('a', a=1, b=2, c=3)


class TestApplyParams:
    def test_simple(self):
        s = dedent('''
            a = param('a', "1"); c = param('c', 1, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        replaced = dedent('''
            a = param('a', '3'); c = param('c', 100, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        out = _param_replace.apply_params(s, {'a': "'3'", 'c': "100"}, _scope.Scope.empty())
        assert replaced == out

    def test_with_variable_dependency(self):
        s = dedent('''
            a = param('a', "1"); c = param('c', 1, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        replaced = dedent('''\
            a = 123
            PARAM_a = a
            a = param('a', PARAM_a); c = param('c', 100, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        scope = _scope.Scope.toplevel(param_replace_variables)
        out = _param_replace.apply_params(s, {'a': "a", 'c': "100"}, scope)
        assert replaced == out

    def test_with_variable_dependency_in_params(self):
        s = dedent('''
            a = params('a', x="1", y="2"); c = params('c', z=3)
            def x():
                b = params('bb', x=123)
        ''')
        replaced = dedent('''\
            b = 1000
            PARAM_a_x = b
            a = params('a', x=PARAM_a_x, y='4'); c = params('c', z=100)
            def x():
                b = params('bb', x=123)
        ''')
        scope = _scope.Scope.toplevel(param_replace_variables)
        out = _param_replace.apply_params(s, {'a': "{'x': b, 'y': '4'}", 'c': "{'z': 100}"},
                                          scope)
        assert replaced == out

    def test_use_default(self):
        s = dedent('''
            a = param('a', "1"); c = param('c', 1, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        replaced = dedent('''
            a = param('a', "1"); c = param('c', 100, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        out = _param_replace.apply_params(s, {'c': "100"}, _scope.Scope.empty())
        assert replaced == out

    def test_with_params(self):
        s = dedent('''
            a = params('a', x="1", y="2"); c = params('c', z=3)
            def x():
                b = params('bb', x=123)
        ''')
        replaced = dedent('''
            a = params('a', x='3', y='4'); c = params('c', z=100)
            def x():
                b = params('bb', x=123)
        ''')
        out = _param_replace.apply_params(s, {'a': "{'x': '3', 'y': '4'}", 'c': "{'z': 100}"},
                                          _scope.Scope.empty())
        assert out == replaced

    def test_missing_mandatory_value_in_params_raises(self):
        s = dedent('''
            a = params('a', x="1", y="2", use_defaults=False); c = params('c', z=3)
            def x():
                b = params('bb', x=123)
        ''')
        with pytest.raises(ValueError):
            out = _param_replace.apply_params(s, {'a': "{'x': '3'}", 'c': "{'z': 100}"},
                                              _scope.Scope.empty())

    def test_missing_mandatory_value_in_param_raises(self):
        s = dedent('''
            a = param('a', "1"); c = param('c', 1, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        with pytest.raises(ValueError):
            _param_replace.apply_params(s, {}, _scope.Scope.empty())

    def test_extra_parameter_raises(self):
        s = dedent('''
            a = param('a', "1"); c = param('c', 1, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        with pytest.raises(ValueError):
            _param_replace.apply_params(s, {'z': 123}, _scope.Scope.empty())


class TestExtractParamS:
    def test_multiple(self):
        s = dedent('''
            a = param('a', "1"); c = param('c', 1, 'hello', False)
            def x():
                b = param('bb', x)
        ''')
        p = _param_replace.extract_param_s(s)
        assert p['a'] == {
            'name': "'a'",
            'val': '"1"',
            'description': 'None',
            'use_default': 'True',
            'position': Position(lineno=2, end_lineno=2, col_offset=15, end_col_offset=18)
        }
        assert p['c'] == {
            'name': "'c'",
            'val': '1',
            'description': "'hello'",
            'use_default': 'False',
            'position': Position(lineno=2, end_lineno=2, col_offset=36, end_col_offset=37)
        }
        assert p['bb'] == {
            'name': "'bb'",
            'val': 'x',
            'description': 'None',
            'use_default': 'True',
            'position': Position(lineno=4, end_lineno=4, col_offset=20, end_col_offset=21)
        }

    def test_defaults_are_filled_in(self):
        s = 'param("a", 1)'
        p = _param_replace.extract_param_s(s)
        assert p['a'] == {
            'name': '"a"',
            'val': '1',
            'description': 'None',
            'use_default': 'True',
            'position': Position(lineno=1, end_lineno=1, col_offset=11, end_col_offset=12)
        }

    def test_defaults_can_be_overridden(self):
        s = 'param("a", 1, "bla", False)'
        p = _param_replace.extract_param_s(s)
        assert p['a'] == {
            'name': '"a"',
            'val': '1',
            'description': '"bla"',
            'use_default': 'False',
            'position': Position(lineno=1, end_lineno=1, col_offset=11, end_col_offset=12)
        }

    def test_defaults_can_be_overridden_via_keywords(self):
        s = 'param(use_default=False, description="bla", name="a", val=1)'
        p = _param_replace.extract_param_s(s)
        assert p['a'] == {
            'name': '"a"',
            'val': '1',
            'description': '"bla"',
            'use_default': 'False',
            'position': Position(lineno=1, end_lineno=1, col_offset=58, end_col_offset=59)
        }

    def test_corre_param_replace_keys(self):
        s = 'param("a", 1)'
        p = _param_replace.extract_param_s(s)
        assert set(p.keys()) == {'a'}
        assert set(p['a'].keys()) == {'name', 'val', 'description', 'use_default', 'position'}

    def test_complex_values_work(self):
        s = 'param("a", np.random.rand(100 ** 10))'
        p = _param_replace.extract_param_s(s)
        assert p['a']['val'] == 'np.random.rand(100 ** 10)'

    def test_attribute_works(self):
        s = 'savethis.param("a", 1)'
        p = _param_replace.extract_param_s(s)
        assert p['a'] == {
            'name': '"a"',
            'val': '1',
            'description': 'None',
            'use_default': 'True',
            'position': Position(lineno=1, end_lineno=1, col_offset=20, end_col_offset=21)
        }

    def test_finds_nested(self):
        s = dedent('''
            class X:
                def f(self):
                    def o():
                        return [x for x in param('x', [1, 2, 3])]
        ''')
        p = _param_replace.extract_param_s(s)
        assert 'x' in p


class TestExtractParamsS:
    def test_defaults_are_filled_in(self):
        s = 'params("a", x=1)'
        p = _param_replace.extract_params_s(s)
        assert p['a'] == {
            'name': '"a"',
            'kwargs': {'x': '1'},
            'use_defaults': 'True',
            'allow_free': 'False',
            'positions': {'x': Position(lineno=1, end_lineno=1, col_offset=14, end_col_offset=15)},
            'end_position': Position(lineno=1, end_lineno=1, col_offset=15, end_col_offset=15)
        }

    def test_without_kwargs(self):
        s = 'params("a", allow_free=True)'
        p = _param_replace.extract_params_s(s)
        assert p['a'] == {
            'name': '"a"',
            'kwargs': {},
            'use_defaults': 'True',
            'allow_free': 'True',
            'positions': {},
            'end_position': Position(lineno=1, end_lineno=1, col_offset=27, end_col_offset=27)
        }

    def test_without_kwargs_and_without_allow_free_raises(self):
        s = 'params("a", allow_free=False)'
        with pytest.raises(ValueError):
            _param_replace.extract_params_s(s)

    def test_defaults_can_be_overridden(self):
        s = 'params("a", x=1, use_defaults=False, allow_free=True)'
        p = _param_replace.extract_params_s(s)
        assert p['a'] == {
            'name': '"a"',
            'kwargs': {'x': '1'},
            'use_defaults': 'False',
            'allow_free': 'True',
            'positions': {'x': Position(lineno=1, end_lineno=1, col_offset=14, end_col_offset=15)},
            'end_position': Position(lineno=1, end_lineno=1, col_offset=15, end_col_offset=15)
        }

    def test_keywords_can_be_used_for_everything(self):
        s = 'params(use_defaults=False, name="a", x=1, allow_free=True)'
        p = _param_replace.extract_params_s(s)
        assert p['a'] == {
            'name': '"a"',
            'kwargs': {'x': '1'},
            'use_defaults': 'False',
            'allow_free': 'True',
            'positions': {'x': Position(lineno=1, end_lineno=1, col_offset=39, end_col_offset=40)},
            'end_position': Position(lineno=1, end_lineno=1, col_offset=40, end_col_offset=40)
        }

    def test_corre_param_replace_keys(self):
        s = 'params("a", x=1)'
        p = _param_replace.extract_params_s(s)
        assert set(p.keys()) == {'a'}
        assert set(p['a'].keys()) == {'name', 'kwargs', 'allow_free', 'use_defaults', 'positions',
                                      'end_position'}

    def test_complex_values_work(self):
        s = 'params("a", x=np.random.rand(100 ** 10))'
        p = _param_replace.extract_params_s(s)
        assert p['a']['kwargs']['x'] == 'np.random.rand(100 ** 10)'

    def test_attribute_works(self):
        s = 'savethis.params("a", x=1)'
        p = _param_replace.extract_params_s(s)
        assert 'a' in p

    def test_finds_nested(self):
        s = dedent('''
            class X:
                def f(self):
                    def o():
                        return [x for x in params('x', o=[1, 2, 3])['o']]
        ''')
        p = _param_replace.extract_params_s(s)
        assert 'x' in p


class TestChangeParam:
    def test_simple(self):
        s = 'param("x", 1)'
        assert _param_replace.change_param(s, 'x', '100') == 'param("x", 100)'

    def test_attribute_works(self):
        s = 'savethis.param("x", 1)'
        assert _param_replace.change_param(s, 'x', '100') == 'savethis.param("x", 100)'

    def test_other_arguments_stay(self):
        s = 'param("x", 1, "this is a parameter", use_default=True)'
        assert _param_replace.change_param(s, 'x', '100') == 'param("x", 100, "this is a parameter", use_default=True)'

    def test_weird_formatting_works(self):
        s = dedent('''
            param("x", 1,
                        "this is a parameter",
                    use_default=True

                )
        ''')
        target = dedent('''
            param("x", 100,
                        "this is a parameter",
                    use_default=True

                )
        ''')
        assert _param_replace.change_param(s, 'x', '100') == target

    def test_nested_works(self):
        s = dedent('''
            def f():
                class X:
                    def __init__(self, y):
                        o = param("x", 1, "this is a parameter", use_default=True)
        ''')
        target = dedent('''
            def f():
                class X:
                    def __init__(self, y):
                        o = param("x", 100, "this is a parameter", use_default=True)
        ''')
        assert _param_replace.change_param(s, 'x', '100') == target


class TestChangeParams:
    def test_simple(self):
        s = 'params("x", x=1)'
        assert _param_replace.change_params(s, 'x', x='100') == 'params("x", x=100)'

    def test_attribute_works(self):
        s = 'savethis.params("x", x=1)'
        assert _param_replace.change_params(s, 'x', x='100') == 'savethis.params("x", x=100)'

    def test_allow_free_works(self):
        s = 'savethis.params("x", x=1, allow_free=True)'
        assert _param_replace.change_params(s, 'x', x='100', y='1000') == 'savethis.params("x", x=100, y=1000, allow_free=True)'

    def test_multiple(self):
        s = 'savethis.params("x", x=1, y=2, z=3)'
        assert _param_replace.change_params(s, 'x', x='100', z='1000') == 'savethis.params("x", x=100, y=2, z=1000)'

    def test_other_arguments_stay(self):
        s = 'params("x", x=1, use_defaults=True, allow_free=False)'
        assert _param_replace.change_params(s, 'x', x='100') == 'params("x", x=100, use_defaults=True, allow_free=False)'
    def test_providing_extra_args_without_allow_free_raises(self):
        s = 'params("x", x=1, allow_free=False)'
        with pytest.raises(ValueError):
            _param_replace.change_params(s, 'x', x='100', y=123)

    def test_weird_formatting_works(self):
        s = dedent('''
            params("x", x=1,
                    use_default=True

                )
        ''')
        target = dedent('''
            params("x", x=100,
                    use_default=True

                )
        ''')
        assert _param_replace.change_params(s, 'x', x='100') == target

    def test_nested_works(self):
        s = dedent('''
            def f():
                class X:
                    def __init__(self, y):
                        o = params("x", x=1, use_default=True)
        ''')
        target = dedent('''
            def f():
                class X:
                    def __init__(self, y):
                        o = params("x", x=100, use_default=True)
        ''')
        assert _param_replace.change_params(s, 'x', x='100') == target
