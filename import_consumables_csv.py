# coding=utf-8
from __future__ import absolute_import

import argparse
import csv
import logging
import os
import re
import sys
import types
import unicodedata
from typing import Any, Dict, Iterable, Optional, Tuple

from peewee import PostgresqlDatabase


def _normalize_header(value: str) -> str:
	text = (value or "").strip()
	text = text.replace("ł", "l").replace("Ł", "L")
	text = unicodedata.normalize("NFKD", text)
	text = "".join(ch for ch in text if not unicodedata.combining(ch))
	return "".join(ch.lower() for ch in text if ch.isalnum())


def _bootstrap_octoprint_spoolmanager_package() -> None:
	if "octoprint_SpoolManager" in sys.modules:
		return

	repo_root = os.path.dirname(os.path.abspath(__file__))
	pkg_path = os.path.join(repo_root, "octoprint_SpoolManager")
	if not os.path.isdir(pkg_path):
		return

	pkg = types.ModuleType("octoprint_SpoolManager")
	pkg.__path__ = [pkg_path]
	sys.modules["octoprint_SpoolManager"] = pkg


_HEADER_ALIASES = {
	"barcode": {"barcode", "ean", "gtin", "code"},
	"pack_units_label": {"packunitslabel", "unit", "unitlabel", "unitslabel"},
	"pack_units": {"packcount", "packunits", "packquantity", "packqty", "sztwkomplecie"},
	"pack_price_gross": {"price", "packprice", "packpricegross", "packcost", "cenapaczkibrutto"},
	"product_code": {"productcode", "sku", "product", "productid", "kodproduktu"},
	"name": {"name", "size", "description", "productname", "produkt"},
	"unit_price": {"priceperunit", "unitprice", "unitcost", "cenaszt"},
	"count": {"count", "stock", "qty", "quantity"},
	"ordered": {"ordered", "onorder", "order", "zamowione"},
}


def _build_header_map(headers: Iterable[str]) -> Dict[str, str]:
	normalized_to_original: Dict[str, str] = {}
	for h in headers:
		n = _normalize_header(h)
		if n and n not in normalized_to_original:
			normalized_to_original[n] = h

	result: Dict[str, str] = {}
	for logical_key, aliases in _HEADER_ALIASES.items():
		for alias in aliases:
			if alias in normalized_to_original:
				result[logical_key] = normalized_to_original[alias]
				break
	return result


def _parse_int(value: Optional[str]) -> Optional[int]:
	if value is None:
		return None
	v = str(value).strip()
	if v == "":
		return None
	m = re.search(r"[-+]?\d+", v)
	if not m:
		return None
	return int(m.group(0))


def _parse_float(value: Optional[str]) -> Optional[float]:
	if value is None:
		return None
	v = str(value).strip()
	if v == "":
		return None
	v = v.replace("\xa0", " ")
	v = v.replace(" ", "")
	m = re.search(r"[-+]?\d+(?:[\.,]\d+)?", v)
	if not m:
		return None
	n = m.group(0).replace(",", ".")
	return float(n)


def _parse_pack_units_label(value: Optional[str]) -> Optional[str]:
	if value is None:
		return None
	v = str(value).replace("\xa0", " ").strip()
	if v == "":
		return None
	m = re.search(r"\d+\s*([^\d\s]+)", v)
	if not m:
		return None
	label = m.group(1).strip()
	return label if label != "" else None


def _get_value(row: Dict[str, Any], header_map: Dict[str, str], key: str) -> Optional[str]:
	header = header_map.get(key)
	if not header:
		return None
	val = row.get(header)
	if val is None:
		return None
	val = str(val).replace("\xa0", " ").strip()
	return val if val != "" else None


def _connect_postgres(args: argparse.Namespace, models: Iterable[Any]) -> PostgresqlDatabase:
	database = PostgresqlDatabase(
		args.db,
		user=args.user,
		password=args.password,
		host=args.host,
		port=int(args.port),
	)
	database.bind(list(models))
	database.connect()
	return database


def _compute_unit_price(pack_price_gross: Optional[float], pack_units: Optional[int]) -> Optional[float]:
	if pack_price_gross is None or pack_units is None or pack_units == 0:
		return None
	return pack_price_gross / float(pack_units)


def _upsert_consumable(
	*,
	ConsumableTypeModelClass: Any,
	ConsumableStockModelClass: Any,
	originator: Optional[str],
	barcode: Optional[str],
	pack_units_label: Optional[str],
	pack_units: Optional[int],
	pack_price_gross: Optional[float],
	product_code: Optional[str],
	name: Optional[str],
	unit_price: Optional[float],
	count: Optional[int],
	ordered: Optional[int],
	dry_run: bool,
	logger: logging.Logger,
) -> Tuple[bool, bool]:
	created_type = False
	created_stock = False

	ct = None
	if barcode:
		ct = ConsumableTypeModelClass.get_or_none(ConsumableTypeModelClass.barcode == barcode)
		if ct is None and product_code:
			ct = (
				ConsumableTypeModelClass.select()
				.where(ConsumableTypeModelClass.productCode == product_code)
				.first()
			)
		if ct is None and name:
			ct = (
				ConsumableTypeModelClass.select()
				.where(ConsumableTypeModelClass.name == name)
				.first()
			)
	elif product_code:
		ct = (
			ConsumableTypeModelClass.select()
			.where(ConsumableTypeModelClass.productCode == product_code)
			.first()
		)
		if ct is None and name:
			ct = (
				ConsumableTypeModelClass.select()
				.where(ConsumableTypeModelClass.name == name)
				.first()
			)
	elif name:
		ct = (
			ConsumableTypeModelClass.select()
			.where(ConsumableTypeModelClass.name == name)
			.first()
		)

	if ct is None:
		created_type = True
		ct = ConsumableTypeModelClass(barcode=barcode)
		if originator is not None:
			ct.originator = originator
	else:
		if barcode is not None:
			ct.barcode = barcode

	if pack_units_label is not None:
		ct.packUnitsLabel = pack_units_label
	if pack_units is not None:
		ct.packUnits = pack_units
	if pack_price_gross is not None:
		ct.packPriceGross = pack_price_gross
	if product_code is not None:
		ct.productCode = product_code
	if name is not None:
		ct.name = name
	if unit_price is not None:
		ct.unitPrice = unit_price

	if dry_run and created_type:
		created_stock = True
		logger.info("[dry-run] barcode=%s type=create stock=create", barcode)
		return created_type, created_stock

	if not dry_run:
		ct.save(force_insert=created_type)

	s = ConsumableStockModelClass.get_or_none(ConsumableStockModelClass.consumableType == ct)
	if s is None:
		created_stock = True
		s = ConsumableStockModelClass(consumableType=ct)
		if originator is not None:
			s.originator = originator

	if count is not None:
		s.count = count
	if ordered is not None:
		s.ordered = ordered

	if not dry_run:
		s.save(force_insert=created_stock)

	if dry_run:
		logger.info(
			"[dry-run] barcode=%s type=%s stock=%s",
			barcode,
			"create" if created_type else "update",
			"create" if created_stock else "update",
		)

	return created_type, created_stock


def main(argv: Optional[Iterable[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Import consumables from CSV into SpoolManager tables")
	parser.add_argument("csv", help="Path to CSV file")
	parser.add_argument("--host", required=True)
	parser.add_argument("--port", default=5432)
	parser.add_argument("--db", required=True, help="Database name")
	parser.add_argument("--user", required=True)
	parser.add_argument("--password", default=os.environ.get("PGPASSWORD", ""))
	parser.add_argument("--originator", default="csv_import")
	parser.add_argument("--default-pack-units-label", default=None)
	parser.add_argument("--barcode-from-product-code-if-missing", action="store_true")
	parser.add_argument("--delimiter", default=None)
	parser.add_argument("--encoding", default="utf-8")
	parser.add_argument("--commit", action="store_true", help="Actually write changes to the DB")
	parser.add_argument("--create-tables", action="store_true", help="Create consumables tables if missing")

	args = parser.parse_args(list(argv) if argv is not None else None)

	logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
	logger = logging.getLogger("import_consumables_csv")
	if not args.commit:
		logger.info("Running in dry-run mode (no DB writes). Use --commit to apply changes.")

	if not os.path.exists(args.csv):
		logger.error("CSV file not found: %s", args.csv)
		return 2

	database: Optional[PostgresqlDatabase] = None
	try:
		_bootstrap_octoprint_spoolmanager_package()
		from octoprint_SpoolManager.DatabaseManager import MODELS
		from octoprint_SpoolManager.models.ConsumableStockModel import ConsumableStockModel
		from octoprint_SpoolManager.models.ConsumableTypeModel import ConsumableTypeModel

		database = _connect_postgres(args, MODELS)

		if args.create_tables:
			try:
				database.create_tables([ConsumableTypeModel, ConsumableStockModel])
			except Exception:
				pass

		created_types = 0
		updated_types = 0
		created_stock = 0
		updated_stock = 0
		skipped = 0

		with open(args.csv, "r", encoding=args.encoding, newline="") as f:
			delimiter = args.delimiter
			if delimiter is None:
				sample = f.read(4096)
				f.seek(0)
				try:
					delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
				except Exception:
					delimiter = ";"
			reader = csv.DictReader(f, delimiter=delimiter)
			if reader.fieldnames is None:
				logger.error("CSV has no header row")
				return 2

			header_map = _build_header_map(reader.fieldnames)
			if "barcode" not in header_map and "product_code" not in header_map and "name" not in header_map:
				logger.error("CSV header must contain at least one identifier column: barcode or product code or name")
				return 2

			for idx, row in enumerate(reader, start=2):
				barcode = _get_value(row, header_map, "barcode")
				product_code = _get_value(row, header_map, "product_code")
				name = _get_value(row, header_map, "name")
				if not barcode and args.barcode_from_product_code_if_missing and product_code:
					barcode = product_code
				if not barcode and not product_code and not name:
					skipped += 1
					logger.info("Skipping line %s (missing identifier)", idx)
					continue

				pack_units_raw = _get_value(row, header_map, "pack_units")
				pack_units = _parse_int(pack_units_raw)
				pack_units_label = _get_value(row, header_map, "pack_units_label") or _parse_pack_units_label(pack_units_raw) or args.default_pack_units_label
				pack_price_gross = _parse_float(_get_value(row, header_map, "pack_price_gross"))
				unit_price = _parse_float(_get_value(row, header_map, "unit_price"))
				count = _parse_int(_get_value(row, header_map, "count"))
				ordered = _parse_int(_get_value(row, header_map, "ordered"))

				if unit_price is None:
					unit_price = _compute_unit_price(pack_price_gross, pack_units)

				with database.atomic():
					created_t, created_s = _upsert_consumable(
						ConsumableTypeModelClass=ConsumableTypeModel,
						ConsumableStockModelClass=ConsumableStockModel,
						originator=args.originator,
						barcode=barcode,
						pack_units_label=pack_units_label,
						pack_units=pack_units,
						pack_price_gross=pack_price_gross,
						product_code=product_code,
						name=name,
						unit_price=unit_price,
						count=count,
						ordered=ordered,
						dry_run=not args.commit,
						logger=logger,
					)

				if created_t:
					created_types += 1
				else:
					updated_types += 1
				if created_s:
					created_stock += 1
				else:
					updated_stock += 1

		logger.info("Done.")
		logger.info("Types: created=%s updated=%s", created_types, updated_types)
		logger.info("Stock: created=%s updated=%s", created_stock, updated_stock)
		logger.info("Skipped=%s", skipped)
		return 0
	finally:
		if database is not None:
			try:
				database.close()
			except Exception:
				pass


if __name__ == "__main__":
	raise SystemExit(main())
