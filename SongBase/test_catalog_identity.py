"""Regression: identical title/artist must not collapse distinct QQ MIDs."""
import build_annotation_gap_report as gap

original = gap.read_json
try:
    gap.read_json = lambda _path: {'tracks': [
        {'songBaseId': identity, 'trackId': identity, 'title': 'Lamp', 'artist': 'haruka nakamura'}
        for identity in ('qq:one', 'qq:two')]}
    index = {(gap.text_key('Lamp'), gap.text_key('haruka nakamura')): {'qq:one', 'qq:two'}}
    assert gap.catalog_ids(index, {'artistAliases': {}}) == {'qq:one', 'qq:two'}
    try:
        gap.catalog_ids({next(iter(index)): {'qq:one'}}, {'artistAliases': {}})
    except ValueError:
        pass
    else:
        raise AssertionError('Identity/title conflict was silently accepted')
finally:
    gap.read_json = original
print('Catalog QQ identity regression passed')
