"""A machine learning framework using the equinox library for learning XC functionals with JAX."""

# Add imports here
from .xcequinox import *


from ._version import __version__

from . import _version
__version__ = _version.get_versions()['version']
