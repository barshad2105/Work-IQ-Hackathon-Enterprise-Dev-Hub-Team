#!/usr/bin/env python3
import os

html_file = r'templates\index.html'

with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()
    
print('File size:', len(content), 'bytes')
has_init = 'initPanelOrchestrator' in content
print('Has initPanelOrchestrator:', has_init)
if has_init:
    idx = content.find('initPanelOrchestrator')
    print('First occurrence at:', idx)
print('Last 300 chars:')
print(repr(content[-300:]))
