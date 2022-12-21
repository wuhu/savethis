# TODO: module docstring
import ast
from collections.abc import Iterable
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable, List, Optional

from . import _inspect_utils, _source_utils, _dumper
from ._dumper import CodeNode, CodeGraph
from ._scope import Scope, ScopedName


SCOPE = Scope.toplevel(sys.modules[__name__])


class Serializer:
    store: List = []
    i: int = 0

    def __init__(self, varname=None, store=True):
        self.index = Serializer.i
        Serializer.i += 1
        self._varname = varname
        self.code_graph = _dumper.CodeGraph()
        if store:
            self.store.append(self)

    def save(self, path: Path):
        raise NotImplementedError

    @classmethod
    def save_all(cls, codegraph, path):
        """Save all values. """
        for codenode in list(codegraph.values()):
            for serializer in cls.store:
                if serializer.varname in codenode.source:
                    loader_graph = serializer.save(path)
                    codegraph.update(loader_graph)

    def complete_path(self, filename):
        if isinstance(filename, (str, Path)):
            return f"pathlib.Path(__file__).parent / '{filename}'"
        elif isinstance(filename, Iterable):
            return ('[pathlib.Path(__file__).parent / filename for filename in ['
                    + ', '.join(f"'{fn}'" for fn in filename)
                    + ']]')
        else:
            raise ValueError('The save function must return a filename, a list of filenames or '
                             'nothing.')

    @property
    def varname(self):
        """The varname to store in the dumped code. """
        if self._varname is not None:
            return self._varname
        return f'SAVETHIS_VALUE_{self.index}'


class SimpleSerializer(Serializer):
    # TODO: explain better
    """Serializer base class.

    :param val: The value to serialize.
    :param save_function: The function to use for saving *val*.
    :param load_function: The function to use for loading *val*.
    :param file_suffix: If set, a string that will be appended to the path.
    :param module: The module the serializer functions are defined in. Optional, default is to
        use the calling module.
    """
    def __init__(self, val: Any, save_function: Callable, load_function: Callable,
                 file_suffix: Optional[str] = None, varname: Optional[str] = None,
                 module: Optional[ModuleType] = None, store: bool = True, **_):  # TODO: why not get the module from the functions??
        super().__init__(varname, store)
        self.val = val
        self.save_function = save_function
        self.file_suffix = file_suffix
        if module is None:
            module = _inspect_utils.caller_module()
        self.scope = Scope.toplevel(module)
        self.code_graph.build(ScopedName(load_function.__name__,
                                         Scope.toplevel(load_function.__module__)))
        self.load_name = load_function.__name__

    def save(self, path: Path):
        """Save the serializer's value to *path*.

        Returns a codegraph containing code needed to load the value.
        """
        if path is None:
            path = Path('?')
        if self.file_suffix is not None:
            path = Path(str(path) + f'/{self.i}{self.file_suffix}')
        filename = self.save_function(self.val, path)
        if filename is None:
            assert self.file_suffix is not None, ('if no file file_suffix is passed to *value*, '
                                                  'the *save*-function must return a filename')
            filename = path.name

        complete_path = self.complete_path(filename)
        code_graph = CodeGraph(self.code_graph)
        code_graph.inject(
             CodeNode(source=f'{self.varname} = {self.load_name}({complete_path})',
                      globals_={ScopedName(self.load_name, self.scope)},
                      scope=self.scope, pos='injected'),
        )
        code_graph.inject(
             CodeNode(source='import pathlib', scope=SCOPE, pos='injected')
        )
        return code_graph


class NullSerializer(Serializer):
    """A Serializer that does nothing. """
    def __init__(self, val, *, evaluable_repr, scope, varname=None, store=True, **_):
        super().__init__(varname, store)
        globals_, scoped_name = self.code_graph.add_startnodes(evaluable_repr, self.varname, scope)
        self.code_graph.build(globals_)

    def save(self, path):
        return self.code_graph


def _serialize(val, serializer=None):
    if serializer is not None:
        return Serializer(val, *serializer).varname
    if hasattr(val, '__len__') and len(val) > 10:
        return serializers.json_serializer(val).varname
    return repr(val)


def value(val, serializer=None):
    """Helper function that marks things in the code that should be stored by value. """
    # TODO: what if this is called from within a function?
    caller_frameinfo = _inspect_utils.outer_caller_frameinfo(__name__)
    _call, locs = _inspect_utils.get_segment_from_frame(caller_frameinfo.frame, 'call', True)
    source = _source_utils.get_source(caller_frameinfo.filename)
    _source_utils.put_into_cache(caller_frameinfo.filename, _source_utils.original(source),
                                 _serialize(val, serializer=serializer), *locs)
    return val
