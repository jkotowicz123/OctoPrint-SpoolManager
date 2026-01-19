# coding=utf-8
from __future__ import absolute_import

from peewee import CharField, IntegerField, TextField, ForeignKeyField

from octoprint_SpoolManager.models.BaseModel import BaseModel
from octoprint_SpoolManager.models.SheetTypeModel import SheetTypeModel


def _create_printer_number_field():
	try:
		return IntegerField(null=True, column_name="printerNumber", index=True)
	except TypeError:
		return IntegerField(null=True, db_column="printerNumber", index=True)


def _create_magazine_position_field():
	try:
		return IntegerField(null=True, column_name="magazinePosition", index=True)
	except TypeError:
		return IntegerField(null=True, db_column="magazinePosition", index=True)


class SheetModel(BaseModel):

	nid = CharField(null=False, unique=True, index=True)
	sheetType = ForeignKeyField(SheetTypeModel, null=False, backref="sheets")
	note = TextField(null=True)
	compatibleMaterials = TextField(null=True)
	currentlyPrinting = TextField(null=True)

	printerNumber = _create_printer_number_field()
	magazinePosition = _create_magazine_position_field()
