import pathlib, ast
bad = []
for p in pathlib.Path('src').rglob('*.py'):
    try:
        ast.parse(p.read_text(encoding='utf-8', errors='replace'), filename=str(p))
    except SyntaxError as e:
        bad.append((str(p), f"line {e.lineno}: {e.msg}"))
for b in bad:
    print(b)
print('bad count', len(bad))
