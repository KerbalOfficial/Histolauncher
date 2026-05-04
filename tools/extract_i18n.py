import os, re, json

def find_files(d, ext):
    res = []
    for root, dirs, files in os.walk(d):
        if 'vendor' in root: continue
        for f in files:
            if f.endswith(ext): res.append(os.path.join(root, f))
    return res

keys = set()

for f in find_files('src/ui', '.html'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
        for m in re.finditer(r'data-i18n(?:-[a-z]+)?="([^"]+)"', content):
            keys.add(m.group(1))

for f in find_files('src/ui', '.js'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
        for m in re.finditer(r'(?<![\w])t\([\'"]([^\'"]+)[\'"]\)', content):
            keys.add(m.group(1))

obj = {}
for k in sorted(list(keys)):
    parts = k.split('.')
    current = obj
    for p in parts[:-1]:
        if p not in current: current[p] = {}
        current = current[p]
    current[parts[-1]] = k

os.makedirs('src/ui/i18n', exist_ok=True)
with open('src/ui/i18n/en.json', 'w', encoding='utf-8') as file:
    json.dump(obj, file, indent=2)

with open('src/ui/i18n/es.json', 'w', encoding='utf-8') as file:
    json.dump(obj, file, indent=2)

print('Done')
