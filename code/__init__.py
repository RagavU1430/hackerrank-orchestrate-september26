"""HackerRank Orchestrate - Buy or Wait?
AI Financial Decision Agent package.
"""

__version__ = "0.1.0"

# The challenge's prescribed package name shadows Python's standard-library
# code module. pdb (and pytest) still require its public console API.
import importlib.util as _importlib_util
from pathlib import Path as _Path
import sysconfig as _sysconfig

_spec = _importlib_util.spec_from_file_location(
    "_buy_or_wait_stdlib_code", _Path(_sysconfig.get_path("stdlib")) / "code.py"
)
_stdlib_code = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_stdlib_code)
InteractiveInterpreter = _stdlib_code.InteractiveInterpreter
InteractiveConsole = _stdlib_code.InteractiveConsole
interact = _stdlib_code.interact
compile_command = _stdlib_code.compile_command
