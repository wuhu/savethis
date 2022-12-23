import linecache
import pytest
from textwrap import dedent

from savethis import _source_utils

from tests.material import source_utils_test


@pytest.fixture
def something_in_replace_cache():
    key = '_rcx'
    _source_utils.replace_cache[key] = 'hallo'
    yield key
    del _source_utils.replace_cache[key]


@pytest.fixture
def clear_cache():
    key = '_rccc'
    yield key
    try:
        del _source_utils.replace_cache[key]
    except KeyError:
        pass


class TestGetSource:
    def test_get_from_replace_cache(self, something_in_replace_cache):
        assert _source_utils.get_source(something_in_replace_cache) == 'hallo'

    def test_get_from_linecache(self):
        linecache.cache['bla'] = (1, 2, ['helllo'], 'bla')
        x = _source_utils.get_source('bla')
        assert x == 'helllo'

    def test_get_from_file(self):
        assert _source_utils.get_source(source_utils_test.__file__, use_replace_cache=False) == '# hello\n'


class TestGetModuleSource:
    def test_it_works(self):
        assert _source_utils.get_module_source(source_utils_test) \
                == '# hello\n'

    def test_from_replace_cache(self, something_in_replace_cache):
        mockmodule = lambda: 0
        mockmodule.__file__ = something_in_replace_cache
        assert _source_utils.get_module_source(mockmodule) == 'hallo'


class TestPutIntoCache:
    def test_it_works(self, clear_cache):
        orig = dedent('''\
            bla bla
            one two
        ''')
        target = dedent('''\
            blip bla
            one two
        ''')
        _source_utils.put_into_cache(clear_cache, orig, 'blip', 0, 0, 0, 3)
        cache_content = _source_utils.replace_cache[clear_cache]
        assert isinstance(cache_content, _source_utils.ReplaceStrings)
        assert cache_content == target

    def test_it_works_with_multiple_replacements(self, clear_cache):
        orig = dedent('''\
            bla bla
            one two
        ''')
        target = dedent('''\
            blip bla
            blip two
        ''')
        _source_utils.put_into_cache(clear_cache, orig, 'blip', 0, 0, 0, 3)
        _source_utils.put_into_cache(clear_cache, orig, 'blip', 1, 1, 0, 3)
        assert _source_utils.replace_cache[clear_cache] == target


class TestOriginal:
    def test_normal_string_is_itself(self):
        assert _source_utils.original('bla') == 'bla'

    def test_replace_string_works(self):
        orig = dedent('''\
            bla bla
            one two
        ''')
        target = dedent('''\
            blip bla
            one two
        ''')
        rs = _source_utils.ReplaceString(orig, 'blip', 0, 0, 0, 3)
        assert rs == target
        assert _source_utils.original(rs) == orig

    def test_replace_strings_works(self):
        orig = dedent('''\
            bla bla
            one two
        ''')
        target = dedent('''\
            blip bla
            blip two
        ''')
        rs1 = _source_utils.ReplaceString(orig, 'blip', 0, 0, 0, 3)
        rs2 = _source_utils.ReplaceString(orig, 'blip', 1, 1, 0, 3)
        rss = _source_utils.ReplaceStrings([rs1, rs2])
        assert rss == target
        assert _source_utils.original(rss) == orig

a = \
'''xxxx
01234567890
01234567890xxxxxxxx
01234567890xxx
01234567890
xxx
'''

a_r = \
'''xxxx
01234567890
01here567890xxxxxxxx
01234567890xxx
01234567890
xxx
'''

a_r1 = \
'''xxxx
01234567890
01he
re890xxxxxxxx
01234567890xxx
01234567890
xxx
'''

a_r2 = \
'''here567890xxxxxxxx
01234567890xxx
01234567890
xxx
'''

a_r3 = \
'''xxxx
01234567890
01here'''

b = '0123456789'

b_r = '0123here6789'


class TestReplace:
    def test_a(self):
        assert _source_utils.replace(a, 'here', 2, 2, 2, 5) == a_r

    def test_one_indexed(self):
        assert _source_utils.replace(a, 'here', 2, 2, 2, 5) == \
            _source_utils.replace(a, 'here', 3, 3, 2, 5, one_indexed=True)

    def test_a1(self):
        assert _source_utils.replace(a, 'he\nre', 2, 2, 2, 8) == a_r1

    def test_b(self):
        assert _source_utils.replace(b, 'here', 0, 0, 4, 6) == b_r

    def test_outside_before_remains_the_same(self):
        assert _source_utils.replace(a, 'here', -1, -1, 4, 6) == a

    def test_outside_after_remains_the_same(self):
        assert _source_utils.replace(a, 'here', 100, 100, 4, 6) == a

    def test_start_before_0(self):
        assert _source_utils.replace(a, 'here', -1, 2, 2, 5) == a_r2

    def test_end_after_len(self):
        assert _source_utils.replace(a, 'here', 2, 200, 2, 5) == a_r3

class TestCut:
    def test_single_line(self):
        assert _source_utils.cut(a, 2, 2, 1, 4) == '123'

    def test_multi_lines(self):
        target = dedent('''\
            1234567890xxxxxxxx
            0123''')
        assert _source_utils.cut(a, 2, 3, 1, 4) == target

    def test_one_indexed(self):
        target = dedent('''\
            1234567890xxxxxxxx
            0123''')
        assert _source_utils.cut(a, 2, 3, 1, 4) == \
            _source_utils.cut(a, 3, 4, 1, 4, one_indexed=True)

    def test_cut_replace_string_outside_replace(self):
        orig = dedent('''\
            bla bla
            one two
        ''')
        rs = _source_utils.ReplaceString(orig, 'blip', 0, 0, 0, 3)
        assert _source_utils.cut(rs, 1, 1, 2, 6) == 'e tw'

    def test_cut_replace_string_outside_replace_multiline(self):
        orig = dedent('''\
            bla bla
            one two
        ''')
        rs = _source_utils.ReplaceString(orig, 'blip', 0, 0, 0, 3)
        assert _source_utils.cut(rs, 0, 1, 4, 6) == 'bla\none tw'

    def test_cut_replace_string_around_replace(self):
        orig = dedent('''\
            bla bla
            one two
        ''')
        rs = _source_utils.ReplaceString(orig, 'blip', 0, 0, 0, 3)
        assert _source_utils.cut(rs, 0, 0, 0, 6) == 'blip bl'

    def test_cut_replace_string_around_replace_multiline(self):
        orig = dedent('''\
            bla bla
            one two
        ''')
        rs = _source_utils.ReplaceString(orig, 'blip', 0, 0, 0, 3)
        assert _source_utils.cut(rs, 0, 1, 0, 6) == 'blip bla\none tw'

    def test_cut_replace_string_around_replace_multiline_2(self):
        orig = dedent('''\
            he ho
            bla bla
            one two
            he ho
        ''')
        target = dedent('''\
            e ho
            blip bla
            one two
            h''')
        rs = _source_utils.ReplaceString(orig, 'blip', 1, 1, 0, 3)
        assert _source_utils.cut(rs, 0, 3, 1, 1) == target

    def test_cut_replace_string_inside_replace_raises(self):
        orig = dedent('''\
            bla bla
            one two
        ''')
        rs = _source_utils.ReplaceString(orig, 'blip', 0, 0, 0, 3)
        with pytest.raises(ValueError):
            _source_utils.cut(rs, 0, 0, 2, 6)

    def test_cut_replace_string_inside_replace_raises_2(self):
        orig = dedent('''\
            bla bla
            one two
        ''')
        rs = _source_utils.ReplaceString(orig, 'blip', 0, 0, 0, 3)
        with pytest.raises(ValueError):
            _source_utils.cut(rs, 0, 0, 0, 2)

    def test_cut_replace_strings_outside(self):
        orig = dedent('''\
            he ho
            bla bla
            one two
            he ho''')
        target = dedent('''\
            he ho
            blip bla
            one blip
            he ho''')
        rs1 = _source_utils.ReplaceString(orig, 'blip', 1, 1, 0, 3)
        rs2 = _source_utils.ReplaceString(orig, 'blip', 2, 2, 4, 7)
        rss = _source_utils.ReplaceStrings([rs1, rs2])
        assert _source_utils.cut(rss, 3, 3, 0, 2) == 'he'

    def test_cut_replace_strings_around(self):
        orig = dedent('''\
            he ho
            bla bla
            one two
            he ho''')
        target = dedent('''\
            blip bla
            one blip
            he''')
        rs1 = _source_utils.ReplaceString(orig, 'blip', 1, 1, 0, 3)
        rs2 = _source_utils.ReplaceString(orig, 'blip', 2, 2, 4, 7)
        rss = _source_utils.ReplaceStrings([rs1, rs2])
        assert _source_utils.cut(rss, 1, 3, 0, 2) == target

    def test_cut_replace_strings_between(self):
        orig = dedent('''\
            he ho
            bla bla
            one two
            he ho''')
        target = dedent('''\
            blip bla
            on''')
        rs1 = _source_utils.ReplaceString(orig, 'blip', 1, 1, 0, 3)
        rs2 = _source_utils.ReplaceString(orig, 'blip', 2, 2, 4, 7)
        rss = _source_utils.ReplaceStrings([rs1, rs2])
        assert _source_utils.cut(rss, 1, 2, 0, 2) == target
