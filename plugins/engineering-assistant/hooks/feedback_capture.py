#!/usr/bin/env python3
import importlib.util
import json
import sys
from pathlib import Path
def emit_empty():
    json.dump({}, sys.stdout); sys.stdout.write('\n'); return 0
try:
    root = Path(__file__).resolve().parents[1]
    gate_path = root / 'engineering-assistant/runtime/engineering_assistant/runtime/hook_gate.py'
    spec = importlib.util.spec_from_file_location('_engineering_assistant_hook_gate', gate_path)
    if spec is None or spec.loader is None:
        raise ImportError('hook gate loader is unavailable')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    should_load, raw = gate.read_gate_input(sys.stdin)
    if should_load:
        import io
        sys.path.insert(0, str(root / 'engineering-assistant/runtime'))
        from engineering_assistant.runtime.feedback import run_codex_hook
        output = io.StringIO()
        exit_code = run_codex_hook(input_stream=io.StringIO(raw), output_stream=output, schema_root=root / 'engineering-assistant/schemas')
        sys.stdout.write(output.getvalue())
    else:
        exit_code = emit_empty()
except Exception:
    exit_code = emit_empty()
raise SystemExit(exit_code)
