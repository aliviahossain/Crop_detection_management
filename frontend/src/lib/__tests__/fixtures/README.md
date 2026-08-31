# Test fixtures

`yolo3class.onnx` (2 KB) is a synthetic model with the exact output signature of
a YOLOv8 3-class detect export: input `images` float32 (1,3,640,640), output
`(1, 7, N)`. It ignores the input and emits one late blight box at
cx=320 cy=320 w=200 h=100 conf=0.88.

It exists so `ortIntegration.test.js` can prove that onnxruntime-web really
loads and runs a model, and that the browser decoder produces the same box as
the Python server — without needing a 12 MB trained checkpoint in git.

Regenerate it with the same helper the backend tests use:

```bash
PYTHONPATH=backend python -c "
import sys; sys.path.insert(0, 'backend/tests')
from test_onnx_integration import build_yolo_like_onnx
from pathlib import Path
build_yolo_like_onnx(Path('frontend/src/lib/__tests__/fixtures/yolo3class.onnx'),
                     [(320.0, 320.0, 200.0, 100.0, 1, 0.88)])
"
```

Requires `pip install -r backend/requirements-dev.txt` (for `onnx`).
