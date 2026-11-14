#!/usr/bin/env python3
"""2D front+side layout for variant B5. Renders layout_b5.png via the CAD model."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "cad_b5"))
import b5_model as m

if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "layout_b5.png"
    m.render_layout_2d(str(out))
    print(out)
