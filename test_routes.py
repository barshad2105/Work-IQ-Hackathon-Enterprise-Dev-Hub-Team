#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
import app as app_module

print("App module loaded")
print("View functions:", list(app_module.app.view_functions.keys()))
print("URL map:")
for rule in app_module.app.url_map.iter_rules():
    print(f"  {rule}")
