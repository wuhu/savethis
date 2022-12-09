# pylint: disable=invalid-name
# TODO: change name?
# TODO: remove scope etc (seems like that belongs somewhere else)
"""Module for symbolically finding python entities in python source code given their name.

A thing in python can get its name in various ways:

 - it's defined as a function
 - it's defined as a class
 - it's assigned
 - it is imported
 - it's created in a with statement
 - it's created in a for loop

This module defines subclasses of the `_ThingFinder` class, which allow to identify these cases
in an AST tree of a source code.

Finding names in code then corresponds to building the AST tree of the code and using the
`_ThingFinder` subclasses to identify if and how the names were created.

The main function to use is :func:`find`, which will find a name in a module or the current ipython
history.

This module also defines the :class:`Scope`, which represents the "location" of a python-thing,
and the :class:`ScopedName`, which is the name of a thing, with its scope.
"""

import ast
from math import inf
import sys
from textwrap import dedent
from typing import List, Tuple, Optional

from . import _ast_utils, _source_utils


class _ThingFinder(ast.NodeVisitor):
    """Class for finding python "things" in a given source code given a variable name.

    :param source: The source in which the thing is searched.
    :param var_name: The name of the variable that's searched for.
    :param max_n: Stop searching after this number of statements from the bottom
        of the module.
    """

    def __init__(self, source: str, var_name: str, max_n: int = inf):
        self.source = source
        self.var_name = var_name
        self.statement_n = 0
        self.max_n = max_n
        self._result = None

    def found_something(self) -> bool:
        """*True* if something was found. """
        return self._result is not None

    def visit_Module(self, node):
        """Visit each statement in a module's body, from top to bottom and stop at "max_n". """
        for i, statement in enumerate(node.body[::-1]):
            if i > self.max_n:
                return
            self.visit(statement)
            if self.found_something():
                self.statement_n = i
                return

    def visit_With(self, node):
        """With is currently not supported - raises an error if the "thing" is defined in the
        head of a "with"-statement. """
        for item in node.items:
            if item.optional_vars is not None and item.optional_vars.id == self.var_name:
                raise NotImplementedError(f'"{self.var_name}" is defined in the head of a with'
                                          ' statement. This is currently not supported.')
        for subnode in node.body:
            self.visit(subnode)

    def visit_ClassDef(self, node):
        """Don't search class definitions (as that's another scope). """

    def visit_FunctionDef(self, node):
        """Don't search function definitions (as that's another scope). """

    def deparse(self) -> str:
        """Get the source snipped corresponding to the found node. """
        return _ast_utils.get_source_segment(self.source, self._result)

    def node(self) -> ast.AST:
        """Get the found node. """
        # TODO: correctly inherit (is not always _result)
        return self._result


class _FunctionDefFinder(_ThingFinder):
    """Class for finding a *function definition* of a specified name in an AST tree.

    Example:

    >>> source = '''
    ... import baz
    ...
    ... def foo(x):
    ...     ...
    ...
    ... def bar(y):
    ...     ...
    ...
    ... X = 100'''
    >>> finder = _FunctionDefFinder(source, 'foo')
    >>> node = ast.parse(source)
    >>> finder.visit(node)
    >>> finder.found_something()
    True
    >>> finder.deparse()
    'def foo(x):\\n    ...'
    >>> finder.node()  # doctest: +ELLIPSIS
    <...ast.FunctionDef object at 0x...>
    """

    def visit_FunctionDef(self, node):
        if node.name == self.var_name:
            self._result = node

    def deparse(self):
        res = ''
        res = _ast_utils.get_source_segment(self.source, self._result)
        # for py 3.8+, the decorators are not included, we need to add them
        if not res.lstrip().startswith('@'):
            for decorator in self._result.decorator_list[::-1]:
                res = f'@{_ast_utils.get_source_segment(self.source, decorator)}\n' + res
        return _fix_indent(res)


def _fix_indent(source):  # TODO a@lf1.io: kind of dubious - is there a better way?
    """Fix the indentation of functions that are wrongly indented.

    This can happen with :func:`_ast_utils.get_source_segment`.
    """
    lines = source.lstrip().split('\n')
    res = []
    for line in lines:
        if line.startswith('@'):
            res.append(line.lstrip())
            continue
        if line.lstrip().startswith('def ') or line.lstrip().startswith('class '):
            res.append(line.lstrip())
        break
    lines = lines[len(res):]
    rest_dedented = dedent('\n'.join(lines))
    res = res + ['    ' + line for line in rest_dedented.split('\n')]
    return '\n'.join(line.rstrip() for line in res)


class _ClassDefFinder(_ThingFinder):
    """Class for finding a *class definition* of a specified name in an AST tree.

    Example:

    >>> source = '''
    ... import baz
    ...
    ... class Foo:
    ...     ...
    ...
    ... def bar(y):
    ...     ...
    ...
    ... X = 100'''
    >>> finder = _ClassDefFinder(source, 'Foo')
    >>> node = ast.parse(source)
    >>> finder.visit(node)
    >>> finder.found_something()
    True
    >>> finder.deparse()
    'class Foo:\\n    ...'
    >>> finder.node()  # doctest: +ELLIPSIS
    <...ast.ClassDef object at 0x...>
    """

    def visit_ClassDef(self, node):
        if node.name == self.var_name:
            self._result = node

    def deparse(self):
        res = ''
        res = _ast_utils.get_source_segment(self.source, self._result)
        res = _fix_indent(res)
        # for py 3.8+, the decorators are not included, we need to add them
        if not res.lstrip().startswith('@'):
            for decorator in self._result.decorator_list[::-1]:
                res = f'@{_ast_utils.get_source_segment(self.source, decorator)}\n' + res
        return res


class _ImportFinder(_ThingFinder):
    """Class for finding a *module import* of a specified name in an AST tree.

    Works with normal imports ("import x") and aliased imports ("import x as y").

    Example:

    >>> source = '''
    ... import baz as boo
    ...
    ... class Foo:
    ...     ...
    ...
    ... def bar(y):
    ...     ...
    ...
    ... X = 100'''
    >>> finder = _ImportFinder(source, 'boo')
    >>> node = ast.parse(source)
    >>> finder.visit(node)
    >>> finder.found_something()
    True
    >>> finder.deparse()
    'import baz as boo'
    """

    def visit_Import(self, node):
        for name in node.names:
            if name.asname == self.var_name:
                self._result = name
                return
            if name.asname is None and name.name == self.var_name:
                self._result = name
                return

    def deparse(self):
        name = self._result
        res = f'import {name.name}'
        if name.asname is not None:
            res += f' as {name.asname}'
        return res

    def node(self):
        # TODO: cache deparse?
        node = ast.parse(self.deparse()).body[0]
        if node.names[0].asname is None:
            node._globalscope = True
        return node


class _ImportFromFinder(_ThingFinder):
    """Class for finding a *from import* of a specified name in an AST tree.

    Example:

    >>> source = '''
    ... from boo import baz as hoo, bup
    ...
    ... class Foo:
    ...     ...
    ...
    ... def bar(y):
    ...     ...
    ...
    ... X = 100'''
    >>> finder = _ImportFromFinder(source, 'hoo')
    >>> node = ast.parse(source)
    >>> finder.visit(node)
    >>> finder.found_something()
    True
    >>> finder.deparse()
    'from boo import baz as hoo'
    """

    def visit_ImportFrom(self, node):
        for name in node.names:
            if name.asname == self.var_name:
                self._result = (node.module, name)
                return
            if name.asname is None and name.name == self.var_name:
                self._result = (node.module, name)
                return

    def deparse(self):
        module, name = self._result
        res = f'from {module} import {name.name}'
        if name.asname is not None:
            res += f' as {name.asname}'
        return res

    def node(self):
        # TODO: cache deparse?
        node = ast.parse(self.deparse()).body[0]
        # the scope does not matter here
        if node.names[0].asname is None:
            node._globalscope = True
        return node


class _AssignFinder(_ThingFinder):
    """Class for finding a *variable assignment* of a specified name in an AST tree.

    Example:

    >>> source = '''
    ... import baz
    ...
    ... class Foo:
    ...     ...
    ...
    ... def bar(y):
    ...     ...
    ...
    ... X = 100'''
    >>> finder = _AssignFinder(source, 'X')
    >>> node = ast.parse(source)
    >>> finder.visit(node)
    >>> finder.found_something()
    True
    >>> finder.deparse()
    'X = 100'
    >>> finder.node()  # doctest: +ELLIPSIS
    <...ast.Assign object at 0x...>
    """

    def visit_Assign(self, node):
        for target in node.targets:
            if self._parse_target(target):
                self._result = node
                return

    def visit_AnnAssign(self, node):
        if self._parse_target(node.target):
            self._result = node
            return

    def _parse_target(self, target):
        if isinstance(target, ast.Name) and target.id == self.var_name:
            return True
        if isinstance(target, ast.Tuple):
            for sub_target in target.elts:
                if self._parse_target(sub_target):
                    return True
        return False

    def deparse(self):
        source = getattr(self._result, '_source', self.source)
        return _ast_utils.get_source_segment(source, self._result)


def statements_before(source, statements, pos):
    if pos is None:
        return statements
    line, col = pos
    for i, node in enumerate(statements):
        pos = _ast_utils.get_position(source, node)
        if pos.lineno < line or (pos.lineno == line and pos.col_offset < col):
            return statements[i:]
    return []


def find_in_scope(scoped_name: ScopedName):
    """Find the piece of code that assigned a value to the variable with name
    *scoped_name.name* in the scope *scoped_name.scope*.

    :param scoped_name: Name (with scope) of the variable to look for.
    :return: Tuple as ((source, node), scope, name), where
        * source: String representation of piece of code.
        * node: Ast node for the code.
        * scope: Scope of the code.
        * name: Name of variable (str).

    """
    scope = scoped_name.scope
    searched_name = scoped_name.copy()
    for _scopename, tree in scope.scopelist:
        try:
            res = find_scopedname_in_source(searched_name, source=searched_name.scope.def_source,
                                            tree=tree)
            source, node, name = res
            if getattr(node, '_globalscope', False):
                name.scope = Scope.empty()
            else:
                name.scope = scope
            return (source, node), name
        except NameNotFound:
            scope = scope.up()
            searched_name.pos = None
            searched_name.cell_no = None
            continue
    if scope.module is None:
        raise NameNotFound(format_scoped_name_not_found(scoped_name))
    source, node, name = find_scopedname(searched_name)
    if getattr(node, '_globalscope', False):
        scope = Scope.empty()
    else:
        scope = getattr(node, '_scope', scope.global_())
    name.scope = scope
    return (source, node), name


def replace_star_imports(tree: ast.Module):
    """Replace star imports in the tree with their written out forms.

    So that::

    from foo import *

    would become::

    from foo import bar, baz, boo
    """
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.names[0].name == '*':
                try:
                    names = sys.modules[node.module].__all__
                except AttributeError:
                    names = [x for x in sys.modules[node.module].__dict__ if not x.startswith('_')]
                node.names = [ast.alias(name=name, asname=None) for name in names]


def find_scopedname_in_source(scoped_name: ScopedName, source, tree=None) -> Tuple[str, ast.AST, str]:
    """Find the piece of code that assigned a value to the variable with name *var_name* in the
    source string *source*.

    :param scoped_name: ScopedName to look for.
    :param tree: AST.Module to look into for scoped_name.
    :param source: Source code to search.
    :returns: Tuple with source code segment, corresponding AST node and variable name.
    """
    if tree is None:
        tree = ast.parse(source)

    replace_star_imports(tree)
    finder_clss = _ThingFinder.__subclasses__()

    for statement in statements_before(source, tree.body[::-1], scoped_name.pos):
        for var_name in scoped_name.variants():
            for finder_cls in finder_clss:
                finder = finder_cls(source, var_name)
                finder.visit(statement)
                if finder.found_something():
                    node = finder.node()
                    pos = _ast_utils.get_position(source, node)
                    return (
                        finder.deparse(),
                        node,
                        ScopedName(var_name, scoped_name.scope, (pos.lineno, pos.col_offset))
                    )
    raise NameNotFound(
        format_scoped_name_not_found(scoped_name)
    )


def find_in_source(var_name: str, source: str, tree=None) -> Tuple[str, ast.AST, str]:
    """Find the piece of code that assigned a value to the variable with name *var_name* in the
    source string *source*.

    :param var_name: Name of the variable to look for.
    :param tree: AST.module.
    :param source: Source code to search.
    :returns: Tuple with (source code segment, corresponding AST node, variable name str).
    """
    scoped_name = ScopedName(var_name, None)
    return find_scopedname_in_source(scoped_name, source, tree)


def find_scopedname_in_module(scoped_name: ScopedName, module):
    source = _source_utils.get_module_source(module)
    return find_scopedname_in_source(scoped_name, source)


def find_in_module(var_name: str, module) -> Tuple[str, ast.AST, str]:
    """Find the piece of code that assigned a value to the variable with name *var_name* in the
    module *module*.

    :param var_name: Name of the variable to look for.
    :param module: Module to search.
    :returns: Tuple with source code segment and corresponding ast node.
    """
    scoped_name = ScopedName(var_name, None)
    return find_scopedname_in_module(scoped_name, module)


def _find_branch(tree, lineno, source):
    """Find the branch of the ast tree *tree* containing *lineno*. """

    if hasattr(tree, 'lineno'):
        position = _ast_utils.get_position(source, tree)
        start, end = position.lineno, position.end_lineno
        # we're outside
        if not start <= lineno <= end:
            return False
    else:
        # this is for the case of nodes that have no lineno, for these we need to go deeper
        start = end = '?'

    child_nodes = list(ast.iter_child_nodes(tree))
    if not child_nodes and start != '?':
        return [tree]

    for child_node in child_nodes:
        res = _find_branch(child_node, lineno, source)
        if res:
            return [tree] + res

    if start == '?':
        return False

    return [tree]


def find_scopedname_in_ipython(scoped_name: ScopedName) ->Tuple[str, ast.AST, str]:
    """Find ScopedName in ipython

    :param scoped_name: ScopedName to find.
    :returns: Tuple with source code segment and corresponding ast node.
    """
    source = node = name = None
    cells = list(enumerate(_source_utils._ipython_history()))
    if scoped_name.cell_no is None:
        start = len(cells) - 1
    else:
        start = scoped_name.cell_no
    for i, cell in cells[start::-1]:
        if i == start:
            name_to_find = scoped_name
        else:
            name_to_find = scoped_name.copy()
            name_to_find.pos = None
        try:
            source, node, name = find_scopedname_in_source(name_to_find, cell)
            name.cell_no = i
        except (NameNotFound, SyntaxError):
            continue
        break
    if source is None:
        raise NameNotFound(format_scoped_name_not_found(scoped_name))
    return source, node, name


def find_in_ipython(var_name: str) -> Tuple[str, ast.AST, str]:
    """Find the piece of code that assigned a value to the variable with name *var_name* in the
    ipython history.

    :param var_name: Name of the variable to look for.
    :returns: Tuple with source code segment and the corresponding ast node.
    """
    scoped_name = ScopedName(var_name, None)
    return find_scopedname_in_ipython(scoped_name)


def find_scopedname(scoped_name: ScopedName) -> Tuple[str, ast.AST, str]:
    """Find the piece of code that assigned a value to the variable with name *scoped_name* in the
    module *module*.

    If *module* is not specified, this uses `__main__`. In that case, the ipython history will
    be searched as well.

    :param scoped_name: Name of the variable to look for.
    :returns: Tuple with source code segment, corresponding ast node and variable name.
    """
    module = scoped_name.scope.module
    if module is None:
        module = sys.modules['__main__']
    try:
        return find_scopedname_in_module(scoped_name, module)
    except TypeError as exc:
        if module is not sys.modules['__main__']:
            raise NameNotFound(format_scoped_name_not_found(scoped_name)) from exc
        return find_scopedname_in_ipython(scoped_name)


def find(var_name: str, module=None) -> Tuple[str, ast.AST, str]:
    """Find the piece of code that assigned a value to the variable with name *var_name* in the
    module *module*.

    If *module* is not specified, this uses `__main__`. In that case, the ipython history will
    be searched as well.

    :param var_name: Name of the variable to look for.
    :param module: Module to search (defaults to __main__).
    :returns: Tuple with source code segment, corresponding ast node and variable name.
    """
    if module is None:
        module = sys.modules['__main__']
    try:
        return find_in_module(var_name, module)
    except TypeError as exc:
        if module is not sys.modules['__main__']:
            raise NameNotFound(f'"{var_name}" not found.') from exc
        return find_in_ipython(var_name)


class NameNotFound(Exception):
    """Exception indicating that a name could not be found. """


def format_scoped_name_not_found(scoped_name):
    """Produce a nice error message for the case a :class:`ScopedName` isn't found. """
    variants = scoped_name.variants()
    if len(variants) > 1:
        joined = ', '.join(f'"{v}"' for v in variants[:-1])
        variant_str = f'(or one of its variants: {joined})'
    else:
        variant_str = ''
    return (
        f'Could not find "{scoped_name.name}" in scope "{scoped_name.scope.dot_string()}".\n\n'
        f'Please make sure that "{scoped_name.name}" is defined {variant_str}.'
    )


def split_call(call_source):
    """Split the function of a call from its arguments.

    Example:

    >>> split_call('f(1, 2, 3)')
    ('f', '1, 2, 3')
    """
    node = ast.parse(call_source).body[0].value
    call = _ast_utils.get_source_segment(call_source, node.func)
    if not node.args and not node.keywords:
        return call, ''
    all_args = node.args + [x.value for x in node.keywords]
    last_arg_position = _ast_utils.get_position(call_source, all_args[-1])
    func_position = _ast_utils.get_position(call_source, node.func)
    args = _source_utils.cut(call_source,
                         node.func.lineno - 1,
                         last_arg_position.end_lineno - 1,
                         func_position.end_col_offset + 1,
                         last_arg_position.end_col_offset)
    return call, ', '.join(x.strip() for x in args.split(','))
