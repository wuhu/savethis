import ast
import json
import pathlib
import pickle
import sys

import torch

from ._serializer import Serializer, SimpleSerializer, NullSerializer
from . import _dumper, _scope


SCOPE = _scope.Scope.toplevel(sys.modules[__name__])


def save_json(val, path):
    """Saver for json. """
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(val, f)


def load_json(path):
    """Loader for json. """
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def json_serializer(val, varname=None, **_):
    """Create a json serializer for *val*. """
    return SimpleSerializer(val, save_json, load_json, '.json', varname, sys.modules[__name__])


class PytorchSerializer(Serializer):
    def __init__(self, val, *, evaluable_repr, scope, varname=None, store=True, **_):
        super().__init__(varname, store)
        self.code_graph = _dumper.CodeGraph()
        globals_, _ = self.code_graph.add_startnodes(evaluable_repr, self.varname, scope)
        self.code_graph.build(globals_)
        self.scope = scope
        self.val = val

    def save(self, path):
        path = pathlib.Path(str(path) + f'/torchmodule_{self.i}.pt')
        torch.save(self.val.state_dict(), path)

        complete_path = f"pathlib.Path(__file__).parent / '{path.name}'"

        return _dumper.CodeGraph(
            {**self.code_graph,
             _scope.ScopedName(self.varname + '__load', _scope.Scope.empty(), pos='injected'):  # TODO: use from_source?
                 _dumper.CodeNode(source=f'{self.varname}.load_state_dict({complete_path})',
                          globals_={_scope.ScopedName(self.varname, self.scope)},
                          ast_node=ast.parse(f'{self.varname}.load_state_dict({complete_path})').body[0],
                          name=_scope.ScopedName(self.varname + '__load', self.scope, pos='injected')),
             _scope.ScopedName('pathlib', SCOPE, pos='injected'):
                 _dumper.CodeNode(source='import pathlib',
                          globals_=set(),
                          ast_node=ast.parse('import pathlib').body[0],
                          name=_scope.ScopedName('pathlib', SCOPE, pos='injected'))}
        )


class PickleSerializer(Serializer):
    def __init__(self, val, *, scope, varname=None, store=True, **_):
        super().__init__(varname, store)
        self.scope = scope
        self.code_graph = _dumper.CodeGraph()
        self.class_name = val.__class__.__name__
        globals_, _ = self.code_graph.add_startnodes(self.class_name, None, self.scope)
        self.code_graph.build(globals_)
        self.val = val

    def save(self, path):
        path = pathlib.Path(str(path) + f'/pickle_{self.i}.pkl')

        with open(path, 'wb') as f:
            pickle.dump(self.val, f)

        complete_path = f"pathlib.Path(__file__).parent / '{path.name}'"

        return _dumper.CodeGraph(
            {**self.code_graph,
             _scope.ScopedName(self.varname + '__load', _scope.Scope.empty(), pos='injected'):  # TODO: use from_source?
                 _dumper.CodeNode(source=f"with open({complete_path}, 'rb') as f:\n    {self.varname} = pickle.load(f)",
                          globals_={_scope.ScopedName(self.class_name, self.scope),
                                    _scope.ScopedName('pickle', SCOPE, pos='injected')},
                          ast_node=ast.parse(f"with open({complete_path}, 'rb') as f:\n    {self.varname} = pickle.load(f)").body[0],
                          name=_scope.ScopedName(self.varname + '__load', self.scope, pos='injected')),
             _scope.ScopedName('pathlib', SCOPE, pos='injected'):
                 _dumper.CodeNode(source='import pathlib',
                          globals_=set(),
                          ast_node=ast.parse('import pathlib').body[0],
                          name=_scope.ScopedName('pathlib', SCOPE, pos='injected')),
             _scope.ScopedName('pickle', SCOPE, pos='injected'):
                 _dumper.CodeNode(source='import pickle',
                          globals_=set(),
                          ast_node=ast.parse('import pickle').body[0],
                          name=_scope.ScopedName('pickle', SCOPE, pos='injected'))}
        )
