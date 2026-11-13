"""Unicode 17.0 character data for the tokenize bundle (the version of ICU 78.2 in Lair's Electron).

Reads UnicodeData.txt, Scripts.txt, DerivedCoreProperties.txt and SpecialCasing.txt of UCD 17.0.0 from
bench/l0/work/ucd17 (downloaded from unicode.org on first use, the header line checked) and gives:
  lower1[c]   the simple lowercase mapping where it differs from c (UnicodeData field 13)
  lower_full  the unconditional full lowercase mappings of SpecialCasing.txt that differ from lower1
              (only U+0130 in 17.0)
  word        code points of general category L* or N* (the JavaScript [\\p{L}\\p{N}])
  cjk         code points of Script Hangul, Han, Hiragana or Katakana
  cased, ignorable   the Cased and Case_Ignorable properties (Final_Sigma context)
"""
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UCD = HERE / 'work' / 'ucd17'
BASE = 'https://www.unicode.org/Public/17.0.0/ucd/'
FILES = ['UnicodeData.txt', 'Scripts.txt', 'DerivedCoreProperties.txt', 'SpecialCasing.txt']
CJK_SCRIPTS = {'Hangul', 'Han', 'Hiragana', 'Katakana'}


def fetch():
    UCD.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = UCD / name
        if not path.exists():
            data = urllib.request.urlopen(BASE + name, timeout=60).read()
            path.write_bytes(data)
    for name in FILES[1:]:
        first = (UCD / name).read_text().split('\n', 1)[0]
        if '17.0.0' not in first:
            raise RuntimeError('%s is not UCD 17.0.0: %r' % (name, first))


def ranges(text):
    for line in text.split('\n'):
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        fields = [f.strip() for f in line.split(';')]
        a, _, b = fields[0].partition('..')
        yield int(a, 16), int(b or a, 16), fields[1:]


def load():
    fetch()
    lower1, word = {}, set()
    first = None
    for line in (UCD / 'UnicodeData.txt').read_text().split('\n'):
        if not line:
            continue
        f = line.split(';')
        c = int(f[0], 16)
        if f[1].endswith(', First>'):
            first = c
            continue
        lo = first if f[1].endswith(', Last>') else c
        first = None
        for x in range(lo, c + 1):
            if f[2][0] in 'LN':
                word.add(x)
            if f[13]:
                lower1[x] = int(f[13], 16)
    cjk = set()
    for a, b, rest in ranges((UCD / 'Scripts.txt').read_text()):
        if rest[0] in CJK_SCRIPTS:
            cjk.update(range(a, b + 1))
    cased, ignorable = set(), set()
    for a, b, rest in ranges((UCD / 'DerivedCoreProperties.txt').read_text()):
        if rest[0] == 'Cased':
            cased.update(range(a, b + 1))
        elif rest[0] == 'Case_Ignorable':
            ignorable.update(range(a, b + 1))
    lower_full = {}
    for a, _, rest in ranges((UCD / 'SpecialCasing.txt').read_text()):
        if len(rest) >= 4 and rest[3]:
            continue  # conditional
        full = [int(x, 16) for x in rest[0].split()]
        if full != [lower1.get(a, a)]:
            lower_full[a] = full
    return dict(lower1=lower1, lower_full=lower_full, word=word, cjk=cjk, cased=cased, ignorable=ignorable)
