import ast
import builtins
from collections import defaultdict
from textwrap import dedent

import pytest

from savethis import _dumper
from savethis._scope import Scope, ScopedName


SOURCE = dedent('''\
    aaa = 1

    def ooo():
        o = aaa  # global - should be renamed

    class CCC:
        o = aaa

        def __init__(self, aaa):  # local - shouldn't be renamed
            self.aaa = aaa  # local

        def aaa(self):  # local
            self.aaa = 123  # attribute - shoudn't be renamed

        def bbb(self):
            return aaa + self.aaa  # global - should be renamed

    def bbb(aaa):  # local
        aaa = 1
        def ccc(bbb):
            return 1 + aaa

    def ccc():
        def ddd():
            return aaa  # global
        return ddd

    def fff(aaa, bbb=aaa):  # default is global
        return x

    o = [aaa for aaa in bla]  # local
    ''')

TARGET = dedent('''\
    xxx = 1

    def ooo():
        o = xxx  # global - should be renamed

    class CCC:
        o = xxx

        def __init__(self, aaa):  # local - shouldn't be renamed
            self.aaa = aaa  # local

        def aaa(self):  # local
            self.aaa = 123  # attribute - shoudn't be renamed

        def bbb(self):
            return xxx + self.aaa  # global - should be renamed

    def bbb(aaa):  # local
        aaa = 1
        def ccc(bbb):
            return 1 + aaa

    def ccc():
        def ddd():
            return xxx  # global
        return ddd

    def fff(aaa, bbb=xxx):  # default is global
        return x

    o = [aaa for aaa in bla]  # local
    ''')


class Test_VarFinder:
    def test_find(self):
        src = dedent('''\
            a = 1
            b = c

            def f():
                c = 1
                i = j''')
        node = ast.parse(src)
        vf = _dumper._VarFinder()
        vars = vf.find(node)
        assert set(x.name for x in vars.globals) == {'c', 'j'}
        assert set(x.name for x in vars.locals) == {'a', 'b', 'f'}

    def test_find_in_list(self):
        src1 = dedent('''\
            a = 1
            b = c

            def f():
                c = 1
                i = j''')
        node1 = ast.parse(src1)
        src2 = dedent('''\
            d = e
            class F:
                ...''')
        node2 = ast.parse(src2)
        vf = _dumper._VarFinder()
        vars = vf.find([node1, node2])
        assert set(x.name for x in vars.globals) == {'c', 'j', 'e'}
        assert set(x.name for x in vars.locals) == {'a', 'b', 'f', 'd', 'F'}

    def test_find_in_function(self):
        src = dedent('''\
            def f(a, *args, **kwargs):
                c = 1
                b = a
                i = j''')
        node = ast.parse(src).body[0]
        vf = _dumper._VarFinder()
        vars = vf.find(node)
        assert set(x.name for x in vars.globals) == {'j'}
        assert set(x.name for x in vars.locals) == {'a', 'args', 'kwargs', 'i', 'c', 'b'}



class TestFinder:
    def test_find_function_def_explicit(self):
        res = _dumper.Finder(ast.FunctionDef).find(ast.parse(SOURCE))
        assert all(isinstance(x, ast.FunctionDef) for x in res)
        assert {x.name for x in res} == {'ooo', '__init__', 'aaa', 'bbb', 'ccc', 'fff', 'ddd'}

    def test_find_all(self):
        parsed = ast.parse(SOURCE)
        all_nodes = list(ast.walk(parsed))
        filtered = defaultdict(set)
        for x in all_nodes:
            filtered[type(x)].add(x)

        for type_, instances in filtered.items():
            res = _dumper.Finder(type_).find(parsed)
            assert set(res) == instances


class Test_JoinAttr:
    def test_attribute_chain(self):
        assert _dumper._join_attr(ast.parse('a.b.c.d.e.f.g').body[0].value) == \
            ['a', 'b', 'c', 'd', 'e', 'f', 'g']

    def test_single_name(self):
        assert _dumper._join_attr(ast.parse('a').body[0].value) == ['a']

    def test_raises_with_wrong_node_type(self):
        with pytest.raises(TypeError):
            _dumper._join_attr(ast.parse('f()').body[0].value)


class TestFindGlobals:
    def test_find_same_name(self):
        statement = 'a = run(a)'
        tree = ast.parse(statement)
        res = _dumper.find_globals(tree)
        assert res == {ScopedName('a', Scope.empty()), ScopedName('run', Scope.empty())}

    def test_find_in_assignment(self):
        statement = 'a = run'
        tree = ast.parse(statement)
        res = _dumper.find_globals(tree)
        assert res == {ScopedName('run', Scope.empty())}

    def test_dots(self):
        statement = (
            'def f(x):\n'
            '    o = x.y\n'
            '    u = y.x\n'
            '    return a.b.c(x)\n'
        )
        res = _dumper.find_globals(ast.parse(statement))
        assert res == {ScopedName('a.b.c', Scope.empty()), ScopedName('y.x', Scope.empty())}

    def test_attribute(self):
        statement = (
            'def f(x):\n'
            '    o = x.y\n'
            '    u = y.x\n'
            '    ff = (aa + bb).c\n'
            '    return a.b.c(x)\n'
        )
        res = _dumper.find_globals(ast.parse(statement))
        assert res == {ScopedName('a.b.c', Scope.empty()), ScopedName('y.x', Scope.empty()),
                       ScopedName('aa', Scope.empty()), ScopedName('bb', Scope.empty())}

    def test_complex_statement_1(self):
        statement = (
            '@transform\n'
            'def f(x):\n'
            '    (255 * (x * 0.5 + 0.5)).numpy().astype(numpy.uint8)\n'
        )
        res = _dumper.find_globals(ast.parse(statement))
        assert res == {ScopedName('numpy.uint8', Scope.empty()), ScopedName('transform', Scope.empty())}

    def test_nested_function(self):
        statement = dedent('''\
            def f():
                def g():
                    x = aaa
        ''')
        res = _dumper.find_globals(ast.parse(statement))
        assert res == {ScopedName('aaa', Scope.empty())}

    def test_nested_function_nonlocal(self):
        statement = dedent('''\
            def f():
                def g():
                    x = aaa
                aaa = 1
        ''')
        res = _dumper.find_globals(ast.parse(statement))
        assert res == set()
    
    def test_subscript_does_not_make_it_local(self):
        statement = dedent('''\
            x[1] = 2
        ''')
        res = _dumper.find_globals(ast.parse(statement))
        assert set(x.name for x in res) == {'x'}

    def test_attribute_does_not_make_it_local(self):
        statement = dedent('''\
            x.a = 2
        ''')
        res = _dumper.find_globals(ast.parse(statement))
        assert set(x.name for x in res) == {'x'}



class TestRename:

    def test_complex_example(self):
        renamed = _dumper.rename(SOURCE, from_='aaa', to='xxx')
        assert renamed == TARGET

    def test_assignment_1(self):
        source = 'aaa = aaa'
        target = 'xxx = xxx'
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target

    def test_assignment_2(self):
        source = 'aaa = bbb'
        target = 'xxx = bbb'
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target

    def test_assignment_3(self):
        source = 'bbb = aaa'
        target = 'bbb = xxx'
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target

    def test_function_body(self):
        source = dedent('''\
            def f():
                bbb = aaa
        ''')
        target = dedent('''\
            def f():
                bbb = xxx
        ''')
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target

    def test_function_name(self):
        source = dedent('''\
            def aaa():
                ...
        ''')
        target = dedent('''\
            def xxx():
                ...
        ''')
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target

    def test_function_name_no_locals(self):
        source = dedent('''\
            def aaa():
                ...
        ''')
        target = dedent('''\
            def aaa():
                ...
        ''')
        renamed = _dumper.rename(source, from_='aaa', to='xxx', rename_locals=False)
        assert renamed == target

    def test_nested_function_body(self):
        source = dedent('''\
            def f():
                def g():
                    bbb = aaa
        ''')
        target = dedent('''\
            def f():
                def g():
                    bbb = xxx
        ''')
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target

    def test_comprehension(self):
        source = 'bbb = [aaa for aaa in bla]'
        target = 'bbb = [aaa for aaa in bla]'
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target

    def test_class_name(self):
        source = dedent('''\
            class aaa():
                ...
        ''')
        target = dedent('''\
            class xxx():
                ...
        ''')
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target

    def test_class_name_no_locals(self):
        source = dedent('''\
            class aaa():
                ...
        ''')
        target = dedent('''\
            class aaa():
                ...
        ''')
        renamed = _dumper.rename(source, from_='aaa', to='xxx', rename_locals=False)
        assert renamed == target

    def test_class_body(self):
        source = dedent('''\
            class bbb:
                ooo = aaa
        ''')
        target = dedent('''\
            class bbb:
                ooo = xxx
        ''')
        renamed = _dumper.rename(source, from_='aaa', to='xxx')
        assert renamed == target


class TestAddScopeAndPos:
    def test_only_change_empty_scope(self):
        scope1 = _dumper.Scope.toplevel(_dumper)
        scope2 = _dumper.Scope.toplevel(ast)
        vars = [_dumper.ScopedName('x', scope=scope1)]
        name = _dumper.ScopedName('y', scope=scope2)
        _dumper.add_scope_and_pos(vars, name, ast.Name())
        assert [var.scope == scope1 for var in vars]

    def test_add_scope(self):
        scope2 = _dumper.Scope.toplevel(ast)
        vars = [_dumper.ScopedName('x', Scope.empty())]
        name = _dumper.ScopedName('y', scope=scope2)
        _dumper.add_scope_and_pos(vars, name, ast.Name())
        assert [var.scope == scope2 for var in vars]

    def test_add_pos(self):
        vars = [_dumper.ScopedName('x', Scope.empty())]
        name = _dumper.ScopedName('y', Scope.empty(), pos=(1, 1))
        _dumper.add_scope_and_pos(vars, name, ast.Name())
        assert [var.pos == (1, 1) for var in vars]


class Test_MethodFinder:
    def test_simple(self):
        source = dedent('''\
            class X:
                def a(self):
                    ...

                def b(self):
                    ...

                def c(self):
                    ...
        ''')
        res = _dumper._MethodFinder().find(ast.parse(source).body[0])
        assert set(res.keys()) == {'a', 'b', 'c'}

    def test_classmethod(self):
        source = dedent('''\
            class X:
                @classmethod
                def a(self):
                    ...

                @classmethod
                def b(cls):
                    ...

                @classmethod
                def c(cls):
                    ...
        ''')
        res = _dumper._MethodFinder().find(ast.parse(source).body[0])
        assert set(res.keys()) == {'a', 'b', 'c'}

    def test_staticmethod(self):
        source = dedent('''\
            class X:
                @staticmethod
                def a(self):
                    ...

                @staticmethod
                def b(cls):
                    ...

                @staticmethod
                def c(cls):
                    ...
        ''')
        res = _dumper._MethodFinder().find(ast.parse(source).body[0])
        assert set(res.keys()) == {'a', 'b', 'c'}

    def test_mixed(self):
        source = dedent('''\
            class X:
                def a(self):
                    ...

                @staticmethod
                def b(cls):
                    ...

                @classmethod
                def c(cls):
                    ...
        ''')
        res = _dumper._MethodFinder().find(ast.parse(source).body[0])
        assert set(res.keys()) == {'a', 'b', 'c'}

    def test_nested_function(self):
        source = dedent('''\
            class X:
                def a(self):
                    def aa():
                        ...

                @staticmethod
                def b(cls):
                    def bb():
                        ...

                @classmethod
                def c(cls):
                    def cc():
                        ...
        ''')
        res = _dumper._MethodFinder().find(ast.parse(source).body[0])
        assert set(res.keys()) == {'a', 'b', 'c'}

    def test_nested_class(self):
        source = dedent('''\
            class X:
                def a(self):
                    ...

                @staticmethod
                def b(cls):
                    ...

                @classmethod
                def c(cls):
                    ...

                class X:
                    def oh(self):
                        ...
        ''')
        res = _dumper._MethodFinder().find(ast.parse(source).body[0])
        assert set(res.keys()) == {'a', 'b', 'c'}


class Test_FilterBuiltins:
    def test_works(self):
        names = [_dumper.ScopedName(x, Scope.empty()) for x in builtins.__dict__.keys()]
        names.insert(0, _dumper.ScopedName('bla', Scope.empty()))
        names.insert(3, _dumper.ScopedName('ble', Scope.empty()))
        names.insert(12, _dumper.ScopedName('bli', Scope.empty()))
        names.insert(22, _dumper.ScopedName('blo', Scope.empty()))
        names.append(_dumper.ScopedName('blu', Scope.empty()))
        assert _dumper._filter_builtins(names) == {_dumper.ScopedName(x, Scope.empty())
                                                   for x in {'bla', 'ble', 'bli', 'blo', 'blu'}}


class Test_FindGlobalsInClassdef:
    def test_finds_in_function_def(self):
        source = dedent('''\
            class A:
                def a(self):
                    o = bla

                def b(self):
                    o = ble

                def c(self, bli):
                    o = bli
        ''')
        res = _dumper._find_globals_in_classdef(ast.parse(source).body[0])
        assert {x.name for x in res} == {'bla', 'ble'}

    def test_finds_in_body(self):
        source = dedent('''\
            class A:
                x = bla
                y = [f for f in ble]
                blu = bla
        ''')
        res = _dumper._find_globals_in_classdef(ast.parse(source).body[0])
        assert {x.name for x in res} == {'bla', 'ble'}

    def test_keeps_builtins(self):
        source = dedent('''\
            class A:
                def a(self):
                    o = int

                def b(self):
                    o = ble

                def c(self, bli):
                    o = bli
        ''')
        res = _dumper._find_globals_in_classdef(ast.parse(source).body[0], filter_builtins=False)
        assert {x.name for x in res} == {'int', 'ble'}

    def test_filters_builtins(self):
        source = dedent('''\
            class A:
                def a(self):
                    o = int

                def b(self):
                    o = ble

                def c(self, bli):
                    o = bli
        ''')
        res = _dumper._find_globals_in_classdef(ast.parse(source).body[0])
        assert {x.name for x in res} == {'ble'}

    def test_nested_class(self):
        source = dedent('''\
            class A:
                class B:
                    def a(self):
                        o = bla

                    def b(self):
                        o = ble

                    def c(self, bli):
                        o = bli
        ''')
        res = _dumper._find_globals_in_classdef(ast.parse(source).body[0], filter_builtins=False)
        assert {x.name for x in res} == {'bla', 'ble'}


class TestFindCodenode:
    def test_find_toplevel(self):
        scope = _dumper.Scope.toplevel(_dumper)
        node = _dumper.ScopedName('find_codenode', scope=scope)
        res = _dumper.find_codenode(node)
        assert res.source.startswith('def find_codenode')
        assert isinstance(res.ast_node, ast.FunctionDef)
        assert res.ast_node.name == 'find_codenode'
        assert res.name.name == 'find_codenode'
        assert res.name.scope == scope
        assert res.name.pos is not None

    def test_find_from_import(self):
        from tests.material import find_codenode_from_import
        scope = _dumper.Scope.toplevel(find_codenode_from_import)
        node = _dumper.ScopedName('find_codenode', scope=scope)
        res = _dumper.find_codenode(node)
        assert res.source == 'from savethis._dumper import find_codenode'
        assert isinstance(res.ast_node, ast.ImportFrom)
        assert res.name.name == 'find_codenode'
        assert res.name.scope == _dumper.Scope.empty()
        assert res.name.pos is not None

    def test_find_from_import_fulldump(self):
        from tests.material import find_codenode_from_import
        scope = _dumper.Scope.toplevel(find_codenode_from_import)
        node = _dumper.ScopedName('find_codenode', scope=scope)
        res = _dumper.find_codenode(node, full_dump_module_names='savethis._dumper')
        assert res.source.startswith('def find_codenode')
        assert isinstance(res.ast_node, ast.FunctionDef)
        assert res.ast_node.name == 'find_codenode'
        assert res.name.name == 'find_codenode'
        assert res.name.scope == _dumper.Scope.toplevel(_dumper)
        assert res.name.pos is not None

    def test_find_module_import(self):
        from tests.material import find_codenode_module_import
        scope = _dumper.Scope.toplevel(find_codenode_module_import)
        node = _dumper.ScopedName('_dumper.find_codenode', scope=scope)
        res = _dumper.find_codenode(node)
        assert res.source == 'from savethis import _dumper'
        assert isinstance(res.ast_node, ast.ImportFrom)
        assert res.name.name == '_dumper'
        assert res.name.scope == _dumper.Scope.empty()
        assert res.name.pos is not None


def parse(src):
    return ast.parse(src).body[0]


class TestNameFromAstNode:
    def test_function_def_works(self):
        assert 'a' == _dumper.name_from_ast_node(parse('def a():\n    ...'))

    def test_class_def_works(self):
        assert 'a' == _dumper.name_from_ast_node(parse('class a():\n    ...'))

    def test_import_works(self):
        assert 'a' == _dumper.name_from_ast_node(parse('import a'))

    def test_import_with_multiple_targets_fails(self):
        with pytest.raises(AssertionError):
            _dumper.name_from_ast_node(parse('import a, b'))

    def test_import_as_works(self):
        assert 'a' == _dumper.name_from_ast_node(parse('import b as a'))

    def test_import_from_works(self):
        assert 'a' == _dumper.name_from_ast_node(parse('from b import a'))

    def test_import_from_as_works(self):
        assert 'a' == _dumper.name_from_ast_node(parse('from b import c as a'))

    def test_assign_works(self):
        assert 'a' == _dumper.name_from_ast_node(parse('a = 1'))

    def test_annassign_works(self):
        assert 'a' == _dumper.name_from_ast_node(parse('a: int = 1'))

    def test_assign_with_multiple_targets_raises(self):
        with pytest.raises(AssertionError):
            _dumper.name_from_ast_node(parse('a = b = 1'))

    def test_assign_with_tuple_target_raises(self):
        with pytest.raises(AssertionError):
            _dumper.name_from_ast_node(parse('a, b = 1, 2'))
