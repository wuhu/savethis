from pathlib import Path
import pytest
from textwrap import dedent

from savethis import core
from savethis._param_replace import param


class TestBuildCodeGraph:
    def test_for_simple_function(self):
        # Test building a code graph for a simple function
        x = 100
        def test_func(a, b):
            return a + b + x
        code_graph = core.build_codegraph(test_func)
        assert code_graph.dumps() == \
            dedent('''\
                x = 100


                def test_func(a, b):
                    return a + b + x
                ''')

    def test_for_simple_class(self):
        # Test building a code graph for a simple class
        class TestClass:
            def __init__(self, a, b):
                self.a = a
                self.b = b
            def test_method(self):
                return self.a + self.b
        code_graph = core.build_codegraph(TestClass)
        assert code_graph.dumps() == \
            dedent('''\
                class TestClass:
                    def __init__(self, a, b):
                        self.a = a
                        self.b = b
                    def test_method(self):
                        return self.a + self.b
                ''')


class TestDumps:
    def test_for_simple_function(self):
        # Test building a code graph for a simple function
        x = 100
        def test_func(a, b):
            return a + b + x
        dump = core.dumps(test_func)
        assert dump == \
            dedent('''\
                x = 100


                def test_func(a, b):
                    return a + b + x
                ''')

    def test_for_simple_class(self):
        # Test building a code graph for a simple class
        class TestClass:
            def __init__(self, a, b):
                self.a = a
                self.b = b
            def test_method(self):
                return self.a + self.b
        dump = core.dumps(TestClass)
        assert dump == \
            dedent('''\
                class TestClass:
                    def __init__(self, a, b):
                        self.a = a
                        self.b = b
                    def test_method(self):
                        return self.a + self.b
                ''')


class TestSave:
    def test_overwrite_fails(self, tmpdir):
        x = 1
        y = 2
        path = Path(tmpdir) / 'test'

        core.save(x, path)
        with pytest.raises(FileExistsError):
            core.save(y, path)

    def test_forced_overwrite_works(self, tmpdir):
        x = 1
        y = 2
        path = Path(tmpdir) / 'test.padl'

        core.save(x, path)
        core.save(y, path, force_overwrite=True)
        z = core.load(path)
        assert z == y

    def test_save_load_simple_function(self, tmpdir):
        # Test saving a simple function
        x = 100

        def test_func(a, b):
            return a + b + x

        path = Path(tmpdir) / 'test.padl'
        core.save(test_func, path, pickle=False, force_overwrite=True)
        assert path.exists()
        f = core.load(path)
        assert f.__name__ == 'test_func'
        assert f(1, 2) == 103
        
    def test_save_load_simple_class(self, tmpdir):
        # Test saving a more complex object
        x = 100
        class TestClass:
            def __init__(self, a, b):
                self.a = a
                self.b = b
            def test_method(self):
                return self.a + self.b + 100
        obj = TestClass(1, 2)
        path = Path(tmpdir) / 'test.padl'
        core.save(obj, path, pickle=False, force_overwrite=True)
        assert path.exists()
        f = core.load(path)
        assert f.__class__.__name__ == 'TestClass'
        assert f.test_method() == 103

    @pytest.mark.filterwarnings('ignore:requirement was not found')
    def test_save_load_with_params(self, tmpdir):
        # Test saving a simple function
        x = param('x', 100)
        y = param('y', 10)

        def test_func(a, b):
            return (a + b + x) * y

        path = Path(tmpdir) / 'test.padl'
        core.save(test_func, path, pickle=False, force_overwrite=True)
        assert path.exists()
        f = core.load(path, x=1000)
        assert f.__name__ == 'test_func'
        assert f(1, 2) == 10030
