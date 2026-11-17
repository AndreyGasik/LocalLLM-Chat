# core/tool_parsing.py — тонкая обёртка над Common/tool_parsing.py
import importlib.util, os, sys
from pathlib import Path

def _find_common():
    here = Path(__file__).resolve()
    cands = []
    env = os.environ.get('LLMCHAT_COMMON')
    if env: cands.append(Path(env))
    cands += [here.parents[2] / 'LLM-Chat-Common', here.parents[1] / 'common']
    for c in cands:
        f = c / 'tool_parsing.py'
        if f.is_file(): return c
    raise ImportError('LLM-Chat-Common не найден')

_SPEC = 'llmchat_common_tool_parsing'
if _SPEC not in sys.modules:
    _p = _find_common() / 'tool_parsing.py'
    _spec = importlib.util.spec_from_file_location(_SPEC, _p)
    _m = importlib.util.module_from_spec(_spec)
    sys.modules[_SPEC] = _m
    _spec.loader.exec_module(_m)

globals().update({k: v for k, v in vars(_m).items()
                  if not (k.startswith('__') and k.endswith('__'))})
