# coding=utf-8
from __future__ import absolute_import

from octoprint_SpoolManager.models.SpoolModel import SpoolModel
from octoprint_SpoolManager.models.SheetModel import SheetModel
from octoprint_SpoolManager.models.SheetTypeModel import SheetTypeModel
from octoprint_SpoolManager.common import StringUtils

def calculateRemainingWeight(usedWeight, totalWeight):
	if (usedWeight == None or totalWeight == None):
		return None

	if ( (type(usedWeight) == int or type(usedWeight) == float) and
			(type(totalWeight) == int or type(totalWeight) == float) ):
		result = totalWeight - usedWeight
		return result

	return None

def _calculateRemainingPercentage(remainingWeight, totalWeight):
	if (remainingWeight == None or totalWeight == None):
		return None

	if ( (type(remainingWeight) == int or type(remainingWeight) == float) and
			(type(totalWeight) == int or type(totalWeight) == float) and
			(totalWeight > 0) ):
		result = remainingWeight / (totalWeight / 100.0)
		return result

	return None

def _calculateUsedPercentage(usedWeight, totalWeight):
	if (usedWeight == None or totalWeight == None):
		return None

	if ( (type(usedWeight) == int or type(usedWeight) == float) and
			(type(totalWeight) == int or type(totalWeight) == float) and
			(totalWeight > 0) ):
		result = usedWeight / (totalWeight / 100.0)
		return result

	return None

def transformSpoolModelToDict(spoolModel):
	spoolAsDict = spoolModel.__data__
	spoolAsDict["printer"] = spoolModel.printer
	spoolAsDict["shelf"] = spoolModel.shelf

	# Date time needs to be converted
	spoolAsDict["firstUse"] = StringUtils.formatDateTime(spoolModel.firstUse)
	spoolAsDict["lastUse"] = StringUtils.formatDateTime(spoolModel.lastUse)
	spoolAsDict["purchasedOn"] = StringUtils.formatDateTime(spoolModel.purchasedOn)

	spoolAsDict["created"] = StringUtils.formatDateTime(spoolModel.created)
	spoolAsDict["updated"] = StringUtils.formatDateTime(spoolModel.updated)


	totalWeight = spoolModel.totalWeight
	usedWeight = spoolModel.usedWeight
	remainingWeight = calculateRemainingWeight(usedWeight, totalWeight)
	remainingPercentage = _calculateUsedPercentage(remainingWeight, totalWeight)
	usedPercentage = _calculateUsedPercentage(usedWeight, totalWeight)

	spoolAsDict["remainingWeight"] = StringUtils.formatFloat(remainingWeight)
	spoolAsDict["remainingPercentage"] = StringUtils.formatFloat(remainingPercentage)
	spoolAsDict["usedPercentage"] = StringUtils.formatFloat(usedPercentage)


	# Decimal and date time needs to be converted. ATTENTION orgiginal fields will be modified
	spoolAsDict["totalWeight"] = StringUtils.formatFloat(spoolModel.totalWeight)
	spoolAsDict["spoolWeight"] = StringUtils.formatFloat(spoolModel.spoolWeight)
	spoolAsDict["usedWeight"] = StringUtils.formatFloat(spoolModel.usedWeight)

	usedLength = spoolModel.usedLength
	totalLength = spoolModel.totalLength
	remainingLength = calculateRemainingWeight(usedLength, totalLength)
	remainingLengthPercentage = _calculateUsedPercentage(remainingLength, totalLength)
	usedLengthPercentage = _calculateUsedPercentage(usedLength, totalLength)

	spoolAsDict["remainingLength"] = StringUtils.formatInt(remainingLength)
	spoolAsDict["remainingLengthPercentage"] = StringUtils.formatInt(remainingLengthPercentage)
	spoolAsDict["usedLengthPercentage"] = StringUtils.formatInt(usedLengthPercentage)




	# spoolAsDict["temperature"] = StringUtils.formatSave("{:.02f}", spoolAsDict["temperature"], "")
	# spoolAsDict["weight"] = StringUtils.formatSave("{:.02f}", spoolAsDict["weight"], "")
	# spoolAsDict["remainingWeight"] = StringUtils.formatSave("{:.02f}", spoolAsDict["remainingWeight"], "")
	# spoolAsDict["usedLength"] = StringUtils.formatSave("{:.02f}", spoolAsDict["usedLength"], "")
	# spoolAsDict["usedLength"] = StringUtils.formatSave("{:.02f}", spoolAsDict["usedLength"], "")


	return spoolAsDict

def transformAllSpoolModelsToDict(allSpoolModels):
	result = []
	if (allSpoolModels != None):
		for job in allSpoolModels:
			spoolAsDict = transformSpoolModelToDict(job)
			result.append(spoolAsDict)
	return result

def transformSheetModelToDict(sheetModel):
	sheetAsDict = sheetModel.__data__

	try:
		sheetAsDict["sheetTypeName"] = sheetModel.sheetType.name if sheetModel.sheetType != None else None
	except Exception:
		sheetAsDict["sheetTypeName"] = None

	sheetAsDict["created"] = StringUtils.formatDateTime(sheetModel.created)
	sheetAsDict["updated"] = StringUtils.formatDateTime(sheetModel.updated)

	return sheetAsDict

def transformAllSheetModelsToDict(allSheetModels):
	result = []
	if (allSheetModels != None):
		for sheet in allSheetModels:
			sheetAsDict = transformSheetModelToDict(sheet)
			result.append(sheetAsDict)
	return result

def transformSheetTypeModelToDict(sheetTypeModel):
	sheetTypeAsDict = sheetTypeModel.__data__
	sheetTypeAsDict["created"] = StringUtils.formatDateTime(sheetTypeModel.created)
	sheetTypeAsDict["updated"] = StringUtils.formatDateTime(sheetTypeModel.updated)
	return sheetTypeAsDict

def transformAllSheetTypeModelsToDict(allSheetTypeModels):
	result = []
	if (allSheetTypeModels != None):
		for sheetType in allSheetTypeModels:
			sheetTypeAsDict = transformSheetTypeModelToDict(sheetType)
			result.append(sheetTypeAsDict)
	return result
