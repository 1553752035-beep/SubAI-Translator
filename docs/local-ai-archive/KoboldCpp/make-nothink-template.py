# -*- coding: utf-8 -*-
"""Generate a no-think chat template from a source jinja template.

Takes the official Qwen3.6 chat template (exported from the model / HF repo)
and removes the conditional enable_thinking branch, keeping only the
empty-thinking-block injection so reasoning is always skipped and all
tokens go to the answer.

Usage:
    python make-nothink-template.py [source.jinja] [output.jinja]
"""
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "chat_template.jinja"
DST = sys.argv[2] if len(sys.argv) > 2 else "qwen36-nothink.jinja"

PATTERN = re.compile(
    r"\{%- if enable_thinking is defined and enable_thinking is false %\}"
    r"(.*?)"
    r"\{%- else %\}"
    r"(.*?)"
    r"\{%- endif %\}",
    re.S,
)

with open(SRC, "r", encoding="utf-8") as f:
    tpl = f.read()
tpl = tpl.replace("\r\n", "\n").replace("\r", "\n")

m = PATTERN.search(tpl)
if not m:
    print("ERROR: conditional thinking branch not found in", SRC)
    sys.exit(1)

# keep only the enable_thinking==false branch (empty thinking block)
tpl = PATTERN.sub(lambda mm: mm.group(1), tpl, count=1)

with open(DST, "w", encoding="utf-8", newline="\n") as f:
    f.write(tpl)
print("written:", DST)
