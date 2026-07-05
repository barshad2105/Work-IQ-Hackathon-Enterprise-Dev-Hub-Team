#!/usr/bin/env python3
with open(r'templates\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

print(f'Python read file size: {len(content)}')
if 'initPanelOrchestrator' in content:
    idx = content.find('initPanelOrchestrator')
    print(f'initPanelOrchestrator found at byte {idx}')
    print(f'That is {len(content) - idx} bytes from the end')

# Check what's at Flask's truncation point
flask_end = 68359
if len(content) > flask_end:
    print(f'\nContent at byte {flask_end} (Flask end +/- 50 bytes):')
    print(repr(content[flask_end-50:flask_end+50]))
    print(f'\nWhat flask sees: {repr(content[:flask_end][-50:])}')
    print(f'What Flask misses starts with: {repr(content[flask_end:flask_end+50])}')
