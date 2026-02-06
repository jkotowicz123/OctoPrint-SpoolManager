# coding=utf-8
from __future__ import absolute_import

from peewee import CharField, FloatField, IntegerField

from octoprint_SpoolManager.models.BaseModel import BaseModel


class ConsumableTypeModel(BaseModel):

	barcode = CharField(null=True, unique=True, index=True)
	category = CharField(null=True, index=True)
	packUnitsLabel = CharField(null=True)
	packUnits = IntegerField(null=True)
	packPriceGross = FloatField(null=True)
	productCode = CharField(null=True, index=True)
	name = CharField(null=True, index=True)
	unitPrice = FloatField(null=True)

	class Meta:
		table_name = "spo_consumable_types"
