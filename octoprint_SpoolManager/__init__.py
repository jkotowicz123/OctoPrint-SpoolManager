# coding=utf-8
from __future__ import absolute_import

import math
from datetime import datetime
import flask
import octoprint.plugin
from flask import request
from octoprint.events import Events
from octoprint.util.comm import MachineCom

from octoprint_SpoolManager.DatabaseManager import DatabaseManager
# from octoprint_SpoolManager.Odometer import FilamentOdometer

from octoprint_SpoolManager.newodometer import NewFilamentOdometer
from octoprint_SpoolManager.mmu_routing import (
	DEFAULT_LOAD_DISTANCE_MM,
	DEFAULT_PURGE_PASSES,
	DEFAULT_MAINTENANCE_BYPASS_FILES,
	maintenance_bypass_files,
	LEGACY_LOAD_DISTANCE_MM,
	MmuRoutingSession,
	STATE_LOADED,
	STATE_UNKNOWN,
	STATE_UNLOADED,
	build_slot,
	classify_mmu_serial_line,
	mmu_completion_state,
	continuousprint_next_path,
	parse_contract_file,
	routing_bypass_reason,
	routing_bypass_reason_file,
	runtime_template_errors_file,
	unload_lift_target_file,
	select_slot,
	spool_accounting_targets,
	should_retain_for_next,
	should_count_for_odometer,
)

from octoprint_SpoolManager.api import Transformer
from octoprint_SpoolManager.api.SpoolManagerAPI import SpoolManagerAPI
from octoprint_SpoolManager.common import StringUtils
from octoprint_SpoolManager.common.SettingsKeys import SettingsKeys
from octoprint_SpoolManager.common.EventBusKeys import EventBusKeys
from octoprint_SpoolManager.filament_accounting import remaining_metadata_length

import json
import re
import threading
from octoprint.settings import settings as octo_settings

class SpoolmanagerPlugin(
							SpoolManagerAPI,
							octoprint.plugin.SimpleApiPlugin,
							octoprint.plugin.SettingsPlugin,
                            octoprint.plugin.AssetPlugin,
                            octoprint.plugin.TemplatePlugin,
							octoprint.plugin.StartupPlugin,
							octoprint.plugin.EventHandlerPlugin,
):

	def initialize(self):
		self._logger.info("Start initializing")

		# DATABASE
		self.databaseConnectionProblemConfirmed = False
		sqlLoggingEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_SQL_LOGGING_ENABLED])
		self._databaseManager = DatabaseManager(self._logger, sqlLoggingEnabled)

		databaseSettings = self._buildDatabaseSettingsFromPluginSettings()

		# init database
		self._databaseManager.initDatabase(databaseSettings, self._sendMessageToClient)


		# OTHER STUFF
		# self._filamentOdometer = None
		# self._filamentOdometer = FilamentOdometer()
		# TODO no idea what this thing is doing in detail self._filamentOdometer.set_g90_extruder(self._settings.getBoolean(["feature", "g90InfluencesExtruder"]))

		self.myFilamentOdometer = NewFilamentOdometer(self._extrusionValuesChanged)
		self.myFilamentOdometer.set_g90_extruder(self._settings.get_boolean(["feature", "g90InfluencesExtruder"]))

		self._filamentManagerPluginImplementation = None
		self._filamentManagerPluginImplementationState = None

		self._lastPrintState = None

		self.metaDataFilamentLengths = []
		# Length already assigned to earlier spools during pause or a deliberate
		# mid-print spool switch. The final slicer total must only contribute the
		# unassigned remainder to the last spool.
		self._committedPrintFilamentLengths = {}

		self.alreadyCanceled = False

		# MMU state is intentionally not restored after restart. Hardware routing must
		# be explicitly reconciled before it may move filament again.
		self._mmuRoutingSession = MmuRoutingSession()
		self._mmuLoadedState = STATE_UNKNOWN
		self._mmuLoadedSlot = None
		self._mmuPendingAction = None
		self._mmuPendingSlot = None
		self._mmuActionUncertain = False
		self._mmuStateSource = "startup"
		self._mmuStateUpdatedAt = datetime.now()
		self._migrateMmuRoutingSettings()

		self._logger.info("Done initializing")
		pass

	################################################################################################### public functions

	def checkRemainingFilament(self, forToolIndex=None):
		"""
		Checks if all spools or single spool includes enough filament

		:param forToolIndex check only for the provided toolIndex
		:return: see
		"""
		shouldWarn = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_WARN_IF_FILAMENT_NOT_ENOUGH])

		# - check, if spool change in pause-mode

		# - check if new spool fits for current printjob
		selectedSpools = self.loadSelectedSpools()

		requiredWeightResult = self._evaluateRequiredWeight(selectedSpools, forToolIndex, shouldWarn)
		# "metaDataMissing": metaDataMissing,
		# "warnUser": fromPluginSettings,
		# "attributesMissing": someAttributesMissing,
		# "notEnough": notEnough,
		# "detailedSpoolResult": [
		# 				"toolIndex": toolIndex,
		# 				"requiredWeight": requiredWeight,
		# 				"requiredLength": filamentLength,
		# 				"remainingWeight": remainingWeight,
		# 				"diameter": diameter,
		# 				"density": density,
		# 				"notEnough": notEnough,
		# 				"spoolSelected": True
		# ]

		# for a single check, don't send the info to the browser
		if (forToolIndex == None):
			requiredWeightResult["action"] = "requiredFilamentChanged"
			self._sendDataToClient(requiredWeightResult)

		return requiredWeightResult

	def set_temp_offsets(self, toolIndex, spoolModel):
		toolOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_TOOL_OFFSET_ENABLED])
		bedOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_BED_OFFSET_ENABLED])
		enclosureOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_ENCLOSURE_OFFSET_ENABLED])

		offset_dict = dict()
		if (toolOffsetEnabled == True and spoolModel != None):
			# toolIndex should be tool0
			offset_dict["tool"+str(toolIndex)] = spoolModel.offsetTemperature if spoolModel.offsetTemperature is not None else 0

		if (bedOffsetEnabled == True and spoolModel != None):
			if (spoolModel.offsetBedTemperature != None):
				if (self._isNewOffsetTemperatureGreater("bed", spoolModel.offsetBedTemperature) == True):
					offset_dict["bed"] = spoolModel.offsetBedTemperature

		if (enclosureOffsetEnabled == True and spoolModel != None):
			if (spoolModel.offsetEnclosureTemperature != None):
				if (self._isNewOffsetTemperatureGreater("chamber", spoolModel.offsetEnclosureTemperature) == True):
					offset_dict["chamber"] = spoolModel.offsetEnclosureTemperature

		if (len(offset_dict) != 0):
			self._printer.set_temperature_offset(offset_dict)


	def _isNewOffsetTemperatureGreater(self, selectedOffset, newOffset):

		allTemperatures = self._printer.get_current_temperatures()
		selectedTemperature =  allTemperatures[selectedOffset] if selectedOffset in allTemperatures else None
		if (selectedTemperature != None):
			currentOffset = selectedTemperature["offset"]
			if (currentOffset != None and newOffset > currentOffset):
				return True
		return False


	def clear_temp_offsets(self):
		toolOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_TOOL_OFFSET_ENABLED])
		bedOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_BED_OFFSET_ENABLED])
		enclosureOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_ENCLOSURE_OFFSET_ENABLED])

		offset_dict = dict()
		if (toolOffsetEnabled == True):
			printer_profile = self._printer_profile_manager.get_current_or_default()
			printerProfileToolCount = printer_profile['extruder']['count']
			# for toolIndex, filamentLength in enumerate(self.metaDataFilamentLengths):
			for toolIndex in range(printerProfileToolCount):
				# toolIndex should be tool0
				offset_dict["tool"+str(toolIndex)] = 0

		if (bedOffsetEnabled == True):
			offset_dict["bed"] = 0

		if (enclosureOffsetEnabled == True):
			offset_dict["chamber"] = 0

		if (len(offset_dict) != 0):
			self._printer.set_temperature_offset(offset_dict)

	################################################################################################## private functions

	def _sendDataToClient(self, payloadDict):
		self._plugin_manager.send_plugin_message(self._identifier,
												 payloadDict)

	def _sendMessageToClient(self, type, title, message, autoclose=False):
		self._logger.warning("SendToClient: " + type + "#" + title + "#" + message)
		self._sendDataToClient(dict(action="showPopUp",
									type=type,
									title= title,
									message=message,
									autoclose=autoclose))

	def _sendPayload2EventBus(self, eventKey, eventPayload):

		eventName = "plugin_spoolmanager_" + eventKey
		self._logger.info("Send Event '"+eventName+"' with payload '"+str(eventPayload)+"' to event-bus")
		self._event_bus.fire(eventName, payload=eventPayload)

	def _checkForMissingPluginInfos(self, sendToClient=False):

		pluginInfo = self._getPluginInformation("filamentmanager")
		self._filamentManagerPluginImplementationState  = pluginInfo[0]
		self._filamentManagerPluginImplementation = pluginInfo[1]

		self._logger.info("Plugin-State: "
						  "filamentmanager=" + self._filamentManagerPluginImplementationState + " ")
		pass

	def _getSpoolAccountingTargets(self, selectedSpools):
		pairs = spool_accounting_targets(
			len(selectedSpools or []),
			mmu_active=self._mmuRoutingSession.active,
			dry_run=self._mmuRoutingSession.dry_run,
			selected_slot=self._mmuRoutingSession.slot
		)
		return [
			(gcodeToolIndex, spoolSlot, selectedSpools[spoolSlot])
			for gcodeToolIndex, spoolSlot in pairs
		]

	# get the plugin with status information
	# [0] == status-string
	# [1] == implementaiton of the plugin
	def _getPluginInformation(self, pluginKey):

		status = None
		implementation = None

		if pluginKey in self._plugin_manager.plugins:
			plugin = self._plugin_manager.plugins[pluginKey]
			if plugin != None:
				if (plugin.enabled == True):
					status = "enabled"
					# for OP 1.4.x we need to check agains "icompatible"-attribute
					if (hasattr(plugin, 'incompatible') ):
						if (plugin.incompatible == False):
							implementation = plugin.implementation
						else:
							status = "incompatible"
					else:
						# OP 1.3.x
						implementation = plugin.implementation
					pass
				else:
					status = "disabled"
		else:
			status = "missing"

		return [status, implementation]

	def _extrusionValuesChanged(self, newExtrusionValues):
		if (self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_EXTRUSION_DEBUGGING_ENABLED])):
			self._sendDataToClient(dict(action="extrusionValuesChanged",
										extrusionValues=newExtrusionValues))

		pass

	def _readingFilamentMetaData(self):
		filamentLengthPresentInMeta = False
		self.metaDataFilamentLengths = []
		if ("job" in self._printer.get_current_data()):
			jobData = self._printer.get_current_data()["job"]
			if ("file" in jobData):
				fileData = jobData["file"]
				origin = fileData["origin"]
				path = fileData["path"]
				if (origin !=  None and path != None):
					metadata = self._file_manager.get_metadata(origin, path)
					if ("analysis" in metadata):
						if ("filament" in metadata["analysis"]):
							for toolName, toolData in metadata["analysis"]["filament"].items():
								toolIndex = int(toolName[4:])
								self.metaDataFilamentLengths += [0.0] * (toolIndex + 1 - len(self.metaDataFilamentLengths))
								self.metaDataFilamentLengths[toolIndex] = toolData["length"]
								filamentLengthPresentInMeta = True
		return filamentLengthPresentInMeta

	def _evaluateRequiredWeight(self, selectedSpools, forToolIndex=None, warnUser=False):

		self._readingFilamentMetaData()
		metaDataMissing = len(self.metaDataFilamentLengths) <= 0
		someAttributesMissing = False
		overallNotEnough = False
		requiredWeightResultDict = {
			"metaDataMissing": metaDataMissing,
			"warnUser": warnUser,
			"attributesMissing": someAttributesMissing,
			"notEnough": overallNotEnough,
			"detailedSpoolResult": []
		}
		if (metaDataMissing == True):
			return requiredWeightResultDict

		# loop over all tools
		accountingTargets = dict(
			(gcodeToolIndex, (spoolSlot, spoolModel))
			for gcodeToolIndex, spoolSlot, spoolModel in self._getSpoolAccountingTargets(selectedSpools)
		)
		for toolIndex, filamentLength in enumerate(self.metaDataFilamentLengths):
			if forToolIndex is not None and forToolIndex != toolIndex:
				continue
			spoolSlot, selectedSpool = accountingTargets.get(toolIndex, (toolIndex, None))

			if (selectedSpool != None):
				diameter = selectedSpool.diameter
				density = selectedSpool.density
				totalWeight = selectedSpool.totalWeight
				usedWeight = selectedSpool.usedWeight

				# need attributes present: diameter, density, totalWeight
				missing_fields = []
				if diameter is None:
					missing_fields.append('diameter')
				if density is None:
					missing_fields.append('density')
				if totalWeight is None:
					missing_fields.append('total weight')
				if usedWeight is None:
					usedWeight = 0.0

				if missing_fields:
					if (warnUser == True):
						self._sendMessageToClient(
							"warning", "Filament prediction not possible!",
							"Following fields not set in Spool '%s' (in tool %d): %s" % (selectedSpool.displayName, spoolSlot, ', '.join(missing_fields))
						)
					someAttributesMissing = True
				else:
					not_a_number_fields = []
					try:
						diameter = float(diameter)
					except ValueError:
						not_a_number_fields.append('diameter')
					try:
						density = float(density)
					except ValueError:
						not_a_number_fields.append('density')
					try:
						totalWeight = float(totalWeight)
					except ValueError:
						not_a_number_fields.append('totalweight')
					try:
						usedWeight = float(usedWeight)
					except ValueError:
						not_a_number_fields.append('used weight')

					if not_a_number_fields:
						if (warnUser == True):
							self._sendMessageToClient(
								"warning", "Filament prediction not possible!",
								"One of the needed fields are not a number in Spool '%s' (in tool %d): %s" % (selectedSpool.displayName, spoolSlot, ', '.join(not_a_number_fields))
							)
						someAttributesMissing = True
					else:
						# Benötigtes Gewicht = gewicht(geplante länge, durchmesser, dichte)
						requiredWeight = self._calculateWeight(filamentLength, diameter, density)

						# Vorhanden Gewicht = Gesamtgewicht - Verbrauchtes Gewicht
						# TODO don't calculate here use the value from the database
						remainingWeight = totalWeight - usedWeight

						saftyLengthInMM = self._settings.get_int([SettingsKeys.SETTINGS_KEY_SAFETY_LENGTH])
						if (saftyLengthInMM != 0):
							saftyRequiredWeight = self._calculateWeight(saftyLengthInMM, diameter, density)
							self._logger.info("saftyWeight '" + str(saftyRequiredWeight) + "' from saftyLengthInMM '" + str(saftyLengthInMM) + "' calculated")
							requiredWeight = requiredWeight + saftyRequiredWeight

						self._logger.info("tool" + str(spoolSlot) + ", requiredWeight '" + str(requiredWeight) + "',  remainingWeight '" + str(remainingWeight) + "'")

						notEnough = False
						if remainingWeight < requiredWeight and requiredWeight > 0:
							self._logger.info("Filament not enough!")
							if (warnUser == True):
								self._sendMessageToClient(
									"warning", "Filament not enough!",
									"Required on tool %d: %dg, available from Spool '%s': '%dg'" % (spoolSlot, requiredWeight, selectedSpool.displayName, remainingWeight)
								)
							notEnough = True
							overallNotEnough = True

						detailedSpoolResultItem = {
							"toolIndex": spoolSlot,
							"requiredWeight": requiredWeight,
							"requiredLength": filamentLength,
							"remainingWeight": remainingWeight,
							"diameter": diameter,
							"density": density,
							"notEnough": notEnough,
							"spoolSelected": True,
							"spoolName": selectedSpool.displayName
						}
						requiredWeightResultDict["detailedSpoolResult"].append(detailedSpoolResultItem)
			else:
				# No selected spool for this tool-index, just create an simple entry
				detailedSpoolResultItem = {
					"toolIndex": spoolSlot,
					"requiredLength": filamentLength,
					"spoolSelected": False,
					"spoolName": "not selected"
				}
				requiredWeightResultDict["detailedSpoolResult"].append(detailedSpoolResultItem)
				pass

		requiredWeightResultDict["attributesMissing"] = someAttributesMissing
		requiredWeightResultDict["notEnough"] = overallNotEnough

		return requiredWeightResultDict


	def _calculateWeight(self, length, diameter, density):
		radius = diameter / 2.0;
		volume = length * math.pi * (radius * radius) / 1000
		result = volume * density
		return result

	def _buildDatabaseSettingsFromPluginSettings(self):
		databaseSettings = DatabaseManager.DatabaseSettings()
		databaseSettings.useExternal = self._settings.get([SettingsKeys.SETTINGS_KEY_DATABASE_USE_EXTERNAL])
		databaseSettings.type = self._settings.get([SettingsKeys.SETTINGS_KEY_DATABASE_TYPE])
		databaseSettings.host = self._settings.get([SettingsKeys.SETTINGS_KEY_DATABASE_HOST])
		databaseSettings.port = self._settings.get_int([SettingsKeys.SETTINGS_KEY_DATABASE_PORT])
		databaseSettings.name = self._settings.get([SettingsKeys.SETTINGS_KEY_DATABASE_NAME])
		databaseSettings.user = self._settings.get([SettingsKeys.SETTINGS_KEY_DATABASE_USER])
		databaseSettings.password = self._settings.get([SettingsKeys.SETTINGS_KEY_DATABASE_PASSWORD])
		pluginDataBaseFolder = self.get_plugin_data_folder()
		databaseSettings.baseFolder = pluginDataBaseFolder
		databaseSettings.fileLocation = self._databaseManager.buildDefaultDatabaseFileLocation(databaseSettings.baseFolder)

		return databaseSettings

	# common states: STATE_CONNECTING("Connecting"), STATE_OPERATIONAL("Operational"),
	# STATE_STARTING("Startinf..."), STATE_PRINTING("Printing or Sendind"), STATE_CANCELLING("Cancelling"),
	# STATE_PAUSING("Pausing"), STATE_PAUSED("Paused"), STATE_RESUMING("Resuming"), STATE_FINISHING("Finishing"), STATE_CLOSED("Offline")
	# Normal flow:
	# - OPERATIONAL
	# - STARTING
	# - PRINTING
	# - FINISHING
	# - OPERATIONAL

	# Cancel
	# - ...
	# - PRINTING
	# -CANCELLING
	# - OPERATIONAL

	# Pause -> Resume
	# - STARTING
	# - PRINTING
	# - PAUSING
	# - PAUSED
	# - RESUMING
	# - PRINTING
	# - FINISHING
	# - OPERATIONAL


	# Pause -> Restart
	# - PRINTING
	# - PAUSING
	# - PAUSED
	# - STARTING
	# - PRINTING
	# - FINISHING
	# - OPERATIONAL

	def _on_printJobStarted(self):
		# starting new print

		# self._filamentOdometer.reset()
		self.myFilamentOdometer.reset()

		reloadTable = False
		selectedSpools = self.loadSelectedSpools()
		self._readingFilamentMetaData()
		for toolIndex, spoolSlot, spoolModel in self._getSpoolAccountingTargets(selectedSpools):
			if toolIndex >= len(self.metaDataFilamentLengths):
				continue

			if (spoolModel != None):
				if self._mmuRoutingSession.active and not self._mmuRoutingSession.dry_run:
					self.set_temp_offsets(toolIndex, spoolModel)
				if (StringUtils.isEmpty(spoolModel.firstUse) == True):
					firstUse = datetime.now()
					spoolModel.firstUse = firstUse
					self._databaseManager.saveSpool(spoolModel)
					reloadTable = True
		if reloadTable:
			self._sendDataToClient(dict(
									action="reloadTable"
									))
		try:
			self._storeObjectsInfoOnCurrentSheet()
		except Exception:
			self._logger.exception("Could not store objects_info on current sheet")
		# assign the current extrusion to the current selected spools

	def _getCurrentPrinterNumber(self):
		try:
			instanceName = octo_settings().get(["appearance", "name"])
			if (instanceName == None):
				return None
			m = re.search(r"#\s*(\d+)", str(instanceName))
			if (m != None):
				return int(m.group(1))
			instanceNameStr = str(instanceName).strip()
			if (instanceNameStr.isdigit()):
				return int(instanceNameStr)
			return None
		except Exception:
			return None

	def _getCurrentJobFile(self, selectedFile=None):
		# FileSelected already carries the authoritative storage location.  Use it
		# before consulting the printer snapshot, which can still describe the
		# previous/empty job while OctoPrint is dispatching the selection event.
		if (isinstance(selectedFile, dict)):
			origin = selectedFile.get("origin")
			path = selectedFile.get("path")
			name = selectedFile.get("name")
			if (origin != None and path != None):
				return origin, path, name
		try:
			data = self._printer.get_current_data()
			if (data == None or "job" not in data):
				return None, None, None
			jobData = data.get("job")
			if (jobData == None or "file" not in jobData):
				return None, None, None
			fileData = jobData.get("file")
			if (fileData == None):
				return None, None, None
			origin = fileData.get("origin")
			path = fileData.get("path")
			name = fileData.get("name")
			return origin, path, name
		except Exception:
			return None, None, None

	def _readFileTail(self, filePath, maxBytes):
		try:
			with open(filePath, "rb") as f:
				try:
					f.seek(0, 2)
					size = f.tell()
					start = max(0, size - int(maxBytes))
					f.seek(start, 0)
				except Exception:
					f.seek(0, 0)
				data = f.read()
			try:
				return data.decode("utf-8", errors="replace")
			except Exception:
				return data.decode(errors="replace")
		except Exception:
			return None

	def _extractObjectsInfoJson(self, text):
		try:
			matches = re.findall(r"^;\s*objects_info\s*=\s*(\{.*\})\s*$", text, flags=re.MULTILINE)
			if (matches == None or len(matches) == 0):
				return None
			return matches[-1]
		except Exception:
			return None

	def _aggregateObjectQuantities(self, objectsInfoJson):
		result = {}
		try:
			for m in re.finditer(r'"name"\s*:\s*"((?:\\\\.|[^"\\\\])*)"', objectsInfoJson):
				rawName = m.group(1)
				name = None
				try:
					name = json.loads('"' + rawName + '"')
				except Exception:
					name = rawName
				try:
					name = re.sub(r"\s*\(Instance\s+\d+\)\s*$", "", str(name))
				except Exception:
					pass
				try:
					name = re.sub(r"\.{3,}\s*$", "", str(name)).strip()
				except Exception:
					pass
				if (name == None or str(name).strip() == ""):
					continue
				result[name] = (result.get(name, 0) or 0) + 1
			return result
		except Exception:
			return {}

	def _storeObjectsInfoOnCurrentSheet(self):
		printerNumber = self._getCurrentPrinterNumber()
		if (printerNumber == None):
			return

		printerName = None
		try:
			printerName = octo_settings().get(["appearance", "name"])
		except Exception:
			printerName = None

		origin, path, name = self._getCurrentJobFile()
		if (origin == None or path == None):
			return
		if (origin != "local"):
			return

		gcodePath = None
		try:
			gcodePath = self._file_manager.path_on_disk(origin, path)
		except Exception:
			try:
				gcodePath = self._file_manager.pathOnDisk(origin, path)
			except Exception:
				gcodePath = None

		if (gcodePath == None):
			return

		marker = "; objects_info ="
		objectsInfoJson = None
		maxBytes = 1024 * 1024
		while maxBytes <= (32 * 1024 * 1024):
			tailText = self._readFileTail(gcodePath, maxBytes)
			if (tailText != None and marker in tailText):
				objectsInfoJson = self._extractObjectsInfoJson(tailText)
				if (objectsInfoJson != None):
					break
			maxBytes = maxBytes * 2

		quantities = {}
		if (objectsInfoJson != None):
			quantities = self._aggregateObjectQuantities(objectsInfoJson)

		objects = []
		try:
			for objectName in sorted(list(quantities.keys())):
				objects.append({
					"name": objectName,
					"quantity": int(quantities.get(objectName) or 0)
				})
		except Exception:
			pass

		selectedSpoolIds = []
		try:
			selectedSpoolIds = self._settings.get([SettingsKeys.SETTINGS_KEY_SELECTED_SPOOLS_DATABASE_IDS]) or []
		except Exception:
			selectedSpoolIds = []

		payload = {
			"printer": {
				"name": printerName,
				"number": printerNumber
			},
			"sheet": None,
			"spools": [],
			"sourceFile": {
				"origin": origin,
				"path": path,
				"name": name
			},
			"objects": objects
		}

		self._databaseManager.connectoToDatabase()
		try:
			selectedSpools = []
			selectedEntries = list(enumerate(selectedSpoolIds))
			if self._mmuRoutingSession.active and not self._mmuRoutingSession.dry_run:
				slot = self._mmuRoutingSession.slot
				selectedEntries = [(slot, selectedSpoolIds[slot])] if slot < len(selectedSpoolIds) else []
			for toolIndex, spoolId in selectedEntries:
				if (spoolId == None):
					continue
				try:
					spoolDatabaseId = int(spoolId)
				except Exception:
					continue

				spoolModel = self._databaseManager.loadSpool(spoolDatabaseId, withReusedConnection=True)
				selectedSpools.append({
					"toolIndex": int(toolIndex),
					"databaseId": spoolDatabaseId,
					"displayName": (None if spoolModel == None else spoolModel.displayName)
				})
			payload["spools"] = selectedSpools

			currentSheet, _ = self._databaseManager.getSheetsStateForPrinter(printerNumber, withReusedConnection=True)
			if (currentSheet != None):
				sheetTypeName = None
				try:
					if (currentSheet.sheetType != None):
						sheetTypeName = currentSheet.sheetType.name
				except Exception:
					sheetTypeName = None

				payload["sheet"] = {
					"databaseId": currentSheet.databaseId,
					"nid": currentSheet.nid,
					"sheetTypeName": sheetTypeName
				}

			payloadJson = None
			try:
				payloadJson = json.dumps(payload, ensure_ascii=False)
			except Exception:
				payloadJson = json.dumps(payload)

			self._databaseManager.setCurrentlyPrintingForPrinter(printerNumber, payloadJson, withReusedConnection=True)
		finally:
			self._databaseManager.closeDatabase()

	def commitOdometerData(self, printStatus=None):
		reload = False
		selectedSpools = self.loadSelectedSpools()
		for gcodeToolIndex, toolIndex, spoolModel in self._getSpoolAccountingTargets(selectedSpools):
			if spoolModel is None:
				self._logger.warning("Tool %d: No spool selected, could not update values after print" % toolIndex)
				continue

			# - Last usage datetime
			lastUsage = datetime.now()
			spoolModel.lastUse = lastUsage
			# - Used length
			currentExtrusionLengthOdometer = None
			try:
				allExtrusions = self.myFilamentOdometer.getExtrusionAmount()
				currentExtrusionLengthOdometer = allExtrusions[gcodeToolIndex]
			except (KeyError, IndexError) as e:
				pass

			currentExtrusionLengthMeta = None
			metadataTotalLength = None
			previouslyCommittedLength = float(self._committedPrintFilamentLengths.get(gcodeToolIndex, 0.0) or 0.0)
			if printStatus == "success":
				try:
					self._readingFilamentMetaData()
					if gcodeToolIndex < len(self.metaDataFilamentLengths):
						metadataTotalLength = self.metaDataFilamentLengths[gcodeToolIndex]
						if (
							gcodeToolIndex == 0
							and self._mmuRoutingSession.active
							and not self._mmuRoutingSession.dry_run
						):
							metadataTotalLength += self._mmuRoutingSession.extra_purge_mm
						currentExtrusionLengthMeta = remaining_metadata_length(metadataTotalLength, previouslyCommittedLength)
				except Exception:
					currentExtrusionLengthMeta = None

			calculationSource = "odometer"
			currentExtrusionLength = currentExtrusionLengthOdometer
			if printStatus == "success" and currentExtrusionLengthMeta is not None and currentExtrusionLengthMeta > 0:
				calculationSource = "metadata"
				currentExtrusionLength = currentExtrusionLengthMeta

			if currentExtrusionLength is None:
				self._logger.info("Tool %d: No filament extruded" % toolIndex)
				continue
			self._logger.info(
				"Tool %d: Extruded filament length: %s (source=%s, odometer=%s, metadata=%s)"
				% (toolIndex, str(currentExtrusionLength), calculationSource, str(currentExtrusionLengthOdometer), str(currentExtrusionLengthMeta))
			)
			spoolUsedLength = 0.0 if StringUtils.isEmpty(spoolModel.usedLength) == True else spoolModel.usedLength
			self._logger.info("Tool %d: Current Spool used filament length: %s" % (toolIndex, str(spoolUsedLength)))
			newUsedLength = spoolUsedLength + currentExtrusionLength
			self._logger.info("Tool %d: New Spool used filament length: %s" % (toolIndex, str(newUsedLength)))
			spoolModel.usedLength = newUsedLength
			# - Used weight
			diameter = spoolModel.diameter
			density = spoolModel.density
			usedWeight = None
			if diameter is None or density is None:
				self._logger.warning(
					"Tool %d: Could not update spool weight, because diameter or density not set in spool '%s'" % (toolIndex, spoolModel.displayName)
				)
			else:
				usedWeight = self._calculateWeight(currentExtrusionLength, diameter, density)
				spoolUsedWeight = 0.0 if spoolModel.usedWeight == None else spoolModel.usedWeight
				newUsedWeight = spoolUsedWeight + usedWeight
				spoolModel.usedWeight = newUsedWeight
				self._logger.info("Tool %d: spoolUsedWeight: %s" % (toolIndex, str(spoolUsedWeight)))
				self._logger.info("Tool %d: New spoolUsedWeight: %s" % (toolIndex, str(newUsedWeight)))

			self._databaseManager.saveSpool(spoolModel)

			if printStatus in (None, "paused") and currentExtrusionLength is not None:
				self._committedPrintFilamentLengths[gcodeToolIndex] = previouslyCommittedLength + max(0.0, float(currentExtrusionLength))

			eventPayload = {
				"toolId": toolIndex,
				"databaseId": spoolModel.databaseId,
				"spoolName": spoolModel.displayName,
				"material": spoolModel.material,
				"colorName": spoolModel.colorName,
				"remainingWeight": spoolModel.remainingWeight,
				"usedLengthThisPrint": currentExtrusionLength,
				"usedWeightThisPrint": usedWeight,
				"calculationSource": calculationSource,
				"odometerLengthThisPrint": currentExtrusionLengthOdometer,
				"metadataLengthThisPrint": currentExtrusionLengthMeta,
				"metadataTotalLength": metadataTotalLength,
				"previouslyCommittedLength": previouslyCommittedLength
			}
			self._sendPayload2EventBus(EventBusKeys.EVENT_BUS_SPOOL_WEIGHT_UPDATED_AFTER_PRINT, eventPayload)

			reload = True

		self.myFilamentOdometer.reset_extruded_length()
		if printStatus not in (None, "paused"):
			self._committedPrintFilamentLengths = {}

		if reload:
			self._sendDataToClient(dict(
				action="reloadTable and sidebarSpools"
			))

	#### print job finished
	def _on_printJobFinished(self, printStatus, payload):
		self.commitOdometerData(printStatus)

		if (self._mmuRoutingSession.active and not self._mmuRoutingSession.dry_run):
			if (printStatus == "success"):
				if (self._mmuRoutingSession.unload_at_end and self._mmuRoutingSession.unload_injected):
					if self._mmuLoadedState != STATE_UNLOADED:
						self._setMmuLoadedState(STATE_UNKNOWN, None, "print_done_unload_unconfirmed")
				elif (not self._mmuRoutingSession.unload_at_end):
					if not (self._mmuLoadedState == STATE_LOADED and self._mmuLoadedSlot == self._mmuRoutingSession.slot):
						self._setMmuLoadedState(STATE_UNKNOWN, None, "print_done_load_unconfirmed")
				else:
					self._setMmuLoadedState(STATE_UNKNOWN, None, "print_done_ambiguous")
			elif (printStatus != "paused"):
				self._setMmuLoadedState(STATE_UNKNOWN, None, "print_%s" % str(printStatus))

		# update remaining data in selected spools after a print
		selectedSpools = self.loadSelectedSpools()
		requiredWeightResult = self._evaluateRequiredWeight(selectedSpools, None, False)
		requiredWeightResult["action"] = "requiredFilamentChanged"
		self._sendDataToClient(requiredWeightResult)

		if ("paused" != printStatus):
			self.clear_temp_offsets()

	def _on_clientOpened(self, payload):
		# start-workaround https://github.com/foosel/OctoPrint/issues/3400
		import time
		time.sleep(3)
		selectedSpoolsAsDicts = []

		# Check if database is available
		# connected = self._databaseManager.reConnectToDatabase()
		# self._logger.info("ClientOpened. Database connected:"+str(connected))

		connectionErrorResult = self._databaseManager.testDatabaseConnection()

		# Don't show already shown message
		if (self.databaseConnectionProblemConfirmed == False and
			connectionErrorResult != None):
			databaseErrorMessageDict = self._databaseManager.getCurrentErrorMessageDict();
			# The databaseErrorMessages should always be present in that case.
			if (databaseErrorMessageDict != None):
				self._logger.error(databaseErrorMessageDict)
				self._sendDataToClient(dict(action = "showConnectionProblem",
											type = databaseErrorMessageDict["type"],
											title = databaseErrorMessageDict["title"],
											message = databaseErrorMessageDict["message"]))

		# Send plugin storage information
		## Storage
		if (connectionErrorResult == None):
			selectedSpoolsAsDicts = [
				(None if selectedSpool is None else Transformer.transformSpoolModelToDict(selectedSpool))
				for selectedSpool in self.loadSelectedSpools()
			]

		pluginNotWorking = connectionErrorResult != None
		self._sendDataToClient(dict(action = "initalData",
									selectedSpools = selectedSpoolsAsDicts,
									isFilamentManagerPluginAvailable = self._filamentManagerPluginImplementation != None,
									pluginNotWorking = pluginNotWorking
									))
		# data for the sidebar
		self.checkRemainingFilament()
		pass

	def _on_clientClosed(self, payload):
		self.databaseConnectionProblemConfirmed = False

	def _on_file_selectionChanged(self, payload):
		try:
			self._prepareMmuRoutingForCurrentJob(enforceGuard=False, selectedFile=payload)
		except Exception:
			self._logger.exception("Could not prepare MMU routing after file selection change")
		self.checkRemainingFilament()
	pass


	######################################################################################### PUBLIC IMPLEMENTATION API
	def api_getSelectedSpoolInformations(self):
		"""
		Returns the current extruded filament for each tool
		:param string path:
		:return: array of spoolData-object ....
		"""
		spoolModels = self.loadSelectedSpools()
		result = []
		toolIndex = 0
		while toolIndex < len(spoolModels):
			spoolModel = spoolModels[toolIndex]
			spoolData = None
			if (spoolModel != None):
				spoolData = {
					"toolIndex": toolIndex,
					"databaseId": spoolModel.databaseId,
					"spoolName": spoolModel.displayName,
					"vendor": spoolModel.vendor,
					"project":spoolModel.project,
					"material": spoolModel.material,
					"diameter": spoolModel.diameter,
					"density": spoolModel.density,
					"colorName": spoolModel.colorName,
					"color": spoolModel.color,
					"cost": spoolModel.cost,
					"weight": spoolModel.totalWeight
				}
			result.append(spoolData)

			toolIndex += 1
		return result

	def api_getExtrusionAmount(self):
		"""
		Returns the current extruded filament for each tool
		:param string path:
		:return: array of ....
		"""
		return self.myFilamentOdometer.getExtrusionAmount()
		pass


	######################################################################################### Hooks and public functions

	def on_after_startup(self):
		# check if needed plugins were available
		self._checkForMissingPluginInfos()
		pass

	def _migrateMmuRoutingSettings(self):
		"""Correct the unsafe legacy prototype distance without touching custom values."""
		try:
			configured = float(self._settings.get([SettingsKeys.SETTINGS_KEY_MMU_LOAD_DISTANCE]) or LEGACY_LOAD_DISTANCE_MM)
			if abs(configured - LEGACY_LOAD_DISTANCE_MM) < 0.0001:
				self._settings.set([SettingsKeys.SETTINGS_KEY_MMU_LOAD_DISTANCE], DEFAULT_LOAD_DISTANCE_MM)
				self._settings.save()
				self._logger.warning(
					"Migrated MMU load distance from unsafe prototype value %.1f mm to MK4 MMU3 profile value %.1f mm",
					LEGACY_LOAD_DISTANCE_MM,
					DEFAULT_LOAD_DISTANCE_MM
				)
		except Exception:
			self._logger.exception("Could not migrate MMU routing settings")

	def _setMmuPendingAction(self, action, slot=None, source="unknown"):
		action = str(action or "").upper() or None
		if action not in ("LOADING", "UNLOADING"):
			action = None
		try:
			slot = None if slot is None else int(slot)
		except Exception:
			slot = None
		if action == "LOADING" and slot is None:
			slot = self._mmuRoutingSession.slot
		# Only a command deliberately sent by this plugin starts a new action
		# whose result may become trusted. Progress lines after an MMU error are
		# retries of the uncertain action and must not clear that uncertainty.
		if source == "gcode_sent":
			self._mmuActionUncertain = False
		if self._mmuPendingAction != action or self._mmuPendingSlot != slot:
			self._logger.info(
				"MMU action transition: action=%s slot=%s source=%s",
				str(action), str(slot), str(source)
			)
		self._mmuPendingAction = action
		self._mmuPendingSlot = slot

	def _setMmuLoadedState(self, state, slot=None, source="unknown"):
		state = str(state or STATE_UNKNOWN).upper()
		if state not in (STATE_UNKNOWN, STATE_UNLOADED, STATE_LOADED):
			state = STATE_UNKNOWN
		try:
			slot = None if slot is None else int(slot)
		except Exception:
			slot = None
		if state != STATE_LOADED or slot is None or slot < 0 or slot > 4:
			if state == STATE_LOADED:
				state = STATE_UNKNOWN
			slot = None
		oldState = self._mmuLoadedState
		oldSlot = self._mmuLoadedSlot
		self._mmuLoadedState = state
		self._mmuLoadedSlot = slot
		self._mmuPendingAction = None
		self._mmuPendingSlot = None
		self._mmuStateSource = str(source or "unknown")
		self._mmuStateUpdatedAt = datetime.now()
		if state != STATE_UNKNOWN:
			self._mmuActionUncertain = False
		if oldState != state or oldSlot != slot:
			self._logger.info(
				"MMU loaded-state transition: %s/%s -> %s/%s source=%s",
				str(oldState), str(oldSlot), str(state), str(slot), str(source)
			)
			try:
				self._sendDataToClient(dict(
					action="mmuRoutingStateChanged",
					loadedState=state,
					loadedSlot=slot,
					loadedStateSource=self._mmuStateSource
				))
			except Exception:
				self._logger.debug("Could not publish MMU state transition to clients", exc_info=True)

	def _parseMmuTool(self, value):
		try:
			text = str(value).strip().upper()
			if text.startswith("T"):
				text = text[1:]
			tool = int(text, 16)
			return tool if 0 <= tool <= 4 else None
		except Exception:
			return None

	def _handlePrusaMmuEvent(self, payload):
		data = payload if isinstance(payload, dict) else {}
		state = str(data.get("state") or "").upper()
		tool = self._parseMmuTool(data.get("tool"))
		if state == "LOADING":
			self._setMmuPendingAction("LOADING", tool, "prusammu_event")
		elif state == "LOADED":
			confirmedSlot = tool if tool is not None else self._mmuPendingSlot
			completedState, completedSlot = mmu_completion_state(
				"LOADING", confirmedSlot, self._mmuActionUncertain
			)
			self._setMmuLoadedState(completedState, completedSlot, "prusammu_event")
		elif state in ("UNLOADING", "UNLOADING_FINAL"):
			self._setMmuPendingAction("UNLOADING", self._mmuLoadedSlot, "prusammu_event")
		elif (state == "OK" and self._mmuPendingAction == "UNLOADING"
				and str(data.get("responseData") or "").lower() == "2"):
			completedState, completedSlot = mmu_completion_state(
				"UNLOADING", None, self._mmuActionUncertain
			)
			self._setMmuLoadedState(completedState, completedSlot, "prusammu_event")
		elif state in ("ATTENTION", "PAUSED_USER") and self._mmuPendingAction is not None:
			self._mmuActionUncertain = True
			self._setMmuLoadedState(STATE_UNKNOWN, None, "prusammu_event_error")

	def _handleMmuSerialLine(self, line):
		transition = classify_mmu_serial_line(line)
		if transition == "LOADING":
			targetSlot = self._mmuRoutingSession.slot if self._mmuRoutingSession.active else self._mmuPendingSlot
			self._setMmuPendingAction("LOADING", targetSlot, "serial")
		elif transition == "UNLOADING":
			self._setMmuPendingAction("UNLOADING", self._mmuLoadedSlot, "serial")
		elif transition == "ACTION_DONE":
			if self._mmuPendingAction in ("LOADING", "UNLOADING"):
				completedState, completedSlot = mmu_completion_state(
					self._mmuPendingAction, self._mmuPendingSlot, self._mmuActionUncertain
				)
				completionSource = "serial_after_error" if self._mmuActionUncertain else "serial"
				self._setMmuLoadedState(completedState, completedSlot, completionSource)
		elif transition == "ERROR" and self._mmuPendingAction is not None:
			self._mmuActionUncertain = True
			self._setMmuLoadedState(STATE_UNKNOWN, None, "serial_error")

	def on_receivedGCodeHook(self, comm_instance, line, *args, **kwargs):
		try:
			self._handleMmuSerialLine(line)
		except Exception:
			self._logger.exception("Could not process MMU serial response")
		return line

	def _getContinuousPrintNextPath(self):
		try:
			pluginInfo = None
			for pluginId in ("continuousprint", "ContinuousPrint"):
				pluginInfo = self._plugin_manager.plugins.get(pluginId)
				if pluginInfo != None:
					break
			if pluginInfo == None or not pluginInfo.enabled:
				return None
			implementation = pluginInfo.implementation
			# ContinuousPrint 2.4.x exposes an OctoPrint-facing wrapper here; its
			# queue, driver and API state live on the wrapped CPQPlugin instance.
			implementation = getattr(implementation, "_plugin", implementation)
			if implementation == None or not hasattr(implementation, "_state_json"):
				return None
			activeSetId = None
			activeQueueName = None
			currentPath = None
			queueManager = getattr(implementation, "q", None)
			if (queueManager != None):
				activeSet = queueManager.get_set() if hasattr(queueManager, "get_set") else None
				if (activeSet != None):
					activeSetId = getattr(activeSet, "id", None)
					currentPath = getattr(activeSet, "path", None)
				activeQueue = getattr(queueManager, "active_queue", None)
				if (activeQueue != None):
					activeQueueName = getattr(activeQueue, "ns", None) or getattr(activeQueue, "name", None)
			state = implementation._state_json()
			if not isinstance(state, dict):
				state = json.loads(state)
			return continuousprint_next_path(
				state,
				active_set_id=activeSetId,
				active_queue_name=activeQueueName,
				current_path=currentPath
			)
		except Exception as e:
			self._logger.warning("ContinuousPrint lookahead unavailable; MMU will unload: %s", str(e))
			return None

	def _prepareMmuRoutingForCurrentJob(self, enforceGuard=False, selectedFile=None):
		self._mmuRoutingSession.reset()
		enabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_MMU_ROUTING_ENABLED])
		dryRun = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_MMU_ROUTING_DRY_RUN])
		try:
			configuredPrinter = int(self._settings.get([SettingsKeys.SETTINGS_KEY_MMU_PRINTER_NUMBER]) or 5)
		except Exception:
			configuredPrinter = 5
		currentPrinter = self._getCurrentPrinterNumber()
		if (not enabled or currentPrinter != configuredPrinter):
			return

		origin, path, name = self._getCurrentJobFile(selectedFile=selectedFile)
		gcodePath = None
		if (origin == "local" and path != None):
			try:
				gcodePath = self._file_manager.path_on_disk(origin, path)
			except Exception:
				try:
					gcodePath = self._file_manager.pathOnDisk(origin, path)
				except Exception:
					gcodePath = None

		# Always retain built-in maintenance jobs when upgrading an installation
		# whose saved list predates newly added Jobox actions.
		bypassFiles = maintenance_bypass_files(
			self._settings.get([SettingsKeys.SETTINGS_KEY_MMU_BYPASS_FILES])
		)
		# ContinuousPrint automation scripts are temporary real print jobs, not
		# material-bearing models. Check the storage path before the basename so
		# its private automation directory can be recognized safely.
		bypassReason = routing_bypass_reason(path or name, allowed_names=bypassFiles)
		if (bypassReason == None and gcodePath != None):
			try:
				bypassReason = routing_bypass_reason_file(
					gcodePath,
					name=name or path,
					allowed_names=bypassFiles
				)
			except Exception as e:
				self._logger.warning("Could not inspect routing bypass marker in %s: %s", str(name or path), str(e))
		if (bypassReason != None):
			self._mmuRoutingSession.configure_bypass(enabled, dryRun, bypassReason)
			self._logger.info(
				"MMU routing bypass: file=%s reason=%s state=%s loadedSlot=%s",
				str(name or path), str(bypassReason), str(self._mmuLoadedState), str(self._mmuLoadedSlot)
			)
			return

		contract = None
		if (gcodePath != None):
			try:
				contract = parse_contract_file(gcodePath)
				templateErrors = runtime_template_errors_file(gcodePath)
				if (contract.get("valid") and len(templateErrors) > 0):
					contract["valid"] = False
					contract["error"] = "unsupported runtime template: " + ", ".join(templateErrors)
			except Exception as e:
				self._logger.warning("Could not read SpoolManager contract from %s: %s", str(name or path), str(e))
		if (contract == None):
			contract = {"valid": False, "error": "contract_not_found"}

		slotIds = self._getMmuSlotSpoolIds()
		slots = []
		self._databaseManager.connectoToDatabase()
		try:
			for slotIndex in range(5):
				spool = None
				spoolId = slotIds[slotIndex] if slotIndex < len(slotIds) else None
				if (spoolId != None):
					try:
						spool = self._databaseManager.loadSpool(spoolId, withReusedConnection=True)
					except Exception:
						spool = None
				slots.append(build_slot(slotIndex, spool))
		finally:
			self._databaseManager.closeDatabase()

		try:
			reserveWeight = float(self._settings.get([SettingsKeys.SETTINGS_KEY_MMU_RESERVE_WEIGHT]) or 0)
		except Exception:
			reserveWeight = 0.0
		loadedSlot = self._mmuLoadedSlot if self._mmuLoadedState == STATE_LOADED else None
		decision = select_slot(contract, slots, loaded_slot=loadedSlot, reserve_g=reserveWeight)
		try:
			loadDistance = float(self._settings.get([SettingsKeys.SETTINGS_KEY_MMU_LOAD_DISTANCE]) or DEFAULT_LOAD_DISTANCE_MM)
		except Exception:
			loadDistance = DEFAULT_LOAD_DISTANCE_MM
		try:
			purgePasses = int(self._settings.get([SettingsKeys.SETTINGS_KEY_MMU_PURGE_PASSES]) or DEFAULT_PURGE_PASSES)
		except Exception:
			purgePasses = DEFAULT_PURGE_PASSES
		unloadLiftZ = None
		if (gcodePath != None):
			try:
				unloadLiftZ = unload_lift_target_file(gcodePath)
			except Exception as e:
				self._logger.warning("Could not calculate capped MMU unload lift for %s: %s", str(name or path), str(e))

		unloadAtEnd = True
		nextPath = self._getContinuousPrintNextPath()
		if (nextPath != None):
			nextGcodePath = None
			try:
				nextGcodePath = self._file_manager.path_on_disk("local", nextPath)
			except Exception:
				try:
					nextGcodePath = self._file_manager.pathOnDisk("local", nextPath)
				except Exception:
					nextGcodePath = None
			if (nextGcodePath != None):
				try:
					nextContract = parse_contract_file(nextGcodePath)
					nextTemplateErrors = runtime_template_errors_file(nextGcodePath)
					if (len(nextTemplateErrors) == 0):
						unloadAtEnd = not should_retain_for_next(
							contract,
							decision,
							nextContract,
							slots,
							reserve_g=reserveWeight
						)
				except Exception as e:
					self._logger.warning("Could not verify next ContinuousPrint contract; MMU will unload: %s", str(e))
		self._mmuRoutingSession.configure(
			enabled,
			dryRun,
			contract,
			decision,
			loaded_state=self._mmuLoadedState,
			loaded_slot=self._mmuLoadedSlot,
			unload_at_end=unloadAtEnd,
			load_distance_mm=loadDistance,
			purge_passes=purgePasses,
			unload_lift_z=unloadLiftZ
		)

		self._logger.info(
			"MMU routing decision: file=%s dryRun=%s contract=%s decision=%s nextPath=%s unloadAtEnd=%s purgePasses=%s state=%s loadedSlot=%s active=%s error=%s",
			str(name or path), str(dryRun), str(contract), str(decision), str(nextPath),
			str(unloadAtEnd), str(self._mmuRoutingSession.purge_passes), str(self._mmuLoadedState), str(self._mmuLoadedSlot), str(self._mmuRoutingSession.active), str(self._mmuRoutingSession.error)
		)

		if (not dryRun and enforceGuard and not self._mmuRoutingSession.allow_print):
			self._logger.error("MMU hardware routing guard rejected print: %s", str(self._mmuRoutingSession.error))
			try:
				self._printer.cancel_print()
			except Exception:
				self._logger.exception("Could not cancel print rejected by MMU routing guard")

	def on_atcommand_queuing(self, comm_instance, phase, command, parameters, tags=None, *args, **kwargs):
		if (str(command or "").strip().upper() == "SPOOLMANAGER"):
			self._mmuRoutingSession.handle_marker(parameters)

	def on_queuingGCodeHook(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		return self._mmuRoutingSession.rewrite(cmd)

	# Listen to all  g-code which where already sent to the printer (thread: comm.sending_thread)
	def on_sentGCodeHook(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):

		# TODO maybe later via a queue
		# self._filamentOdometer.parse(gcode, cmd)
		cmdUpper = str(cmd).upper() if cmd != None else ""
		tags = kwargs.get("tags")
		if tags == None:
			for arg in reversed(args):
				if isinstance(arg, (set, list, tuple)):
					tags = arg
					break
		tags = set(tags or [])
		isMmuTransport = "spoolmanager:mmu_transport" in tags or "SM_PURPOSE=MMU_TRANSPORT" in cmdUpper
		isMmuSelect = "spoolmanager:mmu_select" in tags or "SM_PURPOSE=MMU_SELECT" in cmdUpper
		isMmuRecovery = "spoolmanager:mmu_recovery" in tags or "SM_PURPOSE=MMU_RECOVERY" in cmdUpper
		isMmuUnload = "spoolmanager:mmu_unload" in tags or "SM_PURPOSE=MMU_UNLOAD" in cmdUpper
		if (self._mmuRoutingSession.active and isMmuSelect):
			self._setMmuPendingAction("LOADING", self._mmuRoutingSession.slot, "gcode_sent")
		elif (self._mmuRoutingSession.active and (isMmuRecovery or isMmuUnload)):
			self._setMmuPendingAction("UNLOADING", self._mmuLoadedSlot, "gcode_sent")
		elif (isMmuTransport and self._mmuRoutingSession.active):
			self._logger.debug("MMU transport sent; waiting for firmware confirmation before marking slot loaded")
		if (should_count_for_odometer(cmd, tags)):
			self.myFilamentOdometer.processGCodeLine(cmd)

		try:
			if ("SM_PLATE_LOADED" in cmdUpper):
				self._logger.info("Detected SM_PLATE_LOADED marker in sent gcode: %s", str(cmd))
				threading.Thread(target=self._onPlateLoadedMarker, daemon=True).start()
		except Exception:
			self._logger.exception("Error while processing sent gcode hook")
		# if self.pauseEnabled and self.check_threshold():
		# 	self._logger.info("Filament is running out, pausing print")
		# 	self._printer.pause_print()
		pass

	def _onPlateLoadedMarker(self):
		try:
			instanceName = None
			try:
				instanceName = octo_settings().get(["appearance", "name"])
			except Exception:
				instanceName = None

			printerNumber = self._getCurrentPrinterNumber()
			if (printerNumber == None):
				self._logger.warning("SM_PLATE_LOADED ignored because printerNumber could not be determined from appearance.name=%s", str(instanceName))
				return

			self._logger.info("Handling SM_PLATE_LOADED for printerNumber=%s (appearance.name=%s)", str(printerNumber), str(instanceName))

			self._databaseManager.connectoToDatabase()
			try:
				oldCurrent, newCurrent = self._databaseManager.advanceSheetFromMagazineToCurrent(printerNumber, withReusedConnection=True)
				oldPayload = None if oldCurrent == None else Transformer.transformSheetModelToDict(oldCurrent)
				newPayload = None if newCurrent == None else Transformer.transformSheetModelToDict(newCurrent)
			finally:
				self._databaseManager.closeDatabase()

			self._logger.info(
				"SM_PLATE_LOADED advance result: oldCurrent=%s newCurrent=%s",
				str(None if oldPayload == None else oldPayload.get("databaseId")),
				str(None if newPayload == None else newPayload.get("databaseId"))
			)

			try:
				if (oldPayload != None):
					self._sendPayload2EventBus(EventBusKeys.EVENT_BUS_SHEET_UNASSIGNED, {
						"databaseId": oldPayload.get("databaseId"),
						"nid": oldPayload.get("nid")
					})
				if (newPayload != None):
					self._sendPayload2EventBus(EventBusKeys.EVENT_BUS_SHEET_ASSIGNED, {
						"databaseId": newPayload.get("databaseId"),
						"nid": newPayload.get("nid"),
						"printerNumber": newPayload.get("printerNumber"),
						"magazinePosition": newPayload.get("magazinePosition")
					})
			except Exception:
				self._logger.exception("Failed sending sheet events after SM_PLATE_LOADED")

			try:
				self._sendDataToClient(dict(action="reloadSheets"))
			except Exception:
				self._logger.exception("Failed sending reloadSheets after SM_PLATE_LOADED")
		except Exception:
			self._logger.exception("Unhandled error in _onPlateLoadedMarker")

	def on_event(self, event, payload):
		if event in ("plugin_prusammu_mmu_change", "plugin_prusammu_mmu_changed"):
			self._handlePrusaMmuEvent(payload)
			return

		if event in (getattr(Events, "DISCONNECTED", "Disconnected"), getattr(Events, "ERROR", "Error")):
			self._setMmuLoadedState(STATE_UNKNOWN, None, "printer_%s" % str(event).lower())
			return

		# if (event != "RegisteredMessageReceived"):
		# 	print("*** EVENT: " + event)
		#
		# if ("plugin_spoolmanager" in event):
		# 	print(payload)
		# 	pass

		if (Events.CLIENT_OPENED == event):
			self._on_clientOpened(payload)
			return
		if (Events.CLIENT_CLOSED == event):
			self._on_clientClosed(payload)
			return

		elif (Events.PRINT_STARTED == event):
			self.alreadyCanceled = False
			self._committedPrintFilamentLengths = {}
			self._prepareMmuRoutingForCurrentJob(enforceGuard=True, selectedFile=payload)
			self._on_printJobStarted()

		elif (Events.PRINT_PAUSED == event):
			self._on_printJobFinished("paused", payload)

		elif (Events.PRINT_DONE == event):
			self._on_printJobFinished("success", payload)

		elif (Events.PRINT_FAILED == event):
			if self.alreadyCanceled == False:
				self._on_printJobFinished("failed", payload)

		elif (Events.PRINT_CANCELLED == event):
			self.alreadyCanceled = True
			self._on_printJobFinished("canceled", payload)

		if (Events.FILE_SELECTED == event or
			Events.FILE_DESELECTED == event or
			Events.UPDATED_FILES == event):
			self._on_file_selectionChanged(payload)
			return

		pass


	def on_settings_save(self, data):
		# Enable cleaning up any offsets that are turned off
		oldToolOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_TOOL_OFFSET_ENABLED])
		oldBedOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_BED_OFFSET_ENABLED])
		oldEnclosureOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_ENCLOSURE_OFFSET_ENABLED])
		if SettingsKeys.SETTINGS_KEY_MMU_PURGE_PASSES in data:
			try:
				purgePasses = int(data.get(SettingsKeys.SETTINGS_KEY_MMU_PURGE_PASSES))
			except Exception:
				purgePasses = DEFAULT_PURGE_PASSES
			data[SettingsKeys.SETTINGS_KEY_MMU_PURGE_PASSES] = max(1, min(3, purgePasses))

		# # default save function
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		# Clean up any offsets that are turned off
		newToolOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_TOOL_OFFSET_ENABLED])
		newBedOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_BED_OFFSET_ENABLED])
		newEnclosureOffsetEnabled = self._settings.get_boolean([SettingsKeys.SETTINGS_KEY_ENCLOSURE_OFFSET_ENABLED])

		offsetCleanup = False
		offset_dict = dict()
		if newToolOffsetEnabled == False and oldToolOffsetEnabled == True:
			offsetCleanup = True
			offset_dict["tool0"] = 0
		if newBedOffsetEnabled == False and oldBedOffsetEnabled == True:
			offsetCleanup = True
			offset_dict["bed"] = 0
		if newEnclosureOffsetEnabled == False and oldEnclosureOffsetEnabled == True:
			offsetCleanup = True
			offset_dict["chamber"] = 0

		if offsetCleanup :
			self._printer.set_temperature_offset(offset_dict)

		# Update Temperature Offsets
		selectedSpools = self.loadSelectedSpools()
		self._readingFilamentMetaData()
		for toolIndex, filamentLength in enumerate(self.metaDataFilamentLengths):
			selectedSpool = selectedSpools[toolIndex] if toolIndex < len(selectedSpools) else None
			if (selectedSpool != None):
				self.set_temp_offsets(toolIndex, selectedSpool)

		# In case we are switching between internal and external storage
		databaseSettings = self._buildDatabaseSettingsFromPluginSettings()
		self._databaseManager.assignNewDatabaseSettings(databaseSettings)
		# testResult = self._databaseManager.testDatabaseConnection(databaseSettings)
		# if (testResult != None):
		# 	# TODO Send to client
		# 	pass


	# to allow the frontend to trigger an update
	def on_api_get(self, request):
		if len(request.values) != 0:
			action = request.values["action"]

			# deceide if you want the reset function in you settings dialog
			if "isResetSettingsEnabled" == action:
				return flask.jsonify(enabled="true")

			if "resetSettings" == action:
				self._settings.set([], self.get_settings_defaults())
				self._settings.save()
				return flask.jsonify(self.get_settings_defaults())

			# because of some race conditions, we can't push the initalDate during client-open event. So we provide the settings on request
			if "additionalSettingsValues" == action:
				return flask.jsonify({
					"isFilamentManagerPluginAvailable":self._filamentManagerPluginImplementation != None
				})

	##~~ SettingsPlugin mixin
	def get_settings_defaults(self):

		settings = dict(
			installed_version=self._plugin_version
		)

		# Not visible
		settings[SettingsKeys.SETTINGS_KEY_SELECTED_SPOOLS_DATABASE_IDS] = []
		settings[SettingsKeys.SETTINGS_KEY_HIDE_EMPTY_SPOOL_IN_SIDEBAR] = False
		settings[SettingsKeys.SETTINGS_KEY_HIDE_INACTIVE_SPOOL_IN_SIDEBAR] = True
		settings[SettingsKeys.SETTINGS_KEY_SHOW_SHEET_MAGAZINE_IN_SIDEBAR] = True
		## Genral
		settings[SettingsKeys.SETTINGS_KEY_REMINDER_SELECTING_SPOOL] = True
		settings[SettingsKeys.SETTINGS_KEY_WARN_IF_SPOOL_NOT_SELECTED] = True
		settings[SettingsKeys.SETTINGS_KEY_WARN_IF_FILAMENT_NOT_ENOUGH] = True
		settings[SettingsKeys.SETTINGS_KEY_CURRENCY_SYMBOL] = "€"
		settings[SettingsKeys.SETTINGS_KEY_SAFETY_LENGTH] = 0

		## QR-Code
		settings[SettingsKeys.SETTINGS_KEY_QR_CODE_ENABLED] = True
		settings[SettingsKeys.SETTINGS_KEY_QR_CODE_USE_URL_PREFIX] = False
		settings[SettingsKeys.SETTINGS_KEY_QR_CODE_URL_PREFIX] = None
		settings[SettingsKeys.SETTINGS_KEY_QR_CODE_FILL_COLOR] = "#000000"
		settings[SettingsKeys.SETTINGS_KEY_QR_CODE_BACKGROUND_COLOR] = "#ffffff"
		settings[SettingsKeys.SETTINGS_KEY_QR_CODE_WIDTH] = "100"
		settings[SettingsKeys.SETTINGS_KEY_QR_CODE_HEIGHT] = "100"

		## Export / Import
		settings[SettingsKeys.SETTINGS_KEY_IMPORT_CSV_MODE] = SettingsKeys.KEY_IMPORTCSV_MODE_APPEND

		## Temperature
		settings[SettingsKeys.SETTINGS_KEY_TOOL_OFFSET_ENABLED] = False
		settings[SettingsKeys.SETTINGS_KEY_BED_OFFSET_ENABLED] = False
		settings[SettingsKeys.SETTINGS_KEY_ENCLOSURE_OFFSET_ENABLED] = False

		## Debugging
		settings[SettingsKeys.SETTINGS_KEY_SQL_LOGGING_ENABLED] = False
		settings[SettingsKeys.SETTINGS_KEY_EXTRUSION_DEBUGGING_ENABLED] = False

		## MMU single-nozzle routing. Hardware movement stays opt-in and dry-run by default.
		settings[SettingsKeys.SETTINGS_KEY_MMU_ROUTING_ENABLED] = False
		settings[SettingsKeys.SETTINGS_KEY_MMU_ROUTING_DRY_RUN] = True
		settings[SettingsKeys.SETTINGS_KEY_MMU_PRINTER_NUMBER] = 5
		settings[SettingsKeys.SETTINGS_KEY_MMU_RESERVE_WEIGHT] = 0.0
		settings[SettingsKeys.SETTINGS_KEY_MMU_LOAD_DISTANCE] = DEFAULT_LOAD_DISTANCE_MM
		settings[SettingsKeys.SETTINGS_KEY_MMU_PURGE_PASSES] = DEFAULT_PURGE_PASSES
		settings[SettingsKeys.SETTINGS_KEY_MMU_BYPASS_FILES] = list(DEFAULT_MAINTENANCE_BYPASS_FILES)

		## Database
		## nested settings are not working, because if only a few attributes are changed it only returns these few attribuets, instead the default values + adjusted values
		settings[SettingsKeys.SETTINGS_KEY_DATABASE_USE_EXTERNAL] = False
		datbaseLocation = DatabaseManager.buildDefaultDatabaseFileLocation(self.get_plugin_data_folder())
		settings[SettingsKeys.SETTINGS_KEY_DATABASE_LOCAL_FILELOCATION] = datbaseLocation
		settings[SettingsKeys.SETTINGS_KEY_DATABASE_TYPE] = "sqlite"
		# settings[SettingsKeys.SETTINGS_KEY_DATABASE_TYPE] = "postgres"
		settings[SettingsKeys.SETTINGS_KEY_DATABASE_HOST] = "localhost"
		settings[SettingsKeys.SETTINGS_KEY_DATABASE_PORT] = 5432
		settings[SettingsKeys.SETTINGS_KEY_DATABASE_NAME] = "SpoolDatabase"
		settings[SettingsKeys.SETTINGS_KEY_DATABASE_USER] = "Olli"
		settings[SettingsKeys.SETTINGS_KEY_DATABASE_PASSWORD] = "illO"
		# {
		# 	"localDatabaseFileLocation": "",
		# 	"type": "postgres",
		# 	"host": "localhost",
		# 	"port": 5432,
		# 	"databaseName": "SpoolDatabase",
		# 	"user": "Olli",
		# 	"password": "illO"
		# }

		settings["excludedFromTemplateCopy"] = []
		return settings

	##~~ TemplatePlugin mixin
	def get_template_configs(self):
		return [
			dict(type="tab", name="Spools"),
			dict(type="tab", name="Sheets", template="SpoolManager_tab_sheets.jinja2"),
			dict(type="tab", name="Consumables", template="SpoolManager_tab_consumables.jinja2"),
			dict(type="tab", name="Low Stock", template="SpoolManager_tab_lowstock.jinja2"),
			dict(type="sidebar", template="SpoolManager_sidebar.jinja2"),
			dict(type="settings", custom_bindings=True, name="Spool Manager")
		]

	##~~ AssetPlugin mixin
	def get_assets(self):
		# Define your plugin's asset files to automatically include in the
		# core UI here.
		return dict(
			js=[
				"js/quill.min.js",
				"js/select2.min.js",
				# "js/jquery.datetimepicker.full.min.js",
				"js/jquery.datetimepicker.full.js",
				"js/tinycolor.js",
				"js/pick-a-color.js",
				"js/ResetSettingsUtilV3.js",
				"js/ComponentFactory.js",
				"js/TableItemHelper.js",
				"js/SpoolManager.js",
				"js/SpoolManager-APIClient.js",
				"js/SpoolManager-FilterSorter.js",
				"js/SpoolManager-SpoolSelectionTableComp.js",
				"js/SpoolManager-EditSpoolDialog.js",
				"js/SpoolManager-ImportDialog.js",
				"js/SpoolManager-DatabaseConnectionProblemDialog.js"
			],
			css=[
				"css/quill.snow.css",
				"css/select2.min.css",
				"css/jquery.datetimepicker.min.css",
				"css/pick-a-color-1.1.8.min.css",
				"css/SpoolManager.css"
			],
			less=["less/SpoolManager.less"]
		)

	##~~ Softwareupdate hook
	def get_update_information(self):
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here. See https://github.com/foosel/OctoPrint/wiki/Plugin:-Software-Update
		# for details.
		return dict(
			SpoolManager=dict(
				displayName="SpoolManager Plugin",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="OllisGit",
				repo="OctoPrint-SpoolManager",
				current=self._plugin_version,

				# Release channels
				stable_branch=dict(
					name="Only Release",
					branch="master",
					comittish=["master"]
				),
				prerelease_branches=[
					dict(
						name="Release & Candidate",
						branch="pre-release",
						comittish=["pre-release", "master"],
					),
					dict(
						name="Release & Candidate & under Development",
						branch="development",
						comittish=["development", "pre-release", "master"],
					)
				],

				# update method: pip
				pip="https://github.com/OllisGit/OctoPrint-SpoolManager/releases/download/{target_version}/master.zip"
			)
		)

	def register_custom_events(*args, **kwargs):
		return [EventBusKeys.EVENT_BUS_SPOOL_WEIGHT_UPDATED_AFTER_PRINT,
				EventBusKeys.EVENT_BUS_SPOOL_SELECTED,
				EventBusKeys.EVENT_BUS_SPOOL_DESELECTED,
				EventBusKeys.EVENT_BUS_SPOOL_ADDED,
				EventBusKeys.EVENT_BUS_SPOOL_DELETED,
				EventBusKeys.EVENT_BUS_SHEET_ASSIGNED,
				EventBusKeys.EVENT_BUS_SHEET_UNASSIGNED,
				EventBusKeys.EVENT_BUS_SHEET_ADDED,
				EventBusKeys.EVENT_BUS_SHEET_DELETED
				]


	def is_blueprint_csrf_protected(self):
		return True

	# def message_on_connect(self, comm, script_type, script_name, *args, **kwargs):
	# 	print(script_name)
	# 	if not script_type == "gcode" or not script_name == "afterPrinterConnected":
	# 		return None
	#
	# 	prefix = None
	# 	postfix = "M117 OctoPrint connected"
	# 	variables = dict(myvariable="Hi! I'm a variable!")
	# 	return prefix, postfix, variables

# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "SpoolManager Plugin"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = SpoolmanagerPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.comm.protocol.atcommand.queuing": __plugin_implementation__.on_atcommand_queuing,
		"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.on_queuingGCodeHook,
		"octoprint.comm.protocol.gcode.sent": __plugin_implementation__.on_sentGCodeHook,
		"octoprint.comm.protocol.gcode.received": __plugin_implementation__.on_receivedGCodeHook,
		# "octoprint.comm.protocol.scripts": __plugin_implementation__.message_on_connect
		"octoprint.events.register_custom_events":  __plugin_implementation__.register_custom_events
	}
