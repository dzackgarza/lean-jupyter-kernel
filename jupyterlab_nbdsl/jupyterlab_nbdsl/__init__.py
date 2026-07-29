"""JupyterLab prebuilt extension: Lean 4 syntax highlighting for nbdsl cells."""

__version__ = "0.1.0"


def _jupyter_labextension_paths():
    return [{"src": "labextension", "dest": "jupyterlab_nbdsl"}]
