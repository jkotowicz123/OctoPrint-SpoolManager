# coding=utf-8
from __future__ import absolute_import


def remaining_metadata_length(total_length, committed_length):
	"""Return the unassigned part of slicer metadata after earlier checkpoints."""
	try:
		total = float(total_length)
	except (TypeError, ValueError):
		return None
	try:
		committed = max(0.0, float(committed_length or 0.0))
	except (TypeError, ValueError):
		committed = 0.0
	return max(0.0, total - committed)
