# coding=utf-8
from __future__ import absolute_import

from peewee import ForeignKeyField, IntegerField

from octoprint_SpoolManager.models.BaseModel import BaseModel
from octoprint_SpoolManager.models.ConsumableTypeModel import ConsumableTypeModel


class ConsumableStockModel(BaseModel):

	consumableType = ForeignKeyField(ConsumableTypeModel, null=False, backref="stock", unique=True, on_delete="CASCADE")
	count = IntegerField(null=True)
	ordered = IntegerField(null=True)

	class Meta:
		table_name = "spo_consumable_stock"
