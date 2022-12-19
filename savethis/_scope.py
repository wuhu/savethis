import ast
from collections import defaultdict
from dataclasses import dataclass, field
import sys

from types import ModuleType
from typing import List, Optional, Tuple

from . import _ast_utils, _source_utils


@dataclass
class Signature:
    """A class representing a function signature. """
    argnames: list = field(default_factory=lambda: [])
    pos_only_argnames: list = field(default_factory=lambda: [])
    defaults: dict = field(default_factory=lambda: {})
    kwonly_defaults: dict = field(default_factory=lambda: {})
    vararg: Optional[str] = None
    kwarg: Optional[str] = None
    ignore_extra_kwargs: bool = False

    def remove_fist(self):
        '''Remove the fist positional argument. '''
        if self.argnames:
            return self.argnames.pop(0)
        return self.pos_only_argnames.pop(0)

    @property
    def all_argnames(self):
        """A list of all argument names (including pos_only). """
        return self.pos_only_argnames + self.argnames

    def get_call_assignments(self, pos_args, keyword_args, star_args=None, star_kwargs=None,
                             dump_kwargs=True, ignore_extra_kwargs=False):
        """Given a call signature, return the assignmentes to this function signature.

        :param pos_args: Positional args.
        :param keyword_args: Keyword args.
        :param star_args: Value of *args.
        :param star_kwargs: Value of **kwargs.
        :param dump_kwargs: If *True*, return kwargs as a dumped string, else as a dict.
        :param ignore_extra_kwargs: If *True*, ignore extra keyword arguments, else raise an
            exception.
        """
        res = {}
        for name, val in self.kwonly_defaults.items():
            try:
                res[name] = keyword_args[name]
            except KeyError:
                res[name] = val

        for name, val in zip(self.all_argnames, pos_args):
            res[name] = val

        if self.vararg is not None:
            res[self.vararg] = '[' + ', '.join(pos_args[len(self.all_argnames):]) + ']'

        kwargs = {}
        for name, val in keyword_args.items():
            if name in res:
                continue
            if name in self.argnames:
                res[name] = val
            else:
                kwargs[name] = val

        if kwargs and not set(kwargs) == {None}:
            if self.kwarg is None:
                if not self.ignore_extra_kwargs:
                    raise ValueError('Extra keyword args given, but no **kwarg present.')
            elif dump_kwargs:
                res[self.kwarg] = '{' + ', '.join(f"'{k}': {v}" for k, v in kwargs.items()) + '}'
            else:
                res[self.kwarg] = kwargs

        for name, val in self.defaults.items():
            if name not in res:
                if star_kwargs is not None:
                    res[name] = f"{star_kwargs}.get('{name}', {val})"
                else:
                    res[name] = val

        return res


def _parse_def_args(args, source):
    argnames = [x.arg for x in args.args]

    try:
        pos_only_argnames = [x.arg for x in args.posonlyargs]
    except AttributeError:
        pos_only_argnames = []

    defaults = {
        name: _ast_utils.get_source_segment(source, val)
        for name, val in zip(argnames[::-1], args.defaults[::-1])
    }

    kwonly_defaults = {
        _ast_utils.get_source_segment(source, name): _ast_utils.get_source_segment(source, val)
        for name, val in zip(args.kwonlyargs, args.kw_defaults)
        if val is not None
    }

    if args.vararg is not None:
        vararg = args.vararg.arg
    else:
        vararg = None

    if args.kwarg is not None:
        kwarg = args.kwarg.arg
    else:
        kwarg = None

    return Signature(argnames, pos_only_argnames, defaults, kwonly_defaults, vararg, kwarg)


def _get_call_signature(source: str):
    """Get the call signature of a string containing a call.

    :param source: String containing a call (e.g. "a(2, b, 'f', c=100)").
    :returns: A tuple with
        - a list of positional arguments
        - a list of keyword arguments
        - the value of *args, if present, else None
        - the value of *kwargs, if present, else None

    Example:

    >>> _get_call_signature("a(2, b, 'f', c=100, *[1, 2], **kwargs)")
    (['2', 'b', "'f'"], {'c': '100'}, '[1, 2]', 'kwargs')
    """
    call = ast.parse(source).body[0].value
    if not isinstance(call, ast.Call):
        return [], {}
    star_args = None
    args = []
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            star_args = _ast_utils.get_source_segment(source, arg.value)
            continue
        args.append(_ast_utils.get_source_segment(source, arg))
    kwargs = {
        kw.arg: _ast_utils.get_source_segment(source, kw.value) for kw in call.keywords
    }
    star_kwargs = kwargs.pop(None, None)
    return args, kwargs, star_args, star_kwargs


class Scope:
    """A scope.

    This determines the "location" of an object. A scope has a module and a list of functions.

    For example, if the following were defined in a module "examplemodule"::

        def f():
            x = 1  # <-- here

    the indicated location is in the scope *examplemodule.f*. The following::

        def f():
            def g():
                x = 1  # <-- here

    would have the scope *examplemodule.f.g*.

    Scope objects can be used to find names that are not defined globally in a module, but
    nested, for example within a function body.

    It contains the module, the source string and a "scopelist".
    """
    _counts = defaultdict(set)

    def __init__(self, module: ModuleType, def_source: str,
                 scopelist: List[Tuple[str, ast.AST]], id_=None):
        self.module = module
        self.def_source = def_source
        self.scopelist = scopelist
        self.id_ = id_
        self._counts[self.dot_string()].add(id_)

    @classmethod
    def toplevel(cls, module):
        """Create a top-level scope (i.e. module level, no nesting). """
        if isinstance(module, str):
            module = sys.modules[module]
        try:
            source = _source_utils.get_module_source(module)
        except TypeError:
            source = ''
        return cls(module, source, [])

    @classmethod
    def empty(cls):
        """Create the empty scope (a scope with no module and no nesting). """
        return cls(None, '', [])

    def __deepcopy__(self, memo):
        return Scope(self.module, self.def_source, self.scopelist, self.id_)

    @classmethod
    def from_source(cls, def_source, lineno, call_source, module=None, drop_n=0,
                    calling_scope=None, frame=None, locs=None):
        """Create a `Scope` object from source code.

        :param def_source: The source string containing the scope.
        :param lineno: The line number to get the scope from.
        :param call_source: The source of the call used for accessing the scope.
        :param module: The module.
        :param drop_n: Number of levels to drop from the scope.
        """
        tree = ast.parse(def_source)
        branch = _find_branch(tree, lineno, def_source)
        if not branch:
            branch = []
        function_defs = [x for x in branch if isinstance(x, ast.FunctionDef)]

        function_defs = []
        previous = None
        for x in branch:
            if isinstance(x, ast.FunctionDef):
                function_defs.append(x)
                if isinstance(previous, ast.ClassDef):
                    x.full_name = f'{previous.name}::{x.name}'
                    if not any([getattr(x, 'id', None) == 'staticmethod' for x in x.decorator_list]):
                        x.is_dynamic_method = True
                    else:
                        x.is_dynamic_method = False
                else:
                    x.is_dynamic_method = False
                    x.full_name = x.name
            previous = x

        if drop_n > 0:
            function_defs = function_defs[:-drop_n]

        if not function_defs:
            return cls.toplevel(module)

        # get call assignments for inner function
        # def f(a, b, c=3):
        #    ...
        # and
        # -> f(1, 2)
        # makes
        # a = 1
        # b = 2
        # c = 3
        # ...
        pos_args, keyword_args, star_args, star_kwargs = _get_call_signature(call_source)
        args = function_defs[-1].args

        signature = _parse_def_args(args, def_source)

        if function_defs[-1].is_dynamic_method:
            # remove 'self' args from dynamic methods
            self_var = signature.remove_fist()

        assignments = signature.get_call_assignments(pos_args, keyword_args, star_args, 
                                                     star_kwargs)

        call_assignments = []
        if function_defs[-1].is_dynamic_method:
            # TODO: make this work, see test_transforms.test_classtransform_created_in_init_with_self_can_be_dumped
            src = f'{self_var} = please_do_not_need_a_self_attribute'
            assignment = ast.parse(src).body[0]
            assignment._final_source = src
            _SetAttribute('_scope', calling_scope).visit(assignment.value)
            call_assignments.append(assignment)


        for k, v in assignments.items():
            src = f'{k} = {v}'
            assignment = ast.parse(src).body[0]
            assignment._source = src
            _SetAttribute('_scope', calling_scope).visit(assignment.value)
            call_assignments.append(assignment)

        scopelist = []
        for fdef in function_defs[::-1]:
            module_node = ast.Module()
            module_node.body = []
            module_node.body = fdef.body
            scopelist.append((fdef.full_name, module_node))

        # add call assignments to inner scope
        scopelist[0][1].body = call_assignments + scopelist[0][1].body

        id_ = str((frame.f_code.co_filename, locs))

        return cls(module, def_source, scopelist, id_)

    def from_level(self, i: int) -> 'Scope':
        """Return a new scope starting at level *i* of the scope hierarchy. """
        return type(self)(self.module, self.def_source, self.scopelist[i:])

    def up(self) -> 'Scope':
        """Return a new scope one level up in the scope hierarchy. """
        return type(self)(self.module, self.def_source, self.scopelist[1:])

    def global_(self) -> 'Scope':
        """Return the global scope surrounding *self*. """
        return type(self)(self.module, self.def_source, [])

    def is_global(self) -> bool:
        """*True* iff the scope is global. """
        return len(self.scopelist) == 0

    def is_empty(self) -> bool:
        return self.module is None

    @property
    def module_name(self) -> str:
        """The name of the scope's module. """
        if self.module is None:
            return ''
        return getattr(self.module, '__name__', '__main__')

    def unscoped(self, varname: str) -> str:
        """Convert a variable name in an "unscoped" version by adding strings representing
        the containing scope. """
        if not self.scopelist and self.module_name in ('', '__main__'):
            return varname
        return f'{"_".join(x[0] for x in [(self.module_name.replace(".", "_"), 0)] + self.scopelist)}{self._formatted_index()}_{varname}'

    def index(self):
        return sorted(self._counts[self.dot_string()]).index(self.id_)

    def _formatted_index(self):
        index = self.index()
        if index == 0:
            return ''
        return f'_{self.index()}'

    def dot_string(self):
        return ".".join(x[0] for x in [(self.module_name, 0)] + self.scopelist[::-1])

    def __repr__(self):
        return f'Scope[{self.dot_string()}{self._formatted_index()}]'

    def __len__(self):
        return len(self.scopelist)

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def d_name(self, name, pos=None, cell_no=None):
        return ScopedName(name, self, pos, cell_no)


class ScopedName:
    """A name with a scope and a counter. The "name" is the name of the item, the scope
    is its :class:`Scope` and the counter counts the items with the same name, in the same scope,
    from most recent on up.

    Example - the following::

        a = 1

        def f(x):
            a = 2

        a = a + 1

    contains four scoped names:

        - The "a" of `a = a + 1`, with `name = a`, module-level scope and `n = 0` (it is the most
          recent "a" in the module level scope).
        - The "a" in the function body, with `name = a`, function f scope and `n = 0` (it is the
          most recent "a" in "f" scope).
        - the function name "f", module level scope, `n = 0`
        - the "a" of `a = 1`, with `name = a`, module-level scope and `n = 1` (as it's the second
          most recent "a" in its scope).

    :param name: Name of this ScopedName.
    :param scope: Scope of this ScopedName.
    :param pos: (optional) Maximum position (tuple of line number and col number).
    :param cell_no: (optional) Maximum ipython cell number.
    """

    def __init__(self, name, scope=None, pos=None, cell_no=None):
        self.name = name
        if scope is None:
            scope = Scope.empty()
        self.scope = scope
        self.pos = pos
        self.cell_no = cell_no

    def __hash__(self):
        return hash((self.name, self.scope, self.pos))

    def __eq__(self, other):
        return (
            self.scope == other.scope
            and self.name == other.name
            and self.pos == other.pos
        )

    @property
    def toplevel_name(self):
        return self.name.split('.', 1)[0]

    def variants(self):
        """Returns list of splits for input_name.
        Example:

        >>> ScopedName('a.b.c', '__main__').variants()
        ['a', 'a.b', 'a.b.c']
        """
        splits = self.name.split('.')
        out = []
        for ind, split in enumerate(splits):
            out.append('.'.join(splits[:ind] + [split]))
        return out

    def update_scope(self, new_scope):
        self.scope = new_scope
        return self

    def copy(self):
        return ScopedName(self.name, self.scope, self.pos, self.cell_no)

    def __repr__(self):
        return (
            f"ScopedName(name='{self.name}', scope={self.scope}, pos={self.pos}, "
            f"cell_no={self.cell_no})"
        )


class _SetAttribute(ast.NodeVisitor):  # TODO: use of this seems dubious
    """Class for setting an attribute on all nodes in an ast tree.

    This is being used in :meth:`Scope.from_source` to tag nodes with the scope they were found in.

    Example:

    >>> tree = ast.parse('a = f(0)')
    >>> _SetAttribute('myattribute', True).visit(tree)
    >>> tree.body[0].targets[0].myattribute
    True
    >>> tree.body[0].value.myattribute
    True
    """

    def __init__(self, attr, value):
        self.attr = attr
        self.value = value

    def generic_visit(self, node):
        setattr(node, self.attr, self.value)
        super().generic_visit(node)


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
