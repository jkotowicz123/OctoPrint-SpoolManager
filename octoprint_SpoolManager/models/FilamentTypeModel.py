# coding=utf-8
from __future__ import absolute_import

import json

from peewee import CharField, IntegerField, TextField

from octoprint_SpoolManager.models.BaseModel import BaseModel


class FilamentTypeModel(BaseModel):

	name = CharField(null=False, unique=True, index=True)
	slotCount = IntegerField(null=True)
	items = TextField(null=True)

	class Meta:
		table_name = "spo_filament_types"

	def getItems(self):
		if self.items == None:
			return None
		try:
			return json.loads(self.items)
		except Exception:
			return None
