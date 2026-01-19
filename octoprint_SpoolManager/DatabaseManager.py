# coding=utf-8
from __future__ import absolute_import

import datetime
import json
import os
import logging
import shutil
import sqlite3
import uuid

from octoprint_SpoolManager.WrappedLoggingHandler import WrappedLoggingHandler
from peewee import *
from playhouse.shortcuts import model_to_dict, dict_to_model

from octoprint_SpoolManager.api import Transformer
from octoprint_SpoolManager.common import StringUtils
from octoprint_SpoolManager.models.BaseModel import BaseModel
from octoprint_SpoolManager.models.PluginMetaDataModel import PluginMetaDataModel
from octoprint_SpoolManager.models.SpoolModel import SpoolModel
from octoprint_SpoolManager.models.FilamentTypeModel import FilamentTypeModel
from octoprint_SpoolManager.models.SheetTypeModel import SheetTypeModel
from octoprint_SpoolManager.models.SheetModel import SheetModel

# from octoprint_SpoolManager.models.MaterialModel import MaterialModel
# from octoprint_SpoolManager.models.MaterialCharacteristicModel import MaterialCharacteristicModel

FORCE_CREATE_TABLES = False

CURRENT_DATABASE_SCHEME_VERSION = 11

# List all Models
MODELS = [PluginMetaDataModel, SpoolModel, FilamentTypeModel, SheetTypeModel, SheetModel]

class DatabaseManager(object):

	class DatabaseSettings:
		# Internal stuff
		baseFolder = ""
		fileLocation = ""
		# External stuff
		useExternal = False
		type = "postgresql" # postgresql,  mysql NOT sqlite
		name = ""
		host = ""
		port = 0
		user = ""
		password = ""

		def __str__(self):
			return str(self.__dict__)

	def __init__(self, parentLogger, sqlLoggingEnabled):
		self.sqlLoggingEnabled = sqlLoggingEnabled
		self._logger = logging.getLogger(parentLogger.name + "." + self.__class__.__name__)
		self._sqlLogger = logging.getLogger(parentLogger.name + "." + self.__class__.__name__ + ".SQL")

		self._database = None
		self._databseSettings = None
		self._sendDataToClient = None
		self._isConnected = False
		self._currentErrorMessageDict = None

	################################################################################################## private functions
	# "databaseSettings"] = {
	# "type": "postgres",
	# "host": "localhost",
	# "port": 5432,
	# "databaseName": "SpoolManagerDatabase",
	# "user": "Olli",
	# "password": "illO"

	def _buildDatabaseConnection(self):
		database = None
		if (self._databaseSettings.useExternal == False):
			# local database`
			database = SqliteDatabase(self._databaseSettings.fileLocation)
		else:
			databaseType = self._databaseSettings.type
			databaseName = self._databaseSettings.name
			host = self._databaseSettings.host
			port = int(self._databaseSettings.port)
			user = self._databaseSettings.user
			password = self._databaseSettings.password
			if ("postgres" == databaseType):
				# Connect to a Postgres database.
				database = PostgresqlDatabase(databaseName,
												   	user=user,
												   	password=password,
										   		   	host=host,
												   	port=port)
			else:
				# Connect to a MySQL database on network.
				database = MySQLDatabase(databaseName,
											   user=user,
											   password=password,
											   host=host,
											   port=port)

		return database

	def _createDatabase(self, forceCreateTables):

		if forceCreateTables:
			self._logger.info("Creating new database-tables, because FORCE == TRUE!")
			self._createDatabaseTables()
		else:
			# check, if we need an scheme upgrade
			self._createOrUpgradeSchemeIfNecessary()

		self._logger.info("Database created-check done")

	def _createOrUpgradeSchemeIfNecessary(self):

		self._logger.info("Check if database-scheme upgrade needed...")
		schemeVersionFromDatabaseModel = None
		schemeVersionFromDatabase = None
		try:
			cursor = PluginMetaDataModel.get(PluginMetaDataModel.key == PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION)
			result = cursor.value
			if (result != None):
				try:
					schemeVersionFromDatabase = int(result)
				except Exception:
					schemeVersionFromDatabase = int(result[0])
				self._logger.info("Current databasescheme: " + str(schemeVersionFromDatabase))
			else:
				self._logger.warn("Strange, table is found (maybe), but there is no result of the schem version. Try to recreate a new db-scheme")
				self.backupDatabaseFile() # safty first
				self._createDatabaseTables()
				return
			pass
		except Exception as e:
			self._logger.exception(e)
			self.closeDatabase()
			errorMessage = str(e)
			if (
				# - SQLLite
				errorMessage.startswith("no such table") or
				# - Postgres
				"does not exist" in errorMessage or
				# - mySQL errorcode=1146
				"doesn\'t exist" in errorMessage
			):
				self._createDatabaseTables()
				return
			else:
				self._logger.error(str(e))

		if not schemeVersionFromDatabase == None:
			currentDatabaseSchemeVersion = schemeVersionFromDatabase
			if (currentDatabaseSchemeVersion < CURRENT_DATABASE_SCHEME_VERSION):
				# auto upgrade done only for local database
				if (self._databaseSettings.useExternal == True):
					self._logger.warn("Scheme upgrade is only done for local database")
				else:
					# evautate upgrade steps (from 1-2 , 1...6)
					self._logger.info("We need to upgrade the database scheme from: '" + str(currentDatabaseSchemeVersion) + "' to: '" + str(CURRENT_DATABASE_SCHEME_VERSION) + "'")

					try:
						self.backupDatabaseFile()
						self._upgradeDatabase(currentDatabaseSchemeVersion, CURRENT_DATABASE_SCHEME_VERSION)
					except Exception as e:
						self._logger.error("Error during database upgrade!!!!")
						self._logger.exception(e)
						return
					self._logger.info("...Database-scheme successfully upgraded.")
			else:
				self._logger.info("...Database-scheme upgraded not needed.")
		else:
			self._logger.warn("...something was strange. Should not be shwon in log. Check full log")

		self._ensureSheetTablesExist()
		self._ensureFilamentTypesTableExists()
		pass

	def _ensureFilamentTypesTableExists(self):
		try:
			self._database.connect(reuse_if_open=True)
			self._database.create_tables([FilamentTypeModel], safe=True)
			self._seedFilamentTypes()
		except Exception as e:
			self._logger.exception("Could not ensure filament types exist: " + str(e))

	def _ensureSheetTablesExist(self):
		try:
			self._database.connect(reuse_if_open=True)
			self._database.create_tables([SheetTypeModel, SheetModel], safe=True)
			self._ensureSheetTypeCompatibleMaterialsColumnExists()
			self._ensureSheetCurrentlyPrintingColumnExists()
			self._seedDefaultSheets()
			self._normalizeSheetTypeNames()
			self._syncSheetNidsToDatabaseIds()
			self._syncSheetCompatibleMaterialsFromType()
		except Exception as e:
			self._logger.exception("Could not ensure sheet tables exist: " + str(e))

	def _ensureSheetTypeCompatibleMaterialsColumnExists(self):
		try:
			if (self._databaseSettings.useExternal == False):
				connection = sqlite3.connect(self._databaseSettings.fileLocation)
				cursor = connection.cursor()

				columns = []
				try:
					cursor.execute("PRAGMA table_info('spo_sheettypemodel')")
					columns = [row[1] for row in cursor.fetchall()]
				except Exception:
					columns = []

				if ("compatibleMaterials" not in columns):
					self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_sheettypemodel' ADD 'compatibleMaterials' TEXT")
				connection.close()
				return

			databaseType = self._databaseSettings.type
			if ("postgres" == databaseType):
				self._database.execute_sql('ALTER TABLE "spo_sheettypemodel" ADD COLUMN IF NOT EXISTS "compatibleMaterials" TEXT')
			else:
				try:
					self._database.execute_sql("ALTER TABLE `spo_sheettypemodel` ADD COLUMN `compatibleMaterials` TEXT")
				except Exception:
					self._database.execute_sql("ALTER TABLE spo_sheettypemodel ADD COLUMN compatibleMaterials TEXT")
		except Exception as e:
			self._logger.exception("Could not ensure sheet type compatibleMaterials column exists: " + str(e))

	def _ensureSheetCurrentlyPrintingColumnExists(self):
		try:
			if (self._databaseSettings.useExternal == False):
				connection = sqlite3.connect(self._databaseSettings.fileLocation)
				cursor = connection.cursor()

				columns = []
				try:
					cursor.execute("PRAGMA table_info('spo_sheetmodel')")
					columns = [row[1] for row in cursor.fetchall()]
				except Exception:
					columns = []

				if ("currentlyPrinting" not in columns):
					self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_sheetmodel' ADD 'currentlyPrinting' TEXT")
				connection.close()
				return

			databaseType = self._databaseSettings.type
			if ("postgres" == databaseType):
				self._database.execute_sql('ALTER TABLE "spo_sheetmodel" ADD COLUMN IF NOT EXISTS "currentlyPrinting" TEXT')
			else:
				try:
					self._database.execute_sql("ALTER TABLE `spo_sheetmodel` ADD COLUMN `currentlyPrinting` TEXT")
				except Exception:
					self._database.execute_sql("ALTER TABLE spo_sheetmodel ADD COLUMN currentlyPrinting TEXT")
		except Exception as e:
			self._logger.exception("Could not ensure sheet currentlyPrinting column exists: " + str(e))

	def _syncSheetNidsToDatabaseIds(self):
		try:
			SheetModel.update({SheetModel.nid: SheetModel.databaseId}).execute()
		except Exception as e:
			self._logger.exception("Could not sync sheet NIDs: " + str(e))

	def _syncSheetCompatibleMaterialsFromType(self):
		try:
			allTypes = SheetTypeModel.select()
			for t in allTypes:
				cm = None
				try:
					cm = t.compatibleMaterials
				except Exception:
					cm = None
				if (cm == None or str(cm).strip() == ""):
					continue
				SheetModel.update({SheetModel.compatibleMaterials: cm}).where(
					(SheetModel.sheetType == t) &
					(
						(SheetModel.compatibleMaterials.is_null(True)) |
						(SheetModel.compatibleMaterials == "")
					)
				).execute()
		except Exception as e:
			self._logger.exception("Could not sync sheet compatibleMaterials: " + str(e))

	def _normalizeSheetTypeNames(self):
		try:
			canonical = SheetTypeModel.get_or_none(SheetTypeModel.name == "Satin")
			lowercase = SheetTypeModel.get_or_none(fn.Lower(SheetTypeModel.name) == "satin")
			if (lowercase == None):
				return
			if (canonical == None):
				lowercase.name = "Satin"
				lowercase.save()
				return
			if (canonical.databaseId == lowercase.databaseId):
				return
			SheetModel.update({SheetModel.sheetType: canonical}).where(SheetModel.sheetType == lowercase).execute()
			lowercase.delete_instance()
		except Exception as e:
			self._logger.exception("Could not normalize sheet type names: " + str(e))

	def _seedDefaultSheets(self):
		sheetTypeNames = ["Textured", "Smooth", "Satin", "Nylon"]
		defaultCompatibleMaterials = json.dumps(["PLA", "PETG", "SILK", "FLEX", "PA"], ensure_ascii=False)
		defaultTypeCompatibleMaterials = {
			"Textured": defaultCompatibleMaterials,
			"Smooth": defaultCompatibleMaterials,
			"Satin": defaultCompatibleMaterials,
			"Nylon": defaultCompatibleMaterials
		}
		sheetTypesByName = {}
		for name in sheetTypeNames:
			model, _created = SheetTypeModel.get_or_create(name=name)
			try:
				if (model.compatibleMaterials == None or str(model.compatibleMaterials).strip() == ""):
					model.compatibleMaterials = defaultTypeCompatibleMaterials.get(name)
					model.save()
			except Exception:
				pass
			sheetTypesByName[name] = model

		try:
			if (self._databaseSettings.useExternal):
				return
		except Exception:
			pass

		try:
			if (SheetModel.select().count() > 0):
				return
		except Exception:
			pass

		rows = [
			{"pos": 1, "type": "Textured", "series": "BP-24", "sn": "", "note": ""},
			{"pos": 2, "type": "Textured", "series": "BP-24", "sn": "", "note": ""},
			{"pos": 3, "type": "Textured", "series": "MD-28", "sn": "", "note": ""},
			{"pos": 4, "type": "Textured", "series": "BH-25", "sn": "", "note": u"Stara, z oderwaną powłoką na środku po obu stronach"},
			{"pos": 5, "type": "Textured", "series": "BP-24", "sn": "SN-11397-028614", "note": ""},
			{"pos": 6, "type": "Textured", "series": "", "sn": "", "note": ""},
			{"pos": 7, "type": "Textured", "series": "", "sn": "", "note": ""},
			{"pos": 8, "type": "Textured", "series": "", "sn": "", "note": ""},
			{"pos": 9, "type": "Textured", "series": "", "sn": "", "note": ""},
			{"pos": 10, "type": "Textured", "series": "", "sn": "", "note": ""},
			{"pos": 11, "type": "Textured", "series": "", "sn": "", "note": ""},

			{"pos": 1, "type": "Smooth", "series": "IT-22", "sn": "", "note": ""},
			{"pos": 2, "type": "Smooth", "series": "TF-21", "sn": "", "note": u"Stara, porysowana z jednej strony i wgnieciona z drugiej"},
			{"pos": 3, "type": "Smooth", "series": "PD-24", "sn": "", "note": ""},
			{"pos": 4, "type": "Smooth", "series": "IT-22", "sn": "", "note": ""},
			{"pos": 5, "type": "Smooth", "series": "DB-23", "sn": "", "note": ""},
			{"pos": 6, "type": "Smooth", "series": "PD-24", "sn": "", "note": ""},
			{"pos": 7, "type": "Smooth", "series": "", "sn": "", "note": ""},
			{"pos": 8, "type": "Smooth", "series": "", "sn": "", "note": ""},
			{"pos": 9, "type": "Smooth", "series": "", "sn": "", "note": ""},
			{"pos": 10, "type": "Smooth", "series": "", "sn": "", "note": ""},
			{"pos": 11, "type": "Smooth", "series": "", "sn": "", "note": ""},

			{"pos": 1, "type": "Satin", "series": "VT-24", "sn": "", "note": ""},
			{"pos": 2, "type": "Satin", "series": "VT-24", "sn": "", "note": ""},
			{"pos": 3, "type": "Satin", "series": "VT-24", "sn": "", "note": ""},
			{"pos": 4, "type": "Satin", "series": "VT-24", "sn": "", "note": ""},
			{"pos": 5, "type": "Satin", "series": "LT-11", "sn": "", "note": u"Porysowana na środku"},
			{"pos": 6, "type": "Satin", "series": "VT-24", "sn": "", "note": ""},
			{"pos": 7, "type": "Satin", "series": "MB-23", "sn": "", "note": ""},
			{"pos": 8, "type": "Satin", "series": "VT-24", "sn": "", "note": ""},
			{"pos": 9, "type": "Satin", "series": "LT-11", "sn": "", "note": u"„2”, ghost po lustrze na środku"},
			{"pos": 10, "type": "Satin", "series": "MB-23", "sn": "", "note": u"„4”"},
			{"pos": 11, "type": "Satin", "series": "VT-24", "sn": "", "note": ""},

			{"pos": 1, "type": "Nylon", "series": "VS-11", "sn": "", "note": u"Z jednej strony ślady po MBLu z MK4"}
		]

		for r in rows:
			sheetType = sheetTypesByName.get(r.get("type"))
			if (sheetType == None):
				continue

			pos = r.get("pos")
			nid = str(r.get("type")) + "-" + str(pos)

			noteParts = []
			series = (r.get("series") or "").strip()
			if (series != ""):
				noteParts.append("Seria: " + series)
			sn = (r.get("sn") or "").strip()
			if (sn != ""):
				noteParts.append("SN: " + sn)
			n = (r.get("note") or "")
			try:
				n = n.strip()
			except Exception:
				pass
			if (n != ""):
				noteParts.append(n)

			noteText = None
			if (len(noteParts) > 0):
				noteText = " | ".join(noteParts)

			SheetModel.get_or_create(
				nid=nid,
				defaults={
					"sheetType": sheetType,
					"note": noteText,
					"compatibleMaterials": sheetType.compatibleMaterials,
					"printerNumber": None,
					"magazinePosition": None
				}
			)

	def _seedFilamentTypes(self):
		def _row(pos, series, sn, note):
			return {
				"pos": pos,
				"series": series,
				"sn": sn,
				"note": note
			}

		data = {
			"Textured": {
				"slotCount": 11,
				"items": [
					_row(1, "BP-24", "", ""),
					_row(2, "BP-24", "", ""),
					_row(3, "MD-28", "", ""),
					_row(4, "BH-25", "", u"Stara, z oderwaną powłoką na środku po obu stronach"),
					_row(5, "BP-24", "SN-11397-028614", ""),
					_row(6, "", "", ""),
					_row(7, "", "", ""),
					_row(8, "", "", ""),
					_row(9, "", "", ""),
					_row(10, "", "", ""),
					_row(11, "", "", "")
				]
			},
			"Smooth": {
				"slotCount": 11,
				"items": [
					_row(1, "IT-22", "", ""),
					_row(2, "TF-21", "", u"Stara, porysowana z jednej strony i wgnieciona z drugiej"),
					_row(3, "PD-24", "", ""),
					_row(4, "IT-22", "", ""),
					_row(5, "DB-23", "", ""),
					_row(6, "PD-24", "", ""),
					_row(7, "", "", ""),
					_row(8, "", "", ""),
					_row(9, "", "", ""),
					_row(10, "", "", ""),
					_row(11, "", "", "")
				]
			},
			"Satin": {
				"slotCount": 11,
				"items": [
					_row(1, "VT-24", "", ""),
					_row(2, "VT-24", "", ""),
					_row(3, "VT-24", "", ""),
					_row(4, "VT-24", "", ""),
					_row(5, "LT-11", "", u"Porysowana na środku"),
					_row(6, "VT-24", "", ""),
					_row(7, "MB-23", "", ""),
					_row(8, "VT-24", "", ""),
					_row(9, "LT-11", "", u"„2”, ghost po lustrze na środku"),
					_row(10, "MB-23", "", u"„4”"),
					_row(11, "VT-24", "", "")
				]
			},
			"Nylon": {
				"slotCount": 1,
				"items": [
					_row(1, "VS-11", "", u"Z jednej strony ślady po MBLu z MK4")
				]
			}
		}

		for name, payload in data.items():
			model, _created = FilamentTypeModel.get_or_create(name=name)
			model.slotCount = payload.get("slotCount")
			model.items = json.dumps(payload.get("items"), ensure_ascii=False)
			model.save()

	def _upgradeDatabase(self,currentDatabaseSchemeVersion, targetDatabaseSchemeVersion):

		migrationFunctions = [self._upgradeFrom1To2,
							  self._upgradeFrom2To3,
							  self._upgradeFrom3To4,
							  self._upgradeFrom4To5,
							  self._upgradeFrom5To6,
							  self._upgradeFrom6To7,
							  self._upgradeFrom7To8,
							  self._upgradeFrom8To9,
							  self._upgradeFrom9To10
							  ,self._upgradeFrom10To11
							  ]

		for migrationMethodIndex in range(currentDatabaseSchemeVersion -1, targetDatabaseSchemeVersion -1):
			self._logger.info("Database migration from '" + str(migrationMethodIndex + 1) + "' to '" + str(migrationMethodIndex + 2) + "'")
			migrationFunctions[migrationMethodIndex]()
			pass
		pass

	def _upgradeFrom9To10(self):
		self._logger.info(" Starting 9 -> 10")
		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		columns = []
		try:
			cursor.execute("PRAGMA table_info('spo_spoolmodel')")
			columns = [row[1] for row in cursor.fetchall()]
		except Exception:
			columns = []

		if ("printerNumber" not in columns):
			self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_spoolmodel' ADD 'printerNumber' VARCHAR(255)")

		if ("printer" in columns):
			self._executeSQLQuietly(cursor,
				"UPDATE 'spo_spoolmodel' SET printerNumber = printer "
				"WHERE (printerNumber IS NULL OR printerNumber = '') "
				"AND (printer IS NOT NULL AND printer <> '')")

		self._executeSQLQuietly(cursor, "UPDATE 'spo_pluginmetadatamodel' SET value=10 WHERE key='databaseSchemeVersion'")

		connection.close()
		self._logger.info(" Successfully 9 -> 10")

	def _upgradeFrom10To11(self):
		self._logger.info(" Starting 10 -> 11")
		try:
			self._database.connect(reuse_if_open=True)
			self._database.create_tables([SheetTypeModel, SheetModel], safe=True)
		except Exception as e:
			self._logger.exception("Could not create sheet tables during database migration: " + str(e))
		finally:
			try:
				self.closeDatabase()
			except Exception:
				pass

		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()
		self._executeSQLQuietly(cursor, "UPDATE 'spo_pluginmetadatamodel' SET value=11 WHERE key='databaseSchemeVersion'")
		connection.close()
		self._logger.info(" Successfully 10 -> 11")

	def _upgradeFrom8To9(self):
		self._logger.info(" Starting 8 -> 9")
		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_spoolmodel' ADD 'printerNumber' VARCHAR(255)")
		self._executeSQLQuietly(cursor, "UPDATE 'spo_pluginmetadatamodel' SET value=9 WHERE key='databaseSchemeVersion'")

		connection.close()
		self._logger.info(" Successfully 8 -> 9")

	def _upgradeFrom7To8(self):
		self._logger.info(" Starting 7 -> 8")
		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_spoolmodel' ADD 'shelf' VARCHAR(255)")
		self._executeSQLQuietly(cursor, "UPDATE 'spo_pluginmetadatamodel' SET value=8 WHERE key='databaseSchemeVersion'")

		connection.close()
		self._logger.info(" Successfully 7 -> 8")

	def _upgradeFrom6To7(self):
		self._logger.info(" Starting 6 -> 7")
		# What is changed:
		# - Recalculate remaining weight

		self._logger.info("  try to calculate remaining weight.")

		#  Calculate the remaining weight for all current spools
		with self._database.atomic() as transaction:  # Opens new transaction.

			try:
				allSpoolModels = self.loadAllSpoolsByQuery(None)
				if (allSpoolModels != None):
					for spoolModel in allSpoolModels:
						totalWeight = spoolModel.totalWeight
						usedWeight = spoolModel.usedWeight
						remainingWeight = Transformer.calculateRemainingWeight(usedWeight, totalWeight)
						if (remainingWeight != None):
							spoolModel.remainingWeight = remainingWeight
							spoolModel.save()

				localSchemeVersionFromDatabaseModel = PluginMetaDataModel.get(
					PluginMetaDataModel.key == PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION)
				localSchemeVersionFromDatabaseModel.value = "7"
				localSchemeVersionFromDatabaseModel.save()

				# do expicit commit
				transaction.commit()
			except:
				# Because this block of code is wrapped with "atomic", a
				# new transaction will begin automatically after the call
				# to rollback().
				transaction.rollback()
				self._logger.exception("Could not calculate remainingWeight during scheme update from 6 To 7:" )

				return
			pass
		self._logger.info(" Successfully 6 -> 7")



	def _upgradeFrom5To6(self):
		self._logger.info(" Starting 5 -> 6")
		# What is changed:
		# - Recalculate remaining weight
		# - offsetTemperature = IntegerField(null=True)  # since V6
		# - offsetBedTemperature = IntegerField(null=True)  # since V6
		# - offsetEnclosureTemperature = IntegerField(null=True)  # since V6

		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		sql = """
		PRAGMA foreign_keys=off;
		BEGIN TRANSACTION;

			ALTER TABLE 'spo_spoolmodel' ADD 'offsetTemperature' INTEGER;
			ALTER TABLE 'spo_spoolmodel' ADD 'offsetBedTemperature' INTEGER;
			ALTER TABLE 'spo_spoolmodel' ADD 'offsetEnclosureTemperature' INTEGER;

			UPDATE 'spo_pluginmetadatamodel' SET value=6 WHERE key='databaseSchemeVersion';
		COMMIT;
		PRAGMA foreign_keys=on;
		"""
		cursor.executescript(sql)
		connection.close()

		self._logger.info("  try to calculate remaining weight.")
		#  Calculate the remaining weight for all current spools
		with self._database.atomic() as transaction:  # Opens new transaction.
			try:
				allSpoolModels = self.loadAllSpoolsByQuery(None)
				if (allSpoolModels != None):
					for spoolModel in allSpoolModels:
						totalWeight = spoolModel.totalWeight
						usedWeight = spoolModel.usedWeight
						remainingWeight = Transformer.calculateRemainingWeight(usedWeight, totalWeight)
						if (remainingWeight != None):
							spoolModel.remainingWeight = remainingWeight
							spoolModel.save()
				# do expicit commit
				transaction.commit()
			except Exception as e:
				# Because this block of code is wrapped with "atomic", a
				# new transaction will begin automatically after the call
				# to rollback().
				transaction.rollback()
				self._logger.exception("Could not calculate remainingWeight during scheme update from 5 To 6:" + str(e))

				return
			pass

		self._logger.info(" Successfully 5 -> 6")
		pass

	def _upgradeFrom4To5(self):
		self._logger.info(" Starting 4 -> 5")
		# What is changed:
		# SpoolModel (needed, because last script created a new table and altering was already done
		# - materialCharacteristic = CharField(null=True, index=True) # strong, soft,... # since V4: new
		# - material = CharField(null=True, index=True)	# since V4: added index
		# - vendor = CharField(null=True, index=True) # since V4: added index
		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_spoolmodel' ADD 'updated' DATETIME")
		self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_spoolmodel' ADD 'originator' CHAR(60)")
		self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_spoolmodel' ADD 'materialCharacteristic' VARCHAR(255)")
		self._executeSQLQuietly(cursor, "ALTER TABLE 'spo_spoolmodel' ADD 'isActive' INTEGER")
		self._executeSQLQuietly(cursor, "UPDATE 'spo_spoolmodel' SET isActive=1")
		self._executeSQLQuietly(cursor, "CREATE INDEX spoolmodel_materialCharacteristic ON spo_spoolmodel (materialCharacteristic)")
		self._executeSQLQuietly(cursor, "CREATE INDEX spoolmodel_material ON spo_spoolmodel (material)")
		self._executeSQLQuietly(cursor, "CREATE INDEX spoolmodel_vendor ON spo_spoolmodel (vendor)")
		self._executeSQLQuietly(cursor, "CREATE INDEX spoolmodel_project ON spo_spoolmodel (project)")

		self._executeSQLQuietly(cursor, "UPDATE 'spo_pluginmetadatamodel' SET value=5 WHERE key='databaseSchemeVersion'")

		# sql = """
		# PRAGMA foreign_keys=off;
		# BEGIN TRANSACTION;
		#
		# 	ALTER TABLE 'spo_spoolmodel' ADD 'updated' DATETIME;
		# 	ALTER TABLE 'spo_spoolmodel' ADD 'originator' CHAR(60);
		# 	ALTER TABLE 'spo_spoolmodel' ADD 'materialCharacteristic' VARCHAR(255);
		# 	ALTER TABLE 'spo_spoolmodel' ADD 'isActive' INTEGER;
		# 	UPDATE 'spo_spoolmodel' SET isActive=1;
		#
		# 	CREATE INDEX spoolmodel_materialCharacteristic ON spo_spoolmodel (materialCharacteristic);
		# 	CREATE INDEX spoolmodel_material ON spo_spoolmodel (material);
		# 	CREATE INDEX spoolmodel_vendor ON spo_spoolmodel (vendor);
		# 	CREATE INDEX spoolmodel_project ON spo_spoolmodel (project);
		#
		# 	UPDATE 'spo_pluginmetadatamodel' SET value=5 WHERE key='databaseSchemeVersion';
		# COMMIT;
		# PRAGMA foreign_keys=on;
		# """
		# cursor.executescript(sql)

		connection.close()

		self._logger.info(" Successfully 4 -> 5")
		pass

	def _executeSQLQuietly(self, cursor, sqlStatement):
		try:
			cursor.execute(sqlStatement)
		except Exception as e:
			self._logger.error(sqlStatement)
			self._logger.exception(e)

	def _upgradeFrom4To5_HACK(self, sqlStatement):

		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		sql = """
		PRAGMA foreign_keys=off;
		BEGIN TRANSACTION;
		"""

			# ALTER TABLE 'spo_spoolmodel' ADD 'updated' DATETIME;
			# ALTER TABLE 'spo_spoolmodel' ADD 'originator' CHAR(60);
			# ALTER TABLE 'spo_spoolmodel' ADD 'materialCharacteristic' VARCHAR(255);
			# ALTER TABLE 'spo_spoolmodel' ADD 'isActive' INTEGER;
			# UPDATE 'spo_spoolmodel' SET isActive=1;
			#
			# CREATE INDEX spoolmodel_materialCharacteristic ON spo_spoolmodel (materialCharacteristic);
			# CREATE INDEX spoolmodel_material ON spo_spoolmodel (material);
			# CREATE INDEX spoolmodel_vendor ON spo_spoolmodel (vendor);
			#
			# UPDATE 'spo_pluginmetadatamodel' SET value=5 WHERE key='databaseSchemeVersion';

		sql = sql + """
		COMMIT;
		PRAGMA foreign_keys=on;
		"""
		cursor.executescript(sql)

		connection.close()

	def _upgradeFrom3To4(self):
		self._logger.info(" Starting 3 -> 4")
		# What is changed:
		# BaseModel, so add to all tables
		# - updated = DateTimeField(default=datetime.datetime.now)
		# - version = SmallIntegerField(null=True)
		# - originator = FixedCharField(null=True, max_length=60)
		# SpoolModel
		# - materialCharacteristic = CharField(null=True, index=True) # strong, soft,... # since V4: new
		# - material = CharField(null=True, index=True)	# since V4: added index
		# - vendor = CharField(null=True, index=True) # since V4: added index
		# - encloser -> rename to enclosureTemperature
		#               ALTER TABLE spo_spoolmodel RENAME COLUMN encloserTemperature to enclosureTemperature; not working
		#               SQLite did not support the ALTER TABLE RENAME COLUMN syntax before version 3.25.0.
		#               see https://www.sqlitetutorial.net/sqlite-rename-column/#:~:text=SQLite%20did%20not%20support%20the,the%20version%20lower%20than%203.25.
		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		# SCHROTT!!!!! zuerst 'ALTER' und dann eine neue Tabelle erstellen ohne die ALTER-Spalten, SUPER !!!!
		sql = """
		PRAGMA foreign_keys=off;
		BEGIN TRANSACTION;

			ALTER TABLE 'spo_pluginmetadatamodel' ADD 'updated' DATETIME;
			ALTER TABLE 'spo_pluginmetadatamodel' ADD 'version' INTEGER;
			ALTER TABLE 'spo_pluginmetadatamodel' ADD 'originator' CHAR(60);
			UPDATE 'spo_pluginmetadatamodel' SET version=1;

			ALTER TABLE 'spo_spoolmodel' ADD 'updated' DATETIME;
			ALTER TABLE 'spo_spoolmodel' ADD 'originator' CHAR(60);
			ALTER TABLE 'spo_spoolmodel' ADD 'materialCharacteristic' VARCHAR(255);
			ALTER TABLE 'spo_spoolmodel' ADD 'isActive' INTEGER;
			UPDATE 'spo_spoolmodel' SET isActive=1;

			CREATE INDEX spoolmodel_materialCharacteristic ON spo_spoolmodel (materialCharacteristic);
			CREATE INDEX spoolmodel_material ON spo_spoolmodel (material);
			CREATE INDEX spoolmodel_vendor ON spo_spoolmodel (vendor);
			CREATE INDEX spoolmodel_project ON spo_spoolmodel (project);

			ALTER TABLE 'spo_spoolmodel' RENAME TO 'spo_spoolmodel_old';
			CREATE TABLE "spo_spoolmodel" (
				"databaseId" INTEGER NOT NULL PRIMARY KEY,
				"created" DATETIME NOT NULL,
				"isTemplate" INTEGER,
				"displayName" VARCHAR(255),
				"vendor" VARCHAR(255),
				"material" VARCHAR(255),
				"density" REAL,
				"diameter" REAL,
				"colorName" VARCHAR(255),
				"color" VARCHAR(255),
				"temperature" INTEGER,
				"totalWeight" REAL,
				"usedWeight" REAL,
				"remainingWeight" REAL,
				"usedLength" INTEGER,
				"code" VARCHAR(255),
				"serialNumber" VARCHAR(255),
				"project" VARCHAR(255),
				"firstUse" DATETIME,
				"lastUse" DATETIME,
				"purchasedFrom" VARCHAR(255),
				"purchasedOn" DATE,
				"cost" REAL,
				"costUnit" VARCHAR(255),
				"labels" TEXT,
				"noteText" TEXT,
				"noteDeltaFormat" TEXT,
				"noteHtml" TEXT,
				'version' INTEGER,
				'diameterTolerance' REAL,
				'spoolWeight' REAL,
				'flowRateCompensation' INTEGER,
				'bedTemperature' INTEGER,
				'enclosureTemperature' INTEGER,
				'totalLength' INTEGER);

				INSERT INTO 'spo_spoolmodel'
				(databaseId, created, isTemplate, displayName, vendor, material, density, diameter, diameter, colorName, color, temperature, totalWeight, usedWeight, remainingWeight, usedLength, code, serialNumber,project, firstUse, lastUse, purchasedFrom, purchasedOn, cost, costUnit, labels, noteText, noteDeltaFormat, noteHtml, version, diameterTolerance, spoolWeight, flowRateCompensation, bedTemperature, enclosureTemperature, totalLength)
				  SELECT databaseId, created, isTemplate, displayName, vendor, material, density, diameter, diameter, colorName, color, temperature, totalWeight, usedWeight, remainingWeight, usedLength, code, serialNumber,project, firstUse, lastUse, purchasedFrom, purchasedOn, cost, costUnit, labels, noteText, noteDeltaFormat, noteHtml, version, diameterTolerance, spoolWeight, flowRateCompensation, bedTemperature, encloserTemperature, totalLength
				  FROM 'spo_spoolmodel_old';

				DROP TABLE 'spo_spoolmodel_old';

			UPDATE 'spo_pluginmetadatamodel' SET value=4 WHERE key='databaseSchemeVersion';
		COMMIT;
		PRAGMA foreign_keys=on;
		"""
		cursor.executescript(sql)

		connection.close()

		self._logger.info(" Successfully 3 -> 4")
		pass

	def _upgradeFrom2To3(self):
		self._logger.info(" Starting 2 -> 3")
		# What is changed:
		# - version = IntegerField(null=True)  # since V3
		# - diameterTolerance = FloatField(null=True)  # since V3
		# - flowRateCompensation = IntegerField(null=True)  # since V3
		# - bedTemperature = IntegerField(null=True)  # since V3
		# - enclosureTemperature = IntegerField(null=True)  # since V3

		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		sql = """
		PRAGMA foreign_keys=off;
		BEGIN TRANSACTION;

			ALTER TABLE 'spo_spoolmodel' ADD 'version' INTEGER;
			ALTER TABLE 'spo_spoolmodel' ADD 'diameterTolerance' REAL;
			ALTER TABLE 'spo_spoolmodel' ADD 'spoolWeight' REAL;
			ALTER TABLE 'spo_spoolmodel' ADD 'flowRateCompensation' INTEGER;
			ALTER TABLE 'spo_spoolmodel' ADD 'bedTemperature' INTEGER;
			ALTER TABLE 'spo_spoolmodel' ADD 'encloserTemperature' INTEGER;
			ALTER TABLE 'spo_spoolmodel' ADD 'totalLength' INTEGER;

			UPDATE 'spo_spoolmodel' SET version=1;

			UPDATE 'spo_pluginmetadatamodel' SET value=3 WHERE key='databaseSchemeVersion';
		COMMIT;
		PRAGMA foreign_keys=on;
		"""
		cursor.executescript(sql)

		connection.close()

		self._logger.info(" Successfully 2 -> 3")
		pass

	def _upgradeFrom1To2(self):
		self._logger.info(" Starting 1 -> 2")
		# What is changed:
		# - SpoolModel: Add Column remainingWeight (needed fro filtering, sorting)
		connection = sqlite3.connect(self._databaseSettings.fileLocation)
		cursor = connection.cursor()

		sql = """
		PRAGMA foreign_keys=off;
		BEGIN TRANSACTION;

			ALTER TABLE 'spo_spoolmodel' ADD 'remainingWeight' REAL;

			UPDATE 'spo_pluginmetadatamodel' SET value=2 WHERE key='databaseSchemeVersion';
		COMMIT;
		PRAGMA foreign_keys=on;
		"""
		cursor.executescript(sql)

		connection.close()
		self._logger.info("Database 'altered' successfully. Try to calculate remaining weight.")
		#  Calculate the remaining weight for all current spools
		with self._database.atomic() as transaction:  # Opens new transaction.
			try:
				allSpoolModels = self.loadAllSpoolsByQuery(None)
				if (allSpoolModels != None):
					for spoolModel in allSpoolModels:
						totalWeight = spoolModel.totalWeight
						usedWeight = spoolModel.usedWeight
						remainingWeight = Transformer.calculateRemainingWeight(usedWeight, totalWeight)
						if (remainingWeight != None):
							spoolModel.remainingWeight = remainingWeight
							spoolModel.save()

				# do expicit commit
				transaction.commit()
			except Exception as e:
				# Because this block of code is wrapped with "atomic", a
				# new transaction will begin automatically after the call
				# to rollback().
				transaction.rollback()
				self._logger.exception("Could not upgrade database scheme from 1 To 2:" + str(e))

				self._passMessageToClient("error", "DatabaseManager", "Could not upgrade database scheme V1 to V2. See OctoPrint.log for details!")
			pass

		self._logger.info(" Successfully 1 -> 2")
		pass


	def _createDatabaseTables(self):
		self._logger.info("Creating new database tables for spoolmanager-plugin")
		self._database.connect(reuse_if_open=True)
		if (self._databaseSettings.useExternal == True):
			self._database.create_tables(MODELS, safe=True)
		else:
			self._database.drop_tables(MODELS)
			self._database.create_tables(MODELS)

		meta = PluginMetaDataModel.get_or_none(PluginMetaDataModel.key == PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION)
		if (meta == None):
			PluginMetaDataModel.create(key=PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION, value=CURRENT_DATABASE_SCHEME_VERSION)
		else:
			meta.value = CURRENT_DATABASE_SCHEME_VERSION
			meta.save()
		self.closeDatabase()

	def _storeErrorMessage(self, type, title, message, sendErrorPopUp):
		# store current error message
		self._currentErrorMessageDict = {
			"type":type,
			"title":title,
			"message":message
		}
		# send to client, if needed
		if (sendErrorPopUp == True):
			self._passMessageToClient(type, title, message)

	################################################################################################### public functions
	@staticmethod
	def buildDefaultDatabaseFileLocation(pluginDataBaseFolder):
		databaseFileLocation = os.path.join(pluginDataBaseFolder, "spoolmanager.db")
		return databaseFileLocation

	def initDatabase(self, databaseSettings, sendMessageToClient):

		self._logger.info("Init DatabaseManager")
		self._currentErrorMessageDict = None
		self._passMessageToClient = sendMessageToClient
		self._databaseSettings = databaseSettings

		databaseFileLocation = DatabaseManager.buildDefaultDatabaseFileLocation(databaseSettings.baseFolder)
		self._databaseSettings.fileLocation = databaseFileLocation
		existsDatabaseFile = str(os.path.exists(self._databaseSettings.fileLocation))
		self._logger.info("Databasefile '" +self._databaseSettings.fileLocation+ "' exists: " + existsDatabaseFile)

		if (existsDatabaseFile == False):
			self._createDatabase(FORCE_CREATE_TABLES)
			self.closeDatabase()

		import logging
		logger = logging.getLogger('peewee')
		# we need only the single logger without parent
		logger.parent = None
		# logger.addHandler(logging.StreamHandler())
		# activate SQL logging on PEEWEE side and on PLUGIN side
		# logger.setLevel(logging.DEBUG)
		# self._sqlLogger.setLevel(logging.DEBUG)
		self.showSQLLogging(self.sqlLoggingEnabled)

		wrappedHandler = WrappedLoggingHandler(self._sqlLogger)
		logger.addHandler(wrappedHandler)

		connected = self.connectoToDatabase(sendErrorPopUp=False)
		if (connected == True):
			self._createDatabase(FORCE_CREATE_TABLES)
			self.closeDatabase()

		return self._currentErrorMessageDict

	def assignNewDatabaseSettings(self, databaseSettings):
		self._databaseSettings = databaseSettings

	def getDatabaseSettings(self):
		return self._databaseSettings

	def testDatabaseConnection(self, databaseSettings = None):
		result = None
		backupCurrentDatabaseSettings = None
		try:
			# use provided databasesettings or default if not provided
			if (databaseSettings != None):
				backupCurrentDatabaseSettings = self._databaseSettings
				self._databaseSettings = databaseSettings

			succesful = self.connectoToDatabase()
			if (succesful == False):
				result = self.getCurrentErrorMessageDict()
		finally:
			try:
				self.closeDatabase()
			except:
				pass # do nothing
			if (backupCurrentDatabaseSettings != None):
				self._databaseSettings = backupCurrentDatabaseSettings

		return result


	def getCurrentErrorMessageDict(self):
		return self._currentErrorMessageDict

	# connect to the current database
	def connectoToDatabase(self, withMetaCheck=False, sendErrorPopUp=True) :
		# reset current errorDict
		self._currentErrorMessageDict = None
		self._isConnected = False

		# build connection
		try:
			if (self.sqlLoggingEnabled):
				self._logger.info("Database connection with...")
				self._logger.info(self._databaseSettings)
			self._database = self._buildDatabaseConnection()

			# connect to Database
			DatabaseManager.db = self._database
			self._database.bind(MODELS)

			self._database.connect()
			if (self.sqlLoggingEnabled):
				self._logger.info("Database connection successful. Checking Scheme versions")
			# TODO do I realy need to check the meta-infos in the connect function
			# schemeVersionFromPlugin = str(CURRENT_DATABASE_SCHEME_VERSION)
			# schemeVersionFromDatabaseModel = str(PluginMetaDataModel.get(PluginMetaDataModel.key == PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION).value)
			# if (schemeVersionFromPlugin != schemeVersionFromDatabaseModel):
			# 	errorMessage = "Plugin needs database scheme version: "+str(schemeVersionFromPlugin)+", but database has version: "+str(schemeVersionFromDatabaseModel);
			# 	self._storeErrorMessage("error", "database scheme version", errorMessage , False)
			# 	self._logger.error(errorMessage)
			# 	self._isConnected = False
			# else:
			# 	self._logger.info("...succesfull connected")
			# 	self._isConnected = True
			self._isConnected = True
		except Exception as e:
			errorMessage = str(e)
			self._logger.exception("connectoToDatabase")
			self.closeDatabase()
			# type, title, message
			self._storeErrorMessage("error", "connection problem", errorMessage, sendErrorPopUp)
			return False
		return self._isConnected

	def closeDatabase(self, ) :
		self._currentErrorMessageDict = None
		try:
			self._database.close()
			pass
		except Exception as e:
			pass ## ignore close exception
		self._isConnected = False

	def isConnected(self):
		return self._isConnected

	def showSQLLogging(self, enabled):
		import logging
		logger = logging.getLogger('peewee')

		if (enabled):
			logger.setLevel(logging.DEBUG)
			self._sqlLogger.setLevel(logging.DEBUG)
		else:
			logger.setLevel(logging.ERROR)
			self._sqlLogger.setLevel(logging.ERROR)

	def backupDatabaseFile(self):

		if (self._databaseSettings.useExternal == True):
			self._logger.info("No database backup needed, because we are using an external database.")
		else:
			if (os.path.exists(self._databaseSettings.fileLocation)):
				self._logger.info("Starting database backup")
				now = datetime.datetime.now()
				currentDate = now.strftime("%Y%m%d-%H%M")
				currentSchemeVersion = "unknown"
				try:
					currentSchemeVersion = PluginMetaDataModel.get(
						PluginMetaDataModel.key == PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION)
					if (currentSchemeVersion != None):
						currentSchemeVersion = str(currentSchemeVersion.value)
				except Exception as e:
					self._logger.exception("Could not read databasescheme version:" + str(e))

				backupDatabaseFilePath = self._databaseSettings.fileLocation[0:-3] + "-backup-V" + currentSchemeVersion + "-" +currentDate+".db"
				# backupDatabaseFileName = "spoolmanager-backup-"+currentDate+".db"
				# backupDatabaseFilePath = os.path.join(backupFolder, backupDatabaseFileName)
				if not os.path.exists(backupDatabaseFilePath):
					shutil.copy(self._databaseSettings.fileLocation, backupDatabaseFilePath)
					self._logger.info("Backup of spoolmanager database created '" + backupDatabaseFilePath + "'")
				else:
					self._logger.warn("Backup of spoolmanager database ('" + backupDatabaseFilePath + "') is already present. No backup created.")
				return backupDatabaseFilePath
			else:
				self._logger.info("No database backup needed, because there is no databasefile '"+str(self._databaseSettings.fileLocation)+"'")

	def reCreateDatabase(self, databaseSettings = None):
		self._currentErrorMessageDict = None
		self._logger.info("ReCreating Database")
		self._logger.info(databaseSettings)
		if ((databaseSettings != None and databaseSettings.useExternal == True) or (databaseSettings == None and self._databaseSettings.useExternal == True)):
			self._logger.warn("ReCreating database is disabled for external databases")
			return

		backupCurrentDatabaseSettings = None
		if (databaseSettings != None):
			backupCurrentDatabaseSettings = self._databaseSettings
			self._databaseSettings = databaseSettings
		try:
			# - connect to dataabase
			self.connectoToDatabase()

			self._createDatabase(True)

			# - close dataabase
			self.closeDatabase()
		finally:
			# - restore database settings
			if (backupCurrentDatabaseSettings != None):
				self._databaseSettings = backupCurrentDatabaseSettings

	def copySpoolData(self, databaseSettings = None):
		if (databaseSettings != None and databaseSettings.useExternal == True):
			self._logger.warn("Copying data into an external database is disabled")
			return {
				"success": False,
				"copySpoolCount": 0
			}

		loadResult = False
		copySpoolCount = 0

		backupCurrentDatabaseSettings = None
		if (databaseSettings != None):
			backupCurrentDatabaseSettings = self._databaseSettings
		else:
			# use default settings
			databaseSettings = self._databaseSettings
			backupCurrentDatabaseSettings = self._databaseSettings

		try:
			currentDatabaseType = databaseSettings.type
			currentUseExternal = databaseSettings.useExternal

			# First load meta from local sqlite database
			databaseSettings.type = "sqlite"
			databaseSettings.baseFolder = self._databaseSettings.baseFolder
			databaseSettings.fileLocation = self._databaseSettings.fileLocation
			databaseSettings.useExternal = False
			self._databaseSettings = databaseSettings

			try:
				self.connectoToDatabase( sendErrorPopUp=False)
				allSpools = SpoolModel.select()
				self.closeDatabase()
			except Exception as e:
				errorMessage = "local database: " + str(e)
				self._logger.error("Connecting to local database not possible")
				self._logger.exception(e)
				try:
					self.closeDatabase()
				except Exception:
					pass  # ignore close exception


			databaseSettings.type = currentDatabaseType
			databaseSettings.useExternal = True
			self._databaseSettings = databaseSettings

			try:
				self.connectoToDatabase( sendErrorPopUp=False)
				self._createDatabase(True)
				for spool in allSpools:
					spoolJson = model_to_dict(spool)
					SpoolModel.insert(spoolJson).execute()
					copySpoolCount = copySpoolCount + 1
				self.closeDatabase()
			except Exception as e:
				errorMessage = "database: " + str(e)
				self._logger.error("Connecting to external database not possible")
				self._logger.exception(e)
				try:
					self.closeDatabase()
				except Exception:
					pass  # ignore close exception			

		finally:
			# restore orig. databasettings
			if (backupCurrentDatabaseSettings != None):
				self._databaseSettings = backupCurrentDatabaseSettings

		return {
			"success": loadResult,
			"copySpoolCount": copySpoolCount
		}

	################################################################################################ DATABASE OPERATIONS
	def _handleReusableConnection(self, databaseCallMethode, withReusedConnection, methodeNameForLogging, defaultReturnValue=None):
		try:
			if (withReusedConnection == True):
				if (self._isConnected == False):
					self._logger.error("Database not connected. Check database-settings!")
					return defaultReturnValue
			else:
				self.connectoToDatabase()
			return databaseCallMethode()
		except Exception as e:
			errorMessage = "Database call error in methode " + methodeNameForLogging
			self._logger.exception(errorMessage)

			self._passMessageToClient("error",
									  "DatabaseManager",
									  errorMessage + ". See OctoPrint.log for details!")
			return defaultReturnValue
		finally:
			try:
				if (withReusedConnection == False):
					self.closeDatabase()
			except:
				pass # do nothing
		pass

	def loadDatabaseMetaInformations(self, databaseSettings = None):

		backupCurrentDatabaseSettings = None
		if (databaseSettings != None):
			backupCurrentDatabaseSettings = self._databaseSettings
		else:
			# use default settings
			databaseSettings = self._databaseSettings
			backupCurrentDatabaseSettings = self._databaseSettings
		# filelocation
		# backupname
		# scheme version
		# spoolitem count
		schemeVersionFromPlugin = CURRENT_DATABASE_SCHEME_VERSION
		localSchemeVersionFromDatabaseModel = "-"
		localSpoolItemCount = "-"
		externalSchemeVersionFromDatabaseModel = "-"
		externalSpoolItemCount = "-"
		errorMessage = ""
		loadResult = False
		# - save current DatbaseSettings
		# currentDatabaseSettings = self._databaseSettings
		# currentDatabase = self._database
		# externalConnected = False
		# always read local meta data
		try:
			currentDatabaseType = databaseSettings.type
			currentUseExternal = databaseSettings.useExternal

			# First load meta from local sqlite database
			databaseSettings.type = "sqlite"
			databaseSettings.baseFolder = self._databaseSettings.baseFolder
			databaseSettings.fileLocation = self._databaseSettings.fileLocation
			databaseSettings.useExternal = False
			self._databaseSettings = databaseSettings
			try:
				self.connectoToDatabase( sendErrorPopUp=False)
				localSchemeVersionFromDatabaseModel = PluginMetaDataModel.get(PluginMetaDataModel.key == PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION).value
				localSpoolItemCount = self.countSpoolsByQuery()
				self.closeDatabase()
			except Exception as e:
				errorMessage = "local database: " + str(e)
				self._logger.error("Connecting to local database not possible")
				self._logger.exception(e)
				try:
					self.closeDatabase()
				except Exception:
					pass  # ignore close exception

			# Use orign Databasetype to collect the other meta data (if neeeded)
			databaseSettings.type = currentDatabaseType
			databaseSettings.useExternal = currentUseExternal
			if (databaseSettings.useExternal == True):
				# External DB
				self._databaseSettings = databaseSettings
				self.connectoToDatabase(sendErrorPopUp=False)
				externalSchemeVersionFromDatabaseModel = PluginMetaDataModel.get(PluginMetaDataModel.key == PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION).value
				externalSpoolItemCount = self.countSpoolsByQuery()
				self.closeDatabase()
			loadResult = True
		except Exception as e:
			errorMessage = str(e)
			self._logger.exception(e)
			try:
				self.closeDatabase()
			except Exception:
				pass #ignore close exception
		finally:
			# restore orig. databasettings
			if (backupCurrentDatabaseSettings != None):
				self._databaseSettings = backupCurrentDatabaseSettings

		return {
			"success": loadResult,
			"errorMessage": errorMessage,
			"schemeVersionFromPlugin": schemeVersionFromPlugin,
			"localSchemeVersionFromDatabaseModel": localSchemeVersionFromDatabaseModel,
			"localSpoolItemCount": localSpoolItemCount,
			"externalSchemeVersionFromDatabaseModel": externalSchemeVersionFromDatabaseModel,
			"externalSpoolItemCount": externalSpoolItemCount
		}

	def loadFirstSingleSpool(self, withReusedConnection=False):
		def databaseCallMethode():
			return SpoolModel.select().limit(1)[0]

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadFirstSingleSpool")


	def loadSpool(self, databaseId, withReusedConnection=False):
		def databaseCallMethode():
			return SpoolModel.get_or_none(SpoolModel.databaseId == int(databaseId))

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadSpool")

	def loadSpoolTemplates(self, withReusedConnection=False):
		def databaseCallMethode():
			return SpoolModel.select().where(SpoolModel.isTemplate == True)

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadSpoolTemplates")

	def loadAllSpoolsByQuery(self, tableQuery = None, withReusedConnection = False):

		def databaseCallMethode():
			if (tableQuery == None):
				return SpoolModel.select().order_by(SpoolModel.created.desc())

			sortColumn = tableQuery.get("sortColumn", "displayName")
			sortOrder = tableQuery.get("sortOrder", "desc")
			filterName = tableQuery.get("filterName", "")

			if ("selectedPageSize" in tableQuery and StringUtils.to_native_str(tableQuery["selectedPageSize"]) == "all"):
				myQuery = SpoolModel.select()
			else:
				if ("from" in tableQuery and "to" in tableQuery):
					offset = int(tableQuery["from"])
					limit = int(tableQuery["to"])
					myQuery = SpoolModel.select().offset(offset).limit(limit)
				else:
					myQuery = SpoolModel.select()

			if ("materialFilter" in tableQuery):
				materialFilter = tableQuery.get("materialFilter", "all")
				vendorFilter = tableQuery.get("vendorFilter", "all")
				colorFilter = tableQuery.get("colorFilter", "")
				projectFilter = tableQuery.get("projectFilter", "all")
				# materialFilter
				# u'ABS,PLA'
				# u''
				# u'all'
				materialFilter = StringUtils.to_native_str(materialFilter)
				if (materialFilter != "all"):
					if (StringUtils.isEmpty(materialFilter)):
						myQuery = myQuery.where( (SpoolModel.material == '') )
					else:
						allMaterials = materialFilter.split(",")
						myQuery = myQuery.where(SpoolModel.material.in_(allMaterials))
						# for material in allMaterials:
						# 	myQuery = myQuery.orwhere((SpoolModel.material == material))
				# vendorFilter
				# u'MatterMost,TheFactory'
				# u''
				# u'all'
				vendorFilter = StringUtils.to_native_str(vendorFilter)
				if (vendorFilter != "all"):
					if (StringUtils.isEmpty(vendorFilter)):
						myQuery = myQuery.where( (SpoolModel.vendor == '') )
					else:
						allVendors = vendorFilter.split(",")
						myQuery = myQuery.where(SpoolModel.vendor.in_(allVendors))
						# for vendor in allVendors:
						# 	myQuery = myQuery.orwhere((SpoolModel.vendor == vendor))
	  			# projectlFilter
				# u'my filaments, Client XYZ'
				# u''
				# u'all'
				projectFilter = StringUtils.to_native_str(projectFilter)
				if (projectFilter != "all"):
					if (StringUtils.isEmpty(projectFilter)):
						myQuery = myQuery.where( (SpoolModel.project == '') )
					else:
						allProjects = projectFilter.split(",")
						myQuery = myQuery.where(SpoolModel.project.in_(allProjects))
				#		# for vendor in allVendors:
				#		# 	myQuery = myQuery.orwhere((SpoolModel.vendor == vendor))
				# colorFilter
				# u'#ff0000;red,#ff0000;keinRot,#ff0000;deinRot,#ff0000;meinRot,#ffff00;yellow'
				# u''
				# u'all'
				colorFilter = StringUtils.to_native_str(colorFilter)
				if (colorFilter != "all" and StringUtils.isNotEmpty(colorFilter)):
					allColorObjects = colorFilter.split(",")
					allColors = []
					allColorNames = []
					for colorObject in allColorObjects:
						colorCodeColorName = colorObject.split(";")
						color = colorCodeColorName[0]
						colorName = colorCodeColorName[1]
						allColors.append(color)
						allColorNames.append(colorName)
					myQuery = myQuery.where(SpoolModel.color.in_(allColors))
					myQuery = myQuery.where(SpoolModel.colorName.in_(allColorNames))

					#
					# 	myQuery = myQuery.orwhere(  (SpoolModel.color == color) & (SpoolModel.colorName == colorName) )
				pass

			# mySqlText = myQuery.sql()

			if ("onlyTemplates" in filterName):
				myQuery = myQuery.where( (SpoolModel.isTemplate == True) )
			else:
				if (filterName == "hideEmptySpools"):
					myQuery = myQuery.where( (SpoolModel.remainingWeight > 0) | (SpoolModel.remainingWeight == None))
				if (filterName == "hideInactiveSpools"):
					myQuery = myQuery.where( (SpoolModel.isActive == True) )
				if (filterName == "hideEmptySpools,hideInactiveSpools"):
					myQuery = myQuery.where( ((SpoolModel.remainingWeight > 0) | (SpoolModel.remainingWeight == None)) & (SpoolModel.isActive == True) )

			if ("displayName" == sortColumn):
				if ("desc" == sortOrder):
					myQuery = myQuery.order_by(fn.Lower(SpoolModel.displayName).desc())
				else:
					myQuery = myQuery.order_by(fn.Lower(SpoolModel.displayName).asc())
			if ("lastUse" == sortColumn):
				if ("desc" == sortOrder):
					myQuery = myQuery.order_by(SpoolModel.lastUse.desc())
				else:
					myQuery = myQuery.order_by(SpoolModel.lastUse.asc())
			if ("firstUse" == sortColumn):
				if ("desc" == sortOrder):
					myQuery = myQuery.order_by(SpoolModel.firstUse.desc())
				else:
					myQuery = myQuery.order_by(SpoolModel.firstUse.asc())
			if ("remaining" == sortColumn):
				if ("desc" == sortOrder):
					myQuery = myQuery.order_by(SpoolModel.remainingWeight.desc())
				else:
					myQuery = myQuery.order_by(SpoolModel.remainingWeight.asc())
			if ("material" == sortColumn):
				if ("desc" == sortOrder):
					myQuery = myQuery.order_by(SpoolModel.material.desc())
				else:
					myQuery = myQuery.order_by(SpoolModel.material.asc())
			if ("databaseId" == sortColumn):
				if ("desc" == sortOrder):
					myQuery = myQuery.order_by(SpoolModel.databaseId.desc())
				else:
					myQuery = myQuery.order_by(SpoolModel.databaseId.asc())
			if ("shelf" == sortColumn):
				if ("desc" == sortOrder):
					myQuery = myQuery.order_by(fn.Lower(SpoolModel.shelf).desc())
				else:
					myQuery = myQuery.order_by(fn.Lower(SpoolModel.shelf).asc())
			if ("printer" == sortColumn):
				if ("desc" == sortOrder):
					myQuery = myQuery.order_by(fn.Lower(SpoolModel.printer).desc())
				else:
					myQuery = myQuery.order_by(fn.Lower(SpoolModel.printer).asc())
			#if ("project" == sortColumn):
			#	if ("desc" == sortOrder):
			#		myQuery = myQuery.order_by(SpoolModel.project.desc())
			#	else:
			#		myQuery = myQuery.order_by(SpoolModel.project.asc())
	
			self._logger.info("Quering spools: %s" % myQuery)
			return myQuery

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadAllSpoolsByQuery")

	def saveSpool(self, spoolModel, withReusedConnection=False):

		def databaseCallMethode():
			# databaseId = model.get_id()
			# if (databaseId != None):
			# 	# we need to update and we need to make
			# 	spoolModel = self.loadSpool(databaseId)
			# 	if (spoolModel == None):
			# 		self._passMessageToClient("error", "DatabaseManager",
			# 								  "Could not update the Spool, because it is already deleted!")
			# 		return
			# 	else:
			# 		versionFromUI = model.version if model.version != None else 1
			# 		versionFromDatabase = spoolModel.version if spoolModel.version != None else 1
			# 		if (versionFromUI != versionFromDatabase):
			# 			self._passMessageToClient("error", "DatabaseManager",
			# 									  "Could not update the Spool, because someone already modified the spool. Do a reload!")
			# 			return

			with self._database.atomic() as transaction:  # Opens new transaction.
				try:
					databaseId = spoolModel.databaseId
					if (databaseId != None):
						versionFromUI = None
						# we need to update and we need to make sure nobody else modify the data
						currentSpoolModel = self.loadSpool(databaseId, withReusedConnection)
						if (currentSpoolModel == None):
							self._passMessageToClient("error", "DatabaseManager",
													  "Could not update the Spool, because it is already deleted!")
							return
						else:
							versionFromUI = spoolModel.version if spoolModel.version != None else 1
							versionFromDatabase = currentSpoolModel.version if currentSpoolModel.version != None else 1
							if (versionFromUI != versionFromDatabase):
								self._passMessageToClient("error", "DatabaseManager",
														  "Could not update the Spool, because someone already modified the spool. Do a manuel reload!")
								return
							# okay fits, increate version
						newVersion = versionFromUI + 1
						spoolModel.version = newVersion

					# Not needed any more, we have multi-temlates
					# if (spoolModel.isTemplate == True):
					# 	#  remove template flag from last templateSpool
					# 	SpoolModel.update({SpoolModel.isTemplate: False}).where(SpoolModel.isTemplate == True).execute()

					spoolModel.save()
					databaseId = spoolModel.get_id()
					# do expicit commit
					transaction.commit()
				except Exception as e:
					# Because this block of code is wrapped with "atomic", a
					# new transaction will begin automatically after the call
					# to rollback().
					transaction.rollback()
					self._logger.exception("Could not insert Spool into database")

					self._passMessageToClient("error", "DatabaseManager", "Could not insert the spool into the database. See OctoPrint.log for details!")
				pass

			return databaseId

		# always recalculate the remaing weight (total - used)
		totalWeight = spoolModel.totalWeight
		usedWeight = spoolModel.usedWeight
		if (totalWeight != None):
			if (usedWeight == None):
				usedWeight = 0.0
			remainingWeight = Transformer.calculateRemainingWeight(usedWeight, totalWeight)
			spoolModel.remainingWeight = remainingWeight

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "saveSpool")

	def countSpoolsByQuery(self, withReusedConnection=False):
		def databaseCallMethode():
			myQuery = SpoolModel.select()
			return myQuery.count()

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "countSpoolsByQuery")

	def loadCatalogVendors(self, withReusedConnection=False):
		def databaseCallMethode():
			result = set()
			result.add("")
			myQuery = SpoolModel.select(SpoolModel.vendor).distinct()
			for spool in myQuery:
				value = spool.vendor
				if (value != None):
					result.add(value)
			return result;

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadCatalogVendors", set())
	
	def loadCatalogProjects(self, withReusedConnection=False):
		def databaseCallMethode():
			result = set()
			result.add("")
			myQuery = SpoolModel.select(SpoolModel.project).distinct()
			for spool in myQuery:
				value = spool.project
				if (value != None):
					result.add(value)
			return result;

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadCatalogProjects", set())

	def loadCatalogMaterials(self, withReusedConnection=False):
		def databaseCallMethode():
			result = set()
			myQuery = SpoolModel.select(SpoolModel.material).distinct()
			for spool in myQuery:
				value = spool.material
				if (value != None):
					result.add(value)
			return result;

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadCatalogMaterials", set())

	def loadCatalogLabels(self, tableQuery, withReusedConnection=False):
		def databaseCallMethode():
			result = set()
			myQuery = SpoolModel.select(SpoolModel.labels).distinct()
			for spool in myQuery:
				value = spool.labels
				if (value != None):
					spoolLabels = json.loads(value)
					for singleLabel in spoolLabels:
						result.add(singleLabel)
			return result

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadCatalogLabels", set())

	def loadCatalogColors(self, withReusedConnection=False):
		def databaseCallMethode():
			result = []
			myQuery = SpoolModel.select(SpoolModel.color, SpoolModel.colorName).distinct()
			for spool in myQuery:
				if (spool.color != None and spool.colorName):
					colorInfo = {
						"colorId": spool.color + ";" + spool.colorName,
						"color": spool.color,
						"colorName": spool.colorName
					}
					result.append(colorInfo)
			return result

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadCatalogColors", set())

	def deleteSpool(self, databaseId, withReusedConnection=False):
		def databaseCallMethode():
			with self._database.atomic() as transaction:  # Opens new transaction.
				try:
					# first delete relations
					# n = FilamentModel.delete().where(FilamentModel.printJob == databaseId).execute()
					# n = TemperatureModel.delete().where(TemperatureModel.printJob == databaseId).execute()

					deleteResult = SpoolModel.delete_by_id(databaseId)
					if (deleteResult == 0):
						return None
					return databaseId
					pass
				except Exception as e:
					# Because this block of code is wrapped with "atomic", a
					# new transaction will begin automatically after the call
					# to rollback().
					transaction.rollback()
					self._logger.exception("Could not delete spool from database:" + str(e))

					self._passMessageToClient("Spool-DatabaseManager", "Could not delete the spool ('"+ str(databaseId) +"') from the database. See OctoPrint.log for details!")
					return None
				pass

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "deleteSpool")

	def loadSheet(self, databaseId, withReusedConnection=False):
		def databaseCallMethode():
			return SheetModel.get_or_none(SheetModel.databaseId == int(databaseId))

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadSheet")

	def loadSheetByNid(self, nid, withReusedConnection=False):
		def databaseCallMethode():
			try:
				parsed = int(nid)
				result = SheetModel.get_or_none(SheetModel.databaseId == parsed)
				if (result != None):
					return result
			except Exception:
				pass
			return SheetModel.get_or_none(SheetModel.nid == nid)

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadSheetByNid")

	def loadAllSheets(self, withReusedConnection=False):
		def databaseCallMethode():
			return SheetModel.select().order_by(SheetModel.created.desc())

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadAllSheets")

	def loadAllSheetTypes(self, withReusedConnection=False):
		def databaseCallMethode():
			return SheetTypeModel.select().order_by(fn.Lower(SheetTypeModel.name).asc())

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "loadAllSheetTypes")

	def getOrCreateSheetTypeByName(self, name, withReusedConnection=False):
		def databaseCallMethode():
			model, _created = SheetTypeModel.get_or_create(name=name)
			return model

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "getOrCreateSheetTypeByName")

	def saveSheet(self, sheetModel, withReusedConnection=False):
		def databaseCallMethode():
			with self._database.atomic() as transaction:
				try:
					databaseId = sheetModel.databaseId
					if (databaseId != None):
						currentSheetModel = self.loadSheet(databaseId, withReusedConnection)
						if (currentSheetModel == None):
							self._passMessageToClient("error", "DatabaseManager",
												  "Could not update the Sheet, because it is already deleted!")
							return
						versionFromUI = sheetModel.version if sheetModel.version != None else 1
						versionFromDatabase = currentSheetModel.version if currentSheetModel.version != None else 1
						if (versionFromUI != versionFromDatabase):
							self._passMessageToClient("error", "DatabaseManager",
												  "Could not update the Sheet, because someone already modified the sheet. Do a manuel reload!")
							return
						sheetModel.version = versionFromUI + 1

					if (databaseId == None):
						try:
							if (sheetModel.nid == None or str(sheetModel.nid).strip() == ""):
								sheetModel.nid = "tmp-" + uuid.uuid4().hex
						except Exception:
							sheetModel.nid = "tmp-" + uuid.uuid4().hex

					try:
						if (sheetModel.compatibleMaterials == None or str(sheetModel.compatibleMaterials).strip() == ""):
							if (sheetModel.sheetType != None and sheetModel.sheetType.compatibleMaterials != None):
								sheetModel.compatibleMaterials = sheetModel.sheetType.compatibleMaterials
					except Exception:
						pass

					sheetModel.save()
					databaseId = sheetModel.get_id()
					sheetModel.nid = str(databaseId)
					sheetModel.save()
					transaction.commit()
				except Exception as e:
					transaction.rollback()
					self._logger.exception("Could not insert Sheet into database")
					self._passMessageToClient("error", "DatabaseManager",
											  "Could not insert the sheet into the database. See OctoPrint.log for details!")
					return None
				return databaseId

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "saveSheet")

	def deleteSheet(self, databaseId, withReusedConnection=False):
		def databaseCallMethode():
			with self._database.atomic() as transaction:
				try:
					deleteResult = SheetModel.delete_by_id(databaseId)
					if (deleteResult == 0):
						return None
					return databaseId
				except Exception as e:
					transaction.rollback()
					self._logger.exception("Could not delete sheet from database:" + str(e))
					self._passMessageToClient("Sheet-DatabaseManager",
											  "Could not delete the sheet ('"+ str(databaseId) +"') from the database. See OctoPrint.log for details!")
					return None

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "deleteSheet")

	def unassignSheet(self, sheetModel, withReusedConnection=False):
		def databaseCallMethode():
			with self._database.atomic() as transaction:
				try:
					sheetModel.printerNumber = None
					sheetModel.magazinePosition = None
					sheetModel.save()
					transaction.commit()
					return sheetModel
				except Exception:
					transaction.rollback()
					raise

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "unassignSheet")

	def assignSheetToPrinter(self, sheetModel, printerNumber, withReusedConnection=False):
		def databaseCallMethode():
			with self._database.atomic() as transaction:
				try:
					SheetModel.update({
						SheetModel.printerNumber: None,
						SheetModel.magazinePosition: None
					}).where(
						(SheetModel.printerNumber == int(printerNumber)) &
						(SheetModel.magazinePosition.is_null(True)) &
						(SheetModel.databaseId != sheetModel.databaseId)
					).execute()

					sheetModel.printerNumber = int(printerNumber)
					sheetModel.magazinePosition = None
					sheetModel.save()
					transaction.commit()
					return sheetModel
				except Exception:
					transaction.rollback()
					raise

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "assignSheetToPrinter")

	def appendSheetToMagazine(self, sheetModel, printerNumber, withReusedConnection=False):
		def databaseCallMethode():
			with self._database.atomic() as transaction:
				try:
					maxPos = (SheetModel
							  .select(fn.MAX(SheetModel.magazinePosition))
							  .where((SheetModel.printerNumber == int(printerNumber)) & (SheetModel.magazinePosition.is_null(False)))
							  .scalar())

					if (maxPos == None):
						maxPos = 0
					newPos = int(maxPos) + 1

					sheetModel.printerNumber = int(printerNumber)
					sheetModel.magazinePosition = newPos
					sheetModel.save()
					transaction.commit()
					return sheetModel
				except Exception:
					transaction.rollback()
					raise

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "appendSheetToMagazine")

	def getSheetsStateForPrinter(self, printerNumber, withReusedConnection=False):
		def databaseCallMethode():
			currentSheet = (SheetModel
							.select()
							.where((SheetModel.printerNumber == int(printerNumber)) & (SheetModel.magazinePosition.is_null(True)))
							.limit(1)
							.first())

			magazineSheets = (SheetModel
							 .select()
							 .where((SheetModel.printerNumber == int(printerNumber)) & (SheetModel.magazinePosition.is_null(False)))
							 .order_by(SheetModel.magazinePosition.asc(), SheetModel.databaseId.asc()))

			return currentSheet, magazineSheets

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "getSheetsStateForPrinter")

	def setCurrentlyPrintingForPrinter(self, printerNumber, currentlyPrinting, withReusedConnection=False):
		def databaseCallMethode():
			with self._database.atomic() as transaction:
				try:
					SheetModel.update({
						SheetModel.currentlyPrinting: currentlyPrinting
					}).where(
						(SheetModel.printerNumber == int(printerNumber)) &
						(SheetModel.magazinePosition.is_null(True))
					).execute()
					transaction.commit()
					return True
				except Exception:
					transaction.rollback()
					raise

		return self._handleReusableConnection(databaseCallMethode, withReusedConnection, "setCurrentlyPrintingForPrinter", False)

