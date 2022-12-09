import inspect
import re

from typing import Union, Set

from . import _inspect_utils
from . import _finder, _dumper
from ._dumper import CodeNode, find_codenode, CodeGraph
from ._scope import Scope, ScopedName


def get_argument_assignments(*args, **kwargs):
    frame = _inspect_utils.caller_frame()
    signature = _inspect_utils.get_call_signature(frame)
    return _finder.Signature(*args, **kwargs).get_call_assignments(*signature)


def add_startnodes(evaluable_repr, graph, name: Union[str, None], scope: Scope) -> Set:
    """Build the start-:class:`CodeNode` objects - the node with the source needed to create
    *self* as *name* (in the scope where *self* was originally created).

    Returns a set of dependencies (scoped names the start-node depends on).
    """
    start_source = f'{name or "_pd_dummy"} = {evaluable_repr}'
    start = CodeNode.from_source(start_source, scope, name=name or "_pd_dummy")

    # if name is given, add the node to the CodeGraph, otherwise only use the dependencies
    if name is not None:
        scoped_name = ScopedName(name, scope)
        graph[scoped_name] = start
    else:
        scoped_name = None

    return list(start.globals_), scoped_name


def build_codegraph(var):
    evaluable_repr = get_argument_assignments(['var'])['var']
    call_info = _inspect_utils.CallInfo()
    scope = call_info.scope
    code_graph = CodeGraph()
    globals_, scoped_name = add_startnodes(evaluable_repr, code_graph, 'savethis', scope)
    return code_graph.build(globals_)


def dump(var):
    return build_codegraph(var).dumps()
