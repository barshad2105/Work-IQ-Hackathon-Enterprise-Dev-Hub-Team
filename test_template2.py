#!/usr/bin/env python3

with open(r'templates\index.html', 'r', encoding='utf-8') as f:
    content = f.read()
    
print('Total file size:', len(content))

# Find 'initPanelOrchestrator'
idx = content.find('initPanelOrchestrator')
print(f'initPanelOrchestrator starts at: {idx}')

# What Flask is returning
flask_size = 68359
print(f'Flask returns: {flask_size} bytes')
print(f'Bytes before initPanelOrchestrator: {idx}')
print(f'Flask ends relative to function: {flask_size - idx} bytes into the function')

print('\nContent from position 68350 to 68370:')
print(repr(content[68350:68370]))

print('\nLast 100 bytes Flask returns:')
print(repr(content[68259:68359]))

print('\nFirst 100 bytes AFTER what Flask returns:')
print(repr(content[68359:68459]))
