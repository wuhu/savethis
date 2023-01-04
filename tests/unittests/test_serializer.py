from pathlib import Path
import pytest

from savethis import _serializer, _scope, _source_utils


def trivial_save_function(val, path):
    ...


def trivial_load_function(path):
    return 1


class TestSerializer:
    def test_save_is_not_implemented(self):
        s = _serializer.Serializer()
        with pytest.raises(NotImplementedError):
            s.save('bla')

    def test_complete_path_with_str(self):
        s = _serializer.Serializer()
        assert s.complete_path('ha.txt') == "pathlib.Path(__file__).parent / 'ha.txt'"

    def test_complete_path_with_path(self):
        s = _serializer.Serializer()
        assert s.complete_path(Path('ha.txt')) == "pathlib.Path(__file__).parent / 'ha.txt'"
    def test_complete_path_with_list(self):
        s = _serializer.Serializer()
        assert s.complete_path(['ha.txt', 'ho.txt', 'he.txt']) == \
            "[pathlib.Path(__file__).parent / filename for filename in ['ha.txt', 'ho.txt', 'he.txt']]"

    def test_complete_path_with_something_else_raises(self):
        s = _serializer.Serializer()
        with pytest.raises(ValueError):
            s.complete_path(1)

    def test_auto_varname(self):
        s = _serializer.Serializer()
        assert s.varname.startswith('SAVETHIS_VALUE_')

    def test_custom_varname(self):
        s = _serializer.Serializer(varname='xxx')
        assert s.varname.startswith('xxx')


class TestSimpleSerializer:
    def test_save(self):
        set_val = None
        set_path = None

        def save_function(val, path):
            nonlocal set_val
            nonlocal set_path
            set_val = val
            set_path = path

        s = _serializer.SimpleSerializer(1, save_function, trivial_load_function, 
                                         file_suffix='.txt')
        code_graph = s.save('/bla/')
        code = code_graph.dumps()

        assert set_val == 1
        assert str(set_path).startswith('/bla/')
        assert str(set_path).endswith('.txt')
        assert 'import pathlib' in code
        assert 'def trivial_load_function(path):' in code

    def test_save_no_path(self):
        set_val = None
        set_path = None

        def save_function(val, path):
            nonlocal set_val
            nonlocal set_path
            set_val = val
            set_path = path

        s = _serializer.SimpleSerializer(1, save_function, trivial_load_function, 
                                         file_suffix='.txt')
        s.save(None)
        assert set_val == 1
        assert str(set_path).startswith('?')
        assert str(set_path).endswith('.txt')


class TestNullSerializer:
    def test_save(self):
        s = _serializer.NullSerializer(1, evaluable_repr='1', scope=_scope.Scope.empty(), varname='x')
        codegraph = s.save('bla')
        assert codegraph.dumps().strip() == 'x = 1'


value_for_test_value = _serializer.value(1)


class Test_Serialize:
    def test_int(self):
        assert _serializer._serialize(1) == '1'

    def test_boolean(self):
        assert _serializer._serialize(1 == 1) == 'True'

    def test_json(self):
        assert _serializer._serialize([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]) \
            .startswith('SAVETHIS_VALUE')

    def test_serializer(self):
        assert _serializer._serialize(1, [trivial_load_function, trivial_save_function]).\
            startswith('SAVETHIS_VALUE')

    def test_value(self):
        assert value_for_test_value == 1
        assert 'value_for_test_value = 1\n' in _source_utils.get_source(__file__)

