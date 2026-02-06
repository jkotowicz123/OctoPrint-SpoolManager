# coding=utf-8
from __future__ import absolute_import

import csv
import os
import re
import unicodedata


def _normalize_header(value):
	text = (value or "").strip()
	text = text.replace(u"ł", "l").replace(u"Ł", "L")
	text = unicodedata.normalize("NFKD", text)
	text = "".join(ch for ch in text if not unicodedata.combining(ch))
	return "".join(ch.lower() for ch in text if ch.isalnum())


_HEADER_ALIASES = {
	"barcode": {"barcode", "ean", "gtin", "code"},
	"category": {"category", "type", "group", "kategoria", "typ", "grupa"},
	"pack_units_label": {"packunitslabel", "unit", "unitlabel", "unitslabel"},
	"pack_units": {"packcount", "packunits", "packquantity", "packqty", "sztwkomplecie"},
	"pack_price_gross": {"price", "packprice", "packpricegross", "packcost", "cenapaczkibrutto"},
	"product_code": {"productcode", "sku", "product", "productid", "kodproduktu"},
	"name": {"name", "size", "description", "productname", "produkt"},
	"unit_price": {"priceperunit", "unitprice", "unitcost", "cenaszt"},
	"count": {"count", "stock", "qty", "quantity"},
	"ordered": {"ordered", "onorder", "order", "zamowione"},
}


def _build_header_map(headers):
	normalized_to_original = {}
	for h in headers:
		n = _normalize_header(h)
		if n and n not in normalized_to_original:
			normalized_to_original[n] = h

	result = {}
	for logical_key, aliases in _HEADER_ALIASES.items():
		for alias in aliases:
			if alias in normalized_to_original:
				result[logical_key] = normalized_to_original[alias]
				break
	return result


def _parse_int(value):
	if value is None:
		return None
	v = str(value).strip()
	if v == "":
		return None
	m = re.search(r"[-+]?\d+", v)
	if not m:
		return None
	return int(m.group(0))


def _parse_float(value):
	if value is None:
		return None
	v = str(value).strip()
	if v == "":
		return None
	v = v.replace(u"\xa0", " ").replace(" ", "")
	m = re.search(r"[-+]?\d+(?:[\.,]\d+)?", v)
	if not m:
		return None
	n = m.group(0).replace(",", ".")
	return float(n)


def _parse_pack_units_label(value):
	if value is None:
		return None
	v = str(value).replace(u"\xa0", " ").strip()
	if v == "":
		return None
	m = re.search(r"\d+\s*([^\d\s]+)", v)
	if not m:
		return None
	label = m.group(1).strip()
	return label if label != "" else None


def _get_value(row, header_map, key):
	header = header_map.get(key)
	if not header:
		return None
	val = row.get(header)
	if val is None:
		return None
	val = str(val).replace(u"\xa0", " ").strip()
	return val if val != "" else None


def parseConsumablesCSV(csvFilePath, updateParsingStatus, errorCollection, logger, deleteAfterParsing=True):
	result = []
	lineNumber = 0
	try:
		with open(csvFilePath, "r", encoding="utf-8", newline="") as f:
			sample = f.read(4096)
			f.seek(0)
			try:
				delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
			except Exception:
				delimiter = ";"

			reader = csv.DictReader(f, delimiter=delimiter)
			if reader.fieldnames is None:
				errorCollection.append("CSV has no header row")
				return result

			header_map = _build_header_map(reader.fieldnames)
			if "barcode" not in header_map and "product_code" not in header_map and "name" not in header_map:
				errorCollection.append("CSV header must contain at least one identifier column: barcode, product code, or name")
				return result

			for row in reader:
				lineNumber += 1
				updateParsingStatus(str(lineNumber))

				barcode = _get_value(row, header_map, "barcode")
				product_code = _get_value(row, header_map, "product_code")
				name = _get_value(row, header_map, "name")

				if not barcode and not product_code and not name:
					continue

				pack_units_raw = _get_value(row, header_map, "pack_units")
				pack_units = _parse_int(pack_units_raw)
				pack_units_label = _get_value(row, header_map, "pack_units_label") or _parse_pack_units_label(pack_units_raw)
				pack_price_gross = _parse_float(_get_value(row, header_map, "pack_price_gross"))
				unit_price = _parse_float(_get_value(row, header_map, "unit_price"))
				count = _parse_int(_get_value(row, header_map, "count"))
				ordered = _parse_int(_get_value(row, header_map, "ordered"))

				if unit_price is None and pack_price_gross is not None and pack_units is not None and pack_units != 0:
					unit_price = pack_price_gross / float(pack_units)

				category = _get_value(row, header_map, "category")

				result.append({
					"barcode": barcode,
					"category": category,
					"productCode": product_code,
					"name": name,
					"packUnitsLabel": pack_units_label,
					"packUnits": pack_units,
					"packPriceGross": pack_price_gross,
					"unitPrice": unit_price,
					"count": count,
					"ordered": ordered
				})

	except Exception as e:
		errorMessage = "CSV Parsing error. Line:'" + str(lineNumber) + "' Error:'" + str(e) + "' File:'" + csvFilePath + "'"
		errorCollection.append(errorMessage)
		if logger:
			logger.error(errorMessage)
	finally:
		if deleteAfterParsing:
			if logger:
				logger.info("Removing uploaded csv temp-file")
			try:
				os.remove(csvFilePath)
			except Exception:
				pass
	return result
