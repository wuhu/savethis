import importlib
import os
from pathlib import Path
from shutil import copytree, rmtree
from tempfile import TemporaryDirectory
import types
from typing import Union, Optional
import zipfile

from . import _inspect_utils, _package_utils, _scope, _param_replace, _serializer
from ._dumper import CodeGraph
from . import serializers


def build_codegraph(obj, name=None):
    """Build a code graph for the given object.
    
    A code graph represents the dependencies and code needed to recreate the object.
    
    :param obj: The object to build the code graph for.
    :param name: The name to give the object in the code graph. If not provided, a name will
        be generated automatically.
    :return: The code graph for the object.
    """
    evaluable_repr = _inspect_utils.get_argument_assignments(['obj'])['obj']
    call_info = _inspect_utils.CallInfo()
    scope = call_info.scope
    code_graph = CodeGraph()
    globals_, scoped_name = code_graph.add_startnodes(evaluable_repr, name, scope)
    return code_graph.build(globals_)


def dumps(obj) -> str:
    """Convert the object to python code that would recreate it.
    
    :param obj: The object.
    :return: The python code as a string.
    """
    return build_codegraph(obj).dumps()


def save(obj, path: Union[Path, str], pickle: bool = False, force_overwrite: bool = False,
         strict_requirements: bool = False,
         serializer: _serializer.Serializer = serializers.NullSerializer):  # TODO: compress
    """Save *obj* to a folder at *path*.

    The folder's name should end with '.padl'. If no extension is given, it will be added
    automatically.

    If the folder exists, call with *force_overwrite* = `True` to overwrite. Otherwise, this
    will raise a FileExistsError.

    :param obj: The object to be saved.
    :param path: The path to save the object at.
    :param pickle: If *True*, pickle *obj*.
    :param force_overwrite: If *True*, overwrite any existing saved object at *path*.
    :param strict_requirements: If *True*, fail if any of the Transform's requirements cannot
        be found. If *False* print a warning if that's the case.
    :param serializer: TODO
    """
    # add suffix if needed
    path = Path(path)
    if path.suffix == '':
        path = path.parent / (path.name + '.padl')

    # handle case that folder exists
    if path.exists() and list(path.glob('*')):
        if not force_overwrite:
            raise FileExistsError(f'{path} exists, call with *force_overwrite* to overwrite.')

        with TemporaryDirectory('.padl') as dirname:
            save(obj, dirname, False, strict_requirements=strict_requirements,
                 serializer=serializer)
            rmtree(path)
            copytree(dirname, path)
        return

    # create folder
    path.mkdir(exist_ok=True)

    # build codegraph
    evaluable_repr = _inspect_utils.get_argument_assignments(['obj'], vararg='vararg')['obj']
    scope = _inspect_utils.CallInfo().scope
    codegraph = serializer(obj, varname='__savethis', evaluable_repr=evaluable_repr,
                           scope=scope, store=False).save(path)
    _serializer.Serializer.save_all(codegraph, path)

    # find requirements
    try:
        requirements = _package_utils.dump_requirements(
                (node.ast_node for node in codegraph.values()),
                strict=strict_requirements)
    except _package_utils.RequirementNotFound as exc:  # pragma: no cover
        raise _package_utils.RequirementNotFound(
                f'Could not find an installed version of '
                f'"{exc.package}", which the object you\'re saving depends on. '
                'Run with *strict_requirements=False* to ignore.',
                exc.package) from exc

    # dump code
    code = codegraph.dumps()

    # save
    with open(path / 'src.py', 'w', encoding='utf-8') as f:
        f.write(code)
    with open(path / 'requirements.txt', 'w', encoding='utf-8') as f:
        f.write(requirements)


def _zip_load(path: Union[Path, str]):
    """Load an object from a compressed '.padl' file. """
    # we can't use TemporaryDirectory with a context because the files need to exist when
    # using / saving again
    dirname = TemporaryDirectory('.padl').name
    with zipfile.ZipFile(path, 'r') as zipf:
        zipf.extractall(dirname)
        return load(dirname)


def load(path, **kwargs):
    """Load an object (as saved with padl.save) from *path*.

    Use keyword arguments to override params (see :func:`padl.param`).
    """
    if kwargs:
        _, parsed_kwargs, _, _ = _inspect_utils.get_my_call_signature()
    else:
        parsed_kwargs = {}
    return load_noparse(path, parsed_kwargs)


def load_noparse(path, parsed_kwargs):
    if Path(path).is_file():
        return _zip_load(path)
    path = Path(path)

    with open(path / 'src.py', encoding='utf-8') as f:
        source = f.read()

    scope = _inspect_utils._get_scope_from_frame(_inspect_utils.caller_frame(), 0)
    source = _param_replace.apply_params(source, parsed_kwargs, scope)

    class _EmptyLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return types.ModuleType(spec.name)

    module_name = str(path).replace('/', os.path.sep).lstrip('.') + '.source'
    spec = importlib.machinery.ModuleSpec(module_name, _EmptyLoader())
    module = importlib.util.module_from_spec(spec)

    module.__dict__.update({  # TODO: this all needed?
        '_pd_is_padl_file': True,
        '_pd_source': source,
        '_pd_module': module,
        '_pd_full_dump': True,
    })

    if parsed_kwargs:
        tempdir = TemporaryDirectory()
        module_path = Path(tempdir.name) / 'src.py'
        with open(module_path, 'w', encoding='utf-8') as f:
            f.write(source)
        module.__dict__['_pd_tempdir'] = tempdir
    else:
        module_path = path / 'src.py'

    module.__dict__['__file__'] = str(module_path)

    code = compile(source, module_path, 'exec')

    # pylint: disable=exec-used
    exec(code, module.__dict__)

    # pylint: disable=no-member,protected-access
    obj = module.__savethis

    return obj
