"""مرحلة التخطيط المعماري — turning a brief into a space program."""

from .ai import build_program as build_program_ai
from .rules import build_program as build_program_rules
from .rules import normalise_program

__all__ = ["build_program_ai", "build_program_rules", "normalise_program"]
