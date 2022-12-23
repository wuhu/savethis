import ast
import pytest
from textwrap import dedent

from savethis import _scope, _source_utils, _ast_utils


@pytest.fixture
def simple_nested_scope():
    src = dedent('''\
        # yea
        x = 1

        def f(z):
            a = 2
            def g(y):
                return 1
            return g
        ''')

    return _scope.Scope.from_source(src, 5, 'f(1)', module='__main__')


class TestSignature:
    def test_remove_first_posonly(self):
        s = _scope.Signature(argnames=['a', 'b', 'c'], pos_only_argnames=['d', 'e'])
        assert s.remove_fist() == 'd'
        assert s.pos_only_argnames == ['e']

    def test_remove_first(self):
        s = _scope.Signature(argnames=['a', 'b', 'c'])
        assert s.remove_fist() == 'a'
        assert s.argnames == ['b', 'c']

    def test_all_argnames(self):
        s = _scope.Signature(argnames=['a', 'b', 'c', 'z'], pos_only_argnames=['d', 'e'], defaults={'z': 1}, kwonly_defaults={'y': 100})
        assert s.all_argnames == ['d', 'e', 'a', 'b', 'c', 'z']

    def test_get_call_assignments_all_at_once(self):
        s = _scope.Signature(argnames=['aa', 'ab', 'da', 'db', 'dc'], pos_only_argnames=['pa', 'pb'], 
                             defaults={'da': 1, 'db': 2, 'dc': 3}, kwonly_defaults={'kd': 3, 'ke': 5}, vararg='args', kwarg='kwarg')
        r = s.get_call_assignments([1, 2, 3, 4, 5], {'kd': 30, 'db': 20, 'he': 123})
        assert {
            'aa': 3,
            'ab': 4,
            'pa': 1,
            'pb': 2,
            'da': 5,
            'db': 20,
            'dc': 3,
            'kd': 30,
            'ke': 5,
            'kwarg': "{'he': 123}",
            'args': '[]'
            } == r

    def test_get_call_assignments_positional(self):
        s = _scope.Signature(argnames=['a', 'b'])
        r = s.get_call_assignments([1, 2], {})
        assert {'a': 1, 'b': 2} == r

    def test_get_call_assignments_positional_with_starargs(self):
        s = _scope.Signature(argnames=['a', 'b', 'c', 'd'])
        r = s.get_call_assignments([1, 2], {}, star_args=[1, 2])
        assert {'a': 1, 'b': 2, 'c': 1, 'd': 2} == r

    def test_get_call_assignments_positional_via_keyword(self):
        s = _scope.Signature(argnames=['a', 'b'])
        r = s.get_call_assignments([1], {'b': 2})
        assert {'a': 1, 'b': 2} == r

    def test_get_call_assignments_pos_only(self):
        s = _scope.Signature(pos_only_argnames=['a', 'b'])
        r = s.get_call_assignments([1, 2], {})
        assert {'a': 1, 'b': 2} == r

    def test_get_call_assignments_pos_only_via_keyword_raises(self):
        s = _scope.Signature(pos_only_argnames=['a', 'b'])
        with pytest.raises(ValueError):
            s.get_call_assignments([1], {'b': 2})

    def test_get_call_assignments_keywords(self):
        s = _scope.Signature(argnames=['a', 'b'], defaults={'a': 100, 'b': 2, 'c': 3})
        r = s.get_call_assignments([1], {'b': 1})
        assert {'a': 1, 'b': 1, 'c': 3} == r

    def test_get_call_assignments_keywords_with_star_kwargs(self):
        s = _scope.Signature(argnames=['a', 'b', 'c'], defaults={'a': 100, 'b': 2, 'c': 3})
        r = s.get_call_assignments([1], {'b': 1}, star_kwargs={'c': 30})
        assert {'a': 1, 'b': 1, 'c': "{'c': 30}.get('c', 3)"} == r

    def test_get_call_assignments_extra_keywords_raises(self):
        s = _scope.Signature(argnames=['a', 'b', 'c'], defaults={'a': 100, 'b': 2, 'c': 3})
        with pytest.raises(ValueError):
            s.get_call_assignments([1], {'b': 1, 'x': 10})

    def test_get_call_assignments_keyword_only(self):
        s = _scope.Signature(kwonly_defaults={'a': 100, 'b': 2})
        r = s.get_call_assignments([], {'a': 1})
        assert {'a': 1, 'b': 2} == r

    def test_get_call_assignments_keyword_only_via_pos_raises(self):
        s = _scope.Signature(kwonly_defaults={'a': 100, 'b': 2})
        with pytest.raises(ValueError):
            s.get_call_assignments([1], {'b': 2})

    def test_get_call_assignments_kwargs(self):
        s = _scope.Signature(argnames=['a'], kwarg='kwarg', defaults={'a': 1})
        r = s.get_call_assignments([], {'a': 1, 'b': 2})
        assert {'a': 1, 'kwarg': "{'b': 2}"} == r

    def test_get_call_assignments_kwargs_no_dump(self):
        s = _scope.Signature(kwarg='kwarg')
        r = s.get_call_assignments([], {'a': 1}, dump_kwargs=False)
        assert {'kwarg': {'a': 1}} == r

    def test_get_call_assignments_args(self):
        s = _scope.Signature(argnames=['a'], vararg='args')
        r = s.get_call_assignments([1, 2, 3], {})
        assert {'a': 1, 'args': "[2, 3]"} == r


class Test_ParseDefArgs:
    def test_it_works(self):
        src = dedent('''\
            def f(a, b, /, c, d=1, *, e=2):
               ...''')
        args = ast.parse(src).body[0].args
        r = _scope._parse_def_args(args, src)

        assert r.pos_only_argnames == ['a', 'b']
        assert r.argnames == ['c', 'd']
        assert r.defaults == {'d': '1'}
        assert r.kwonly_defaults == {'e': '2'}

    def test_starargs(self):
        src = dedent('''\
            def f(*argsy, **kwargsy):
               ...''')
        args = ast.parse(src).body[0].args
        r = _scope._parse_def_args(args, src)

        assert r.vararg == 'argsy'
        assert r.kwarg == 'kwargsy'


class TestScope:
    def test_toplevel(self):
        scope = _scope.Scope.toplevel(ast)
        assert scope.module == ast
        assert scope.def_source == _source_utils.get_module_source(ast)
        assert scope.scopelist == []
        assert scope.id_ == None
        assert not scope.is_empty()

    def test_toplevel_from_str(self):
        scope = _scope.Scope.toplevel('ast')
        assert scope.module == ast
        assert scope.def_source == _source_utils.get_module_source(ast)
        assert scope.scopelist == []
        assert scope.id_ == None
        assert not scope.is_empty()

    def test_empty(self):
        scope = _scope.Scope.empty()
        assert scope.is_empty()

    def test_from_source(self):
        src = dedent('''\
            # yea
            x = 1

            def f(z):
                a = 2
                def g(y):
                    return 1
                return g
            ''')

        scope = _scope.Scope.from_source(src, 5, 'f(1)', module='__main__')
        assert scope == 'Scope[__main__.f]'
        assert scope.scopelist[0][0] == 'f'
        target_src = dedent('''\
            z = 1
            a = 2

            def g(y):
                return 1
            return g
        ''')
        assert _ast_utils.unparse(scope.scopelist[0][1]).strip('\n') == target_src.strip('\n')

    def test_from_source_toplevel(self):
        src = dedent('''\
            # yea
            x = 1

            def f(z):
                a = 2
                def g(y):
                    return 1
                return g
            ''')

        scope = _scope.Scope.from_source(src, 1, '', module='__main__')
        assert scope == 'Scope[__main__]'
        assert scope.scopelist == []

    def test_from_source_method(self):
        src = dedent('''\
            # yea
            x = 1

            class X:
                def f(self, z):
                    a = 2
                    def g(y):
                        return 1
                    return g
            ''')

        scope = _scope.Scope.from_source(src, 5, 'x.f(1)', module='__main__')
        assert scope == 'Scope[__main__.X::f]'
        assert scope.scopelist[0][0] == 'X::f'
        target_src = dedent('''\
            self = please_do_not_need_a_self_attribute
            z = 1
            a = 2

            def g(y):
                return 1
            return g
        ''')
        assert _ast_utils.unparse(scope.scopelist[0][1]).strip('\n') == target_src.strip('\n')

    def test_from_source_static_method(self):
        src = dedent('''\
            # yea
            x = 1

            class X:
                @staticmethod
                def f(z):
                    a = 2
                    def g(y):
                        return 1
                    return g
            ''')

        scope = _scope.Scope.from_source(src, 6, 'X.f(1)', module='__main__')
        assert scope == 'Scope[__main__.X::f]'
        assert scope.scopelist[0][0] == 'X::f'
        target_src = dedent('''\
            z = 1
            a = 2

            def g(y):
                return 1
            return g
        ''')
        assert _ast_utils.unparse(scope.scopelist[0][1]).strip('\n') == target_src.strip('\n')

    def test_up(self, simple_nested_scope):
        assert simple_nested_scope == 'Scope[__main__.f]'
        assert simple_nested_scope.up() == 'Scope[__main__]'

    def test_is_global(self, simple_nested_scope):
        assert simple_nested_scope.up().is_global()

    def test_unscoped(self, simple_nested_scope):
        assert simple_nested_scope.unscoped('bip') == '__main___f_bip'
        assert simple_nested_scope.up().unscoped('bip') == 'bip'

    def test_len(self, simple_nested_scope):
        assert len(simple_nested_scope) == 1
        assert len(simple_nested_scope.up()) == 0

    def test_hash(self, simple_nested_scope):
        assert hash(simple_nested_scope) == hash(str(simple_nested_scope))

    def test_d_name(self, simple_nested_scope):
        assert simple_nested_scope.d_name('x', pos=(1, 1), cell_no=2) == \
            _scope.ScopedName(name='x', scope=simple_nested_scope, pos=(1, 1), cell_no=2)


class TestScopedName:
    def test_copy(self):
        a = _scope.ScopedName('a', _scope.Scope.toplevel('__main__'), (1, 1), 1)
        assert a.copy() is not a
        assert a.copy() == a

    def test_toplevel_name(self):
        a = _scope.ScopedName('a.b.c', _scope.Scope.toplevel('__main__'), (1, 1), 1)
        assert a.toplevel_name == 'a'

    def test_repr(self):
        a = _scope.ScopedName('a.b.c', _scope.Scope.toplevel('__main__'), (1, 1), 1)
        assert repr(a) == 'ScopedName(name=\'a.b.c\', scope=Scope[__main__], pos=(1, 1), cell_no=1)'

    def test_up(self, simple_nested_scope):
        a = _scope.ScopedName('a.b.c', simple_nested_scope, (1, 1), 1)
        a.up()
        assert a.scope == simple_nested_scope.up()
        assert a.pos is None
        assert a.cell_no is None

    def test_hash_works(self):
        a = _scope.ScopedName('a.b.c', simple_nested_scope, (1, 1), 1)
        hash(a)
