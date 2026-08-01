"""Distribution artifacts preserve the adapter's validated build identity."""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from nbdsl_kernel.protocol import BuildInfo

REPO = Path(__file__).resolve().parents[2]


def test_generated_sdist_builds_an_identity_bearing_wheel(
        tmp_path: Path) -> None:
    """The published-source boundary is sufficient to reproduce the wheel."""
    sdist_dir = tmp_path / "sdist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--outdir",
            str(sdist_dir),
            str(REPO / "nbdsl_kernel"),
        ],
        check=True,
    )
    sdists = list(sdist_dir.glob("nbdsl_kernel-*.tar.gz"))
    assert len(sdists) == 1, sdists

    source_dir = tmp_path / "source"
    shutil.unpack_archive(sdists[0], source_dir)
    roots = [path for path in source_dir.iterdir() if path.is_dir()]
    assert len(roots) == 1, roots

    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        [
            sys.executable,
            "-m", "build",
            "--wheel",
            "--outdir",
            str(wheel_dir),
            str(roots[0]),
        ],
        check=True,
    )
    wheels = list(wheel_dir.glob("nbdsl_kernel-*.whl"))
    assert len(wheels) == 1, wheels

    with zipfile.ZipFile(wheels[0]) as wheel:
        identities = [
            name for name in wheel.namelist()
            if name.endswith("nbdsl_kernel/_build_info.json")
        ]
        assert len(identities) == 1, identities
        identity = BuildInfo.model_validate_json(wheel.read(identities[0]))
    assert identity.commit
