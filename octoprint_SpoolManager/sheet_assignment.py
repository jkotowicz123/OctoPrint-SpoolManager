def should_refresh_currently_printing(local_printer_number, assigned_printer_number, is_printing, is_paused):
	try:
		if int(local_printer_number) != int(assigned_printer_number):
			return False
	except (TypeError, ValueError):
		return False
	return bool(is_printing or is_paused)
