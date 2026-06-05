from pathlib import Path
path = str(Path(__file__).parent / 'ios-pentest-lab' / 'dashboard' / 'app.py')
content = open(path, encoding='utf-8').read()

# Replace curly/smart quotes with ASCII equivalents (these cause SyntaxError in docstrings)
replacements = {
    '“': '"',
    '”': '"',
    '‘': "'",
    '’': "'",
    '–': '-',
    '—': '--',
    '…': '...',
}
for bad, good in replacements.items():
    before = content.count(bad)
    content = content.replace(bad, good)
    if before:
        print(f'Replaced {before}x U+{ord(bad):04X}')

open(path, 'w', encoding='utf-8').write(content)
print('Written OK')

# Check remaining non-ASCII (these are ok in comments)
non_ascii = []
for i, line in enumerate(content.splitlines()):
    for j, ch in enumerate(line):
        if ord(ch) > 127:
            non_ascii.append((i+1, j, ch, line.lstrip()[:30]))

if non_ascii:
    print(f'{len(non_ascii)} non-ASCII chars remain (in comments/strings, OK for Python 3):')
    seen = set()
    for lineno, col, ch, ctx in non_ascii[:10]:
        key = (lineno, col)
        if key not in seen:
            seen.add(key)
            print(f'  line {lineno} col {col}: U+{ord(ch):04X}  context: {repr(ctx)}')
