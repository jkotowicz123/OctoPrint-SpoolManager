# coding=utf-8
from __future__ import absolute_import

from peewee import CharField, TextField

from octoprint_SpoolManager.models.BaseModel import BaseModel


class SheetTypeModel(BaseModel):

	name = CharField(null=False, unique=True, index=True)
	compatibleMaterials = TextField(null=True)
