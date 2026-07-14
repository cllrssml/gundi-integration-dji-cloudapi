#!/usr/bin/env python3
"""Idempotently add the persistence calls (workspace + platform registration)
to the deployed login.html WITHOUT touching the injected credentials."""
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/home/sam/deploy/login.html"
WS = "97dffb09-5c1e-45fe-955f-48381b90ed3b"
html = open(PATH).read()

if "WORKSPACE_ID" in html:
    print("already patched; nothing to do")
    sys.exit(0)

const_line = f'      const WORKSPACE_ID = "{WS}";\n'
anchor1 = '      var fieldList = document.getElementById("logs");'
if anchor1 not in html:
    sys.exit("anchor1 not found")
html = html.replace(anchor1, const_line + anchor1, 1)

reg_block = (
    '        window.djiBridge.platformSetWorkspaceId(WORKSPACE_ID);\n'
    '        window.djiBridge.platformSetInformation(\n'
    '          "ER Live Telemetry", "CFW", "DJI to EarthRanger live telemetry");\n'
    '        log("registered platform (persistent): ws=" + WORKSPACE_ID);\n'
)
anchor2 = '        log("thingConnect: " +'
if anchor2 not in html:
    sys.exit("anchor2 not found")
html = html.replace(anchor2, reg_block + anchor2, 1)

open(PATH, "w").write(html)
print("patched: added platformSetWorkspaceId + platformSetInformation")
