from __future__ import annotations

import subprocess
import sys


def test_validate_knowledge_base_script_passes_on_seed_data() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_knowledge_base.py"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK germplasm:" in result.stdout
    assert "OK crop_kg:foxtail_millet:" in result.stdout
    assert "OK rag:" in result.stdout
    assert "OK marker_qtl:" in result.stdout
    assert "OK phenotype_protocol:" in result.stdout
    assert "OK field_trial:" in result.stdout
    assert "OK template:marker_qtl:" in result.stdout
    assert "OK template:phenotype_protocol:" in result.stdout
    assert "OK template:field_trial:" in result.stdout
    assert "Knowledge base validation passed." in result.stdout
