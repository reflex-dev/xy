from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDSH = ROOT / "examples" / "pdsh"


def test_pdsh_notebooks_contain_fresh_matplotlib_and_xy_sections() -> None:
    subprocess.run(
        [sys.executable, str(PDSH / "sync_dual_engine_notebooks.py"), "--check"],
        cwd=ROOT,
        check=True,
    )
    paths = sorted(PDSH.glob("pdsh_*.ipynb"))
    assert len(paths) == 14
    for path in paths:
        notebook = json.loads(path.read_text(encoding="utf-8"))
        code_cells = [cell for cell in notebook["cells"] if cell.get("cell_type") == "code"]
        engines = [cell.get("metadata", {}).get("xy_pdsh_engine") for cell in code_cells]
        assert "matplotlib" in engines and "xy" in engines
        assert len(code_cells) % 2 == 0
        assert all(
            engines[index : index + 2] == ["matplotlib", "xy"]
            for index in range(0, len(engines), 2)
        )
        assert all(
            code_cells[index]["metadata"]["xy_pdsh_source_id"]
            == code_cells[index + 1]["metadata"]["xy_pdsh_source_id"]
            for index in range(0, len(code_cells), 2)
        )
        mpl_code = "\n".join(
            "".join(cell.get("source", []))
            for cell in notebook["cells"]
            if cell.get("metadata", {}).get("xy_pdsh_engine") == "matplotlib"
            and cell.get("cell_type") == "code"
        )
        xy_code = "\n".join(
            "".join(cell.get("source", []))
            for cell in notebook["cells"]
            if cell.get("metadata", {}).get("xy_pdsh_engine") == "xy"
            and cell.get("cell_type") == "code"
        )
        assert "xy.pyplot" not in mpl_code
        assert "matplotlib" in mpl_code
        assert "xy.pyplot" in xy_code
        assert "xy_plt.show()" not in xy_code
