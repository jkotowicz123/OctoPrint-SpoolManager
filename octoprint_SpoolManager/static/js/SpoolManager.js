/*
 * View model for OctoPrint-SpoolManager
 *
 * Author: OllisGit
 * License: AGPLv3
 */
 // START: TESTZONE

 var expanded = false;

function showCheckboxes() {

  var checkboxes = document.getElementById("checkboxes");
  if (!expanded) {
    checkboxes.style.display = "block";
    expanded = true;
  } else {
    checkboxes.style.display = "none";
    expanded = false;
  }
}

var data = [{
   id: 0,
   text: 'enhancement',
	html: '<div class="pick-a-color-markup"><span class="color-preview" style="background-color: rgb(255, 255, 0);"></span>enhancement</div>'
}, {
   id: 1,
   text: 'bug',
	html: '<div style="color:red">bug</div><div><small>This is some small text on a new line</small></div>'
}];

function template(data) {
	return data.html;
}

$("#colorFilter").select2({
   data: data,
   templateResult: template,
   escapeMarkup: function(m) {
      return m;
   }
});

 // END: TESTZONE

$(function() {

    var PLUGIN_ID = "SpoolManager"; // from setup.py plugin_identifier


    ///////////////////////////////////////////////////////////////////////////////////////////////////////// VIEW MODEL
    function SpoolManagerViewModel(parameters) {

        var PLUGIN_ID = "SpoolManager"; // from setup.py plugin_identifier

        var self = this;

        // assign the injected parameters, e.g.:
        self.loginStateViewModel = parameters[0];
        self.loginState = parameters[0];
        self.settingsViewModel = parameters[1];
        self.printerStateViewModel = parameters[2];
        self.filesViewModel = parameters[3];
        self.printerProfilesViewModel = parameters[4];

        self.pluginSettings = null;

        self.apiClient = new SpoolManagerAPIClient(PLUGIN_ID, BASEURL);
        self.spoolDialog = new SpoolManagerEditSpoolDialog();


        self.octoPrintInstanceName = ko.observable(null);
        self.currentPrinterNumber = ko.observable(null);

        self.sidebarSheetNid = ko.observable("");
        self.sidebarCurrentSheet = ko.observable(null);
        self.sidebarMagazineSheets = ko.observableArray([]);

        self.sheets = ko.observableArray([]);
        self.sheetTypes = ko.observableArray([]);
        self.sheetFilterQuery = ko.observable("");
        self.currentSheetEditItem = ko.observable(null);

        self.consumables = ko.observableArray([]);
        self.consumableFilterQuery = ko.observable("");
        self.currentConsumableEditItem = ko.observable(null);
        self.consumableScanBarcode = ko.observable("");

        self.filamentTypes = ko.observableArray([]);
        self.currentFilamentStockEditName = ko.observable("");
        self.currentFilamentStockEdit = ko.observable(null);

        self.consumablesCsvFileUploadName = ko.observable();
        self.consumablesCsvImportInProgress = ko.observable(false);
        self.consumablesCsvImportStatus = ko.observable("");
        self.consumablesCsvImportLineNumber = ko.observable("");
        self.consumablesCsvImportSuccessMessage = ko.observable("");
        self.consumablesCsvImportErrorMessage = ko.observable("");
        self.consumablesCsvImportUploadData = undefined;

        self.sheetsTotalCount = ko.pureComputed(function(){
            return self.sheets().length;
        });

        self.consumablesTotalCount = ko.pureComputed(function(){
            return self.consumables().length;
        });

        self.lowStockConsumables = ko.pureComputed(function(){
            return ko.utils.arrayFilter(self.consumables(), function(c){
                var min = parseInt(c.minStockCount());
                if (isNaN(min) || min <= 0) return false;
                var count = parseInt(c.count());
                if (isNaN(count)) count = 0;
                return count < min;
            });
        });

        self.lowStockConsumablesByCategory = ko.pureComputed(function(){
            var items = self.lowStockConsumables();
            var catMap = {};
            var catOrder = [];
            for (var i = 0; i < items.length; i++){
                var cat = ko.utils.unwrapObservable(items[i].category) || "Uncategorized";
                if (!catMap[cat]){
                    catMap[cat] = [];
                    catOrder.push(cat);
                }
                catMap[cat].push(items[i]);
            }
            var result = [];
            for (var j = 0; j < catOrder.length; j++){
                result.push({ category: catOrder[j], items: catMap[catOrder[j]] });
            }
            return result;
        });

        self.consumableDeficit = function(item){
            var min = parseInt(item.minStockCount());
            var count = parseInt(item.count());
            if (isNaN(min)) min = 0;
            if (isNaN(count)) count = 0;
            return Math.max(0, min - count);
        }

        self.lowStockSpoolGroups = ko.pureComputed(function(){
            if (!self.spoolItemTableHelper) return [];
            var groups = self.spoolItemTableHelper.groupedItemsByDisplayName();
            var ftypes = self.filamentTypes();
            var result = [];
            for (var i = 0; i < groups.length; i++){
                var g = groups[i];
                var displayName = g.displayName;
                var ft = null;
                for (var j = 0; j < ftypes.length; j++){
                    if (ftypes[j].name === displayName){ ft = ftypes[j]; break; }
                }
                if (!ft || !ft.minStockWeight) continue;
                var minW = parseFloat(ft.minStockWeight);
                if (isNaN(minW) || minW <= 0) continue;
                var currentW = parseFloat(g.totalRemainingWeight) || 0;
                if (currentW >= minW) continue;

                var deficit = Math.round(minW - currentW);
                var items = g.items || [];
                var distinctWeights = {};
                for (var k = 0; k < items.length; k++){
                    var tw = parseFloat(ko.utils.unwrapObservable(items[k].totalWeight));
                    if (!isNaN(tw) && tw > 0) distinctWeights[tw] = true;
                }
                var sizes = Object.keys(distinctWeights).map(function(s){ return parseFloat(s); });
                sizes.sort(function(a, b){ return a - b; });

                var spoolsToOrder = "?";
                if (sizes.length === 1){
                    spoolsToOrder = Math.ceil(deficit / sizes[0]) + " szpul " + sizes[0] + "g";
                } else if (sizes.length > 1){
                    var parts = [];
                    for (var s = 0; s < sizes.length; s++){
                        parts.push(Math.ceil(deficit / sizes[s]) + " szpul " + sizes[s] + "g");
                    }
                    spoolsToOrder = parts.join(" / ");
                }

                var orderedDict = (ft.ordered && typeof ft.ordered === "object") ? ft.ordered : {};
                var orderedTotal = 0;
                var orderedSizes = [];
                for (var si = 0; si < sizes.length; si++){
                    var wKey = String(sizes[si]);
                    var cnt = parseInt(orderedDict[wKey]) || 0;
                    orderedTotal += cnt;
                    orderedSizes.push({ weight: sizes[si], count: cnt });
                }

                result.push({
                    displayName: displayName,
                    currentWeight: Math.round(currentW),
                    minStockWeight: Math.round(minW),
                    deficit: deficit,
                    spoolsToOrder: spoolsToOrder,
                    orderedTotal: orderedTotal,
                    orderedSizes: orderedSizes,
                    singleSize: sizes.length === 1
                });
            }
            return result;
        });

        self.lowStockTotalCount = ko.pureComputed(function(){
            return self.lowStockConsumables().length + self.lowStockSpoolGroups().length;
        });

        self.canSaveCurrentSheet = ko.pureComputed(function(){
            var item = self.currentSheetEditItem();
            if (!item){
                return false;
            }
            var sheetTypeId = item.sheetTypeId();
            if (sheetTypeId == null || sheetTypeId === ""){
                return false;
            }
            return true;
        });

        self._parsePrinterNumberFromInstanceName = function(instanceName){
            if (!instanceName){
                return null;
            }
            var m = instanceName.match(/#\s*(\d+)/);
            if (!m){
                return null;
            }
            var n = parseInt(m[1]);
            if (isNaN(n)){
                return null;
            }
            return n;
        }

        self._createSheetItem = function(sheetData){
            sheetData = sheetData || {};

            var item = {
                databaseId: ko.observable(sheetData.databaseId),
                version: ko.observable(sheetData.version),
                nid: ko.observable(sheetData.nid),
                note: ko.observable(sheetData.note),
                compatibleMaterials: ko.observable(sheetData.compatibleMaterials),
                sheetTypeId: ko.observable(sheetData.sheetType != null ? sheetData.sheetType : sheetData.sheetTypeId),
                sheetTypeName: ko.observable(sheetData.sheetTypeName),
                printerNumber: ko.observable(sheetData.printerNumber),
                magazinePosition: ko.observable(sheetData.magazinePosition)
            };

            item.assignmentLabel = ko.pureComputed(function(){
                var p = item.printerNumber();
                if (p == null){
                    return "-";
                }
                var pos = item.magazinePosition();
                if (pos == null){
                    return "#" + p;
                }
                return "#" + p + "-" + pos;
            });

            return item;
        }

        self._createConsumableItem = function(consumableData){
            consumableData = consumableData || {};
            return {
                databaseId: ko.observable(consumableData.databaseId),
                version: ko.observable(consumableData.version),
                name: ko.observable(consumableData.name),
                barcode: ko.observable(consumableData.barcode),
                category: ko.observable(consumableData.category),
                productCode: ko.observable(consumableData.productCode),
                packUnitsLabel: ko.observable(consumableData.packUnitsLabel),
                packUnits: ko.observable(consumableData.packUnits),
                packPriceGross: ko.observable(consumableData.packPriceGross),
                unitPrice: ko.observable(consumableData.unitPrice),
                count: ko.observable(consumableData.count),
                ordered: ko.observable(consumableData.ordered),
                minStockCount: ko.observable(consumableData.minStockCount)
            };
        }

        self.clearSheetFilterQuery = function(){
            self.sheetFilterQuery("");
        }

        self.clearConsumableFilterQuery = function(){
            self.consumableFilterQuery("");
        }

        self.filteredSheets = ko.pureComputed(function(){
            var q = (self.sheetFilterQuery() || "").toLowerCase();
            if (!q){
                return self.sheets();
            }

            return ko.utils.arrayFilter(self.sheets(), function(sheet){
                var text = (
                    (sheet.databaseId() != null ? ("" + sheet.databaseId()) : "") + " " +
                    (sheet.nid() || "") + " " +
                    (sheet.sheetTypeName() || "") + " " +
                    (sheet.assignmentLabel() || "") + " " +
                    (sheet.note() || "")
                ).toLowerCase();
                return text.indexOf(q) !== -1;
            });
        });

        self.filteredConsumables = ko.pureComputed(function(){
            var q = (self.consumableFilterQuery() || "").toLowerCase();
            if (!q){
                return self.consumables();
            }

            return ko.utils.arrayFilter(self.consumables(), function(c){
                var text = (
                    (c.databaseId() != null ? ("" + c.databaseId()) : "") + " " +
                    (c.name() || "") + " " +
                    (c.barcode() || "") + " " +
                    (c.category() || "") + " " +
                    (c.productCode() || "") + " " +
                    (c.packUnitsLabel() || "")
                ).toLowerCase();
                return text.indexOf(q) !== -1;
            });
        });

        self.groupedConsumables = ko.pureComputed(function(){
            var items = self.filteredConsumables() || [];
            var copy = items.slice(0);
            copy.sort(function(a, b){
                var ac = (a.category() || "").toLowerCase();
                var bc = (b.category() || "").toLowerCase();
                if (ac < bc) return -1;
                if (ac > bc) return 1;
                var an = (a.name() || "").toLowerCase();
                var bn = (b.name() || "").toLowerCase();
                if (an < bn) return -1;
                if (an > bn) return 1;
                return (a.databaseId() || 0) - (b.databaseId() || 0);
            });

            var groups = [];
            var current = null;
            for (var i = 0; i < copy.length; i++){
                var c = copy[i];
                var cat = c.category() || "Uncategorized";
                if (!current || current.category !== cat){
                    current = { category: cat, expanded: ko.observable(true), items: [] };
                    groups.push(current);
                }
                current.items.push(c);
            }
            return groups;
        });

        self.groupedSheets = ko.pureComputed(function(){
            var items = self.filteredSheets() || [];
            var copy = items.slice(0);
            copy.sort(function(a, b){
                var at = (a.sheetTypeName() || "").toLowerCase();
                var bt = (b.sheetTypeName() || "").toLowerCase();
                if (at < bt){
                    return -1;
                }
                if (at > bt){
                    return 1;
                }
                var ad = a.databaseId() || 0;
                var bd = b.databaseId() || 0;
                return ad - bd;
            });

            var groups = [];
            var current = null;
            for (var i=0; i<copy.length; i++){
                var s = copy[i];
                var typeName = s.sheetTypeName() || "";
                if (!current || current.typeName !== typeName){
                    current = {typeName: typeName, sheets: []};
                    groups.push(current);
                }
                current.sheets.push(s);
            }
            return groups;
        });

        self.loadSheets = function(){
            self.apiClient.callLoadSheets(function(responseData){
                var sheetsData = responseData.allSheets || [];
                var sheetTypesData = responseData.sheetTypes || [];

                self.sheetTypes(sheetTypesData);
                self.sheets(ko.utils.arrayMap(sheetsData, function(sheetData){
                    return self._createSheetItem(sheetData);
                }));
            });
        }

        self.isConsumableLowStock = function(item){
            var min = parseInt(item.minStockCount());
            var count = parseInt(item.count());
            if (isNaN(min) || min <= 0) return false;
            if (isNaN(count)) count = 0;
            var ordered = parseInt(item.ordered());
            if (isNaN(ordered)) ordered = 0;
            return count < min && ordered <= 0;
        }

        self.isConsumableLowStockButOrdered = function(item){
            var min = parseInt(item.minStockCount());
            var count = parseInt(item.count());
            if (isNaN(min) || min <= 0) return false;
            if (isNaN(count)) count = 0;
            var ordered = parseInt(item.ordered());
            if (isNaN(ordered)) ordered = 0;
            return count < min && ordered > 0;
        }

        self.loadConsumables = function(){
            self.apiClient.callLoadConsumables(function(responseData){
                var items = responseData.consumables || [];
                self.consumables(ko.utils.arrayMap(items, function(c){
                    return self._createConsumableItem(c);
                }));
            });
        }

        self.loadFilamentTypes = function(){
            self.apiClient.callLoadFilamentTypes(function(responseData){
                var items = responseData.filamentTypes || [];
                self.filamentTypes(items);
            });
        }

        self.saveFilamentTypeStock = function(name, minStockWeight, ordered){
            var payload = {
                name: name,
                minStockWeight: minStockWeight,
                ordered: ordered
            };
            self.apiClient.callSaveFilamentTypeStock(payload, function(){
                self.loadFilamentTypes();
            });
        }

        self.getFilamentTypeByName = function(displayName){
            var types = self.filamentTypes();
            for (var i = 0; i < types.length; i++){
                if (types[i].name === displayName) return types[i];
            }
            return null;
        }

        self.openFilamentStockEdit = function(displayName){
            var ft = self.getFilamentTypeByName(displayName);
            var minW = (ft && ft.minStockWeight) ? ft.minStockWeight : "";
            var orderedDict = (ft && ft.ordered && typeof ft.ordered === "object") ? ft.ordered : {};

            var entries = ko.observableArray([]);
            for (var bc in orderedDict){
                if (orderedDict.hasOwnProperty(bc)){
                    entries.push({ barcode: bc, count: ko.observable(orderedDict[bc] || 0) });
                }
            }

            var editObj = {
                minStockWeight: ko.observable(minW),
                orderedEntries: entries,
                newOrderedBarcode: ko.observable(""),
                addOrderedEntry: function(){
                    var bc = editObj.newOrderedBarcode().trim();
                    if (!bc) return;
                    var existing = ko.utils.arrayFirst(entries(), function(e){ return e.barcode === bc; });
                    if (existing) return;
                    entries.push({ barcode: bc, count: ko.observable(0) });
                    editObj.newOrderedBarcode("");
                },
                removeOrderedEntry: function(entry){
                    entries.remove(entry);
                }
            };

            self.currentFilamentStockEditName(displayName);
            self.currentFilamentStockEdit(editObj);
            $("#dialog_filamentStock_edit").modal({ keyboard: false });
        }

        self.saveFilamentStockEdit = function(){
            var name = self.currentFilamentStockEditName();
            var edit = self.currentFilamentStockEdit();
            if (!edit) return;
            var minW = parseFloat(edit.minStockWeight());
            if (isNaN(minW)) minW = null;

            var ordered = {};
            var entries = edit.orderedEntries();
            for (var i = 0; i < entries.length; i++){
                var cnt = parseInt(entries[i].count()) || 0;
                if (cnt > 0){
                    ordered[entries[i].barcode] = cnt;
                }
            }

            self.saveFilamentTypeStock(name, minW, Object.keys(ordered).length > 0 ? ordered : null);
            $("#dialog_filamentStock_edit").modal("hide");
        }

        self.adjustFilamentOrdered = function(displayName, weightKey, delta){
            var ft = self.getFilamentTypeByName(displayName);
            var ordered = {};
            if (ft && ft.ordered && typeof ft.ordered === "object"){
                for (var k in ft.ordered){
                    if (ft.ordered.hasOwnProperty(k)) ordered[k] = ft.ordered[k];
                }
            }
            var wk = String(weightKey);
            var current = parseInt(ordered[wk]) || 0;
            var newVal = Math.max(0, current + delta);
            if (newVal > 0){
                ordered[wk] = newVal;
            } else {
                delete ordered[wk];
            }
            var minW = (ft && ft.minStockWeight) ? ft.minStockWeight : null;
            self.saveFilamentTypeStock(displayName, minW, Object.keys(ordered).length > 0 ? ordered : null);
        }

        self.adjustConsumableOrdered = function(item, delta){
            var payload = {
                databaseId: item.databaseId(),
                delta: delta
            };
            self.apiClient.callAdjustConsumableOrdered(payload, function(){
                self.loadConsumables();
            });
        }

        self.isSpoolGroupLowStock = function(displayName, totalRemainingWeight){
            var ft = self.getFilamentTypeByName(displayName);
            if (!ft || !ft.minStockWeight) return false;
            var min = parseFloat(ft.minStockWeight);
            if (isNaN(min) || min <= 0) return false;
            var current = parseFloat(totalRemainingWeight);
            if (isNaN(current)) current = 0;
            return current < min;
        }

        self.isSpoolGroupOrdered = function(displayName){
            var ft = self.getFilamentTypeByName(displayName);
            if (!ft || !ft.ordered || typeof ft.ordered !== "object") return false;
            for (var k in ft.ordered){
                if (ft.ordered.hasOwnProperty(k) && parseInt(ft.ordered[k]) > 0) return true;
            }
            return false;
        }

        self.spoolGroupOrderedLabel = function(displayName){
            var ft = self.getFilamentTypeByName(displayName);
            if (!ft || !ft.ordered || typeof ft.ordered !== "object") return "";
            var parts = [];
            for (var k in ft.ordered){
                if (ft.ordered.hasOwnProperty(k)){
                    var cnt = parseInt(ft.ordered[k]) || 0;
                    if (cnt > 0) parts.push(cnt + "x " + k + "g");
                }
            }
            return parts.length > 0 ? "zamówiono: " + parts.join(", ") : "";
        }

        self._showConsumableDialog = function(){
            $("#dialog_consumable_edit").modal({
                keyboard: false
            });
        }

        self.addNewConsumable = function(){
            self.currentConsumableEditItem(self._createConsumableItem({
                databaseId: null,
                version: null,
                name: "",
                barcode: "",
                category: "",
                productCode: "",
                packUnitsLabel: "",
                packUnits: "",
                packPriceGross: "",
                unitPrice: "",
                count: "",
                ordered: "",
                minStockCount: ""
            }));
            self._showConsumableDialog();
        }

        self.editConsumable = function(consumableItem){
            if (!consumableItem){
                return;
            }
            self.currentConsumableEditItem(self._createConsumableItem({
                databaseId: consumableItem.databaseId(),
                version: consumableItem.version(),
                name: consumableItem.name(),
                barcode: consumableItem.barcode(),
                category: consumableItem.category(),
                productCode: consumableItem.productCode(),
                packUnitsLabel: consumableItem.packUnitsLabel(),
                packUnits: consumableItem.packUnits(),
                packPriceGross: consumableItem.packPriceGross(),
                unitPrice: consumableItem.unitPrice(),
                count: consumableItem.count(),
                ordered: consumableItem.ordered(),
                minStockCount: consumableItem.minStockCount()
            }));
            self._showConsumableDialog();
        }

        self.saveCurrentConsumable = function(){
            var item = self.currentConsumableEditItem();
            if (!item){
                return;
            }
            self.apiClient.callSaveConsumable(item, function(){
                $("#dialog_consumable_edit").modal("hide");
                self.loadConsumables();
            });
        }

        self.deleteConsumable = function(consumableItem){
            if (!consumableItem || consumableItem.databaseId() == null){
                return;
            }
            if (!confirm("Delete consumable " + (consumableItem.name() || consumableItem.databaseId()) + "?")){
                return;
            }
            self.apiClient.callDeleteConsumable(consumableItem.databaseId(), function(){
                self.loadConsumables();
            });
        }

        self.deleteCurrentConsumable = function(){
            var item = self.currentConsumableEditItem();
            if (!item || item.databaseId() == null){
                return;
            }
            if (!confirm("Delete consumable " + (item.name() || item.databaseId()) + "?")){
                return;
            }
            self.apiClient.callDeleteConsumable(item.databaseId(), function(){
                $("#dialog_consumable_edit").modal("hide");
                self.loadConsumables();
            });
        }

        self.adjustConsumableCount = function(consumableItem, delta){
            if (!consumableItem){
                return;
            }
            var payload = {
                databaseId: consumableItem.databaseId(),
                delta: delta
            };
            self.apiClient.callAdjustConsumableCount(payload, function(){
                self.loadConsumables();
            });
        }

        self.onConsumableScanKeyUp = function(_data, event){
            try {
                var code = event && (event.keyCode || event.which);
                if (code === 13) {
                    self.consumableScanAdjustPlus();
                    return false;
                }
            } catch (e) {
            }
            return true;
        }

        self.consumableScanAdjustPlus = function(){
            var barcode = (self.consumableScanBarcode() || "").trim();
            if (!barcode){
                return;
            }
            self.apiClient.callAdjustConsumableCount({ barcode: barcode, delta: 1 }, function(responseData){
                try {
                    var c = responseData && responseData.consumable;
                    if (c && c.name) {
                        self.showPopUp("info", "Consumable", (c.name + ": +1 (count=" + (c.count || "") + ")"), true);
                    }
                } catch (e) {
                }
                self.consumableScanBarcode("");
                self.loadConsumables();
            });
        }

        self.consumableScanAdjustMinus = function(){
            var barcode = (self.consumableScanBarcode() || "").trim();
            if (!barcode){
                return;
            }
            self.apiClient.callAdjustConsumableCount({ barcode: barcode, delta: -1 }, function(responseData){
                try {
                    var c = responseData && responseData.consumable;
                    if (c && c.name) {
                        self.showPopUp("info", "Consumable", (c.name + ": -1 (count=" + (c.count || "") + ")"), true);
                    }
                } catch (e) {
                }
                self.consumableScanBarcode("");
                self.loadConsumables();
            });
        }

        self.consumableScanLookup = function(){
            var barcode = (self.consumableScanBarcode() || "").trim();
            if (!barcode){
                return;
            }
            self.apiClient.callConsumableByBarcode(barcode, function(responseData){
                var c = responseData && responseData.consumable;
                if (!c){
                    return;
                }
                self.currentConsumableEditItem(self._createConsumableItem(c));
                self._showConsumableDialog();
            });
        }

        self.performConsumablesCsvImport = function(){
            if (self.consumablesCsvImportUploadData === undefined) return;

            self.consumablesCsvImportInProgress(true);
            self.consumablesCsvImportStatus("");
            self.consumablesCsvImportLineNumber("");
            self.consumablesCsvImportSuccessMessage("");
            self.consumablesCsvImportErrorMessage("");

            $("#dialog_spoolManager_consumablesCsvImportStatus").modal({
                keyboard: false,
                clickClose: false,
                showClose: false,
                backdrop: "static"
            });

            self.consumablesCsvImportUploadData.submit();
        };

        self.closeConsumablesCsvImportDialog = function(){
            $("#dialog_spoolManager_consumablesCsvImportStatus").modal("hide");
            self.loadConsumables();
        };

        self._handleConsumablesCsvImportStatus = function(data){
            if (data.importStatus) {
                self.consumablesCsvImportStatus(data.importStatus);
                switch (data.importStatus){
                    case "running":
                        self.consumablesCsvImportLineNumber(data.currenLineNumber);
                        self.consumablesCsvImportInProgress(true);
                        break;
                    case "finished":
                        self.consumablesCsvImportInProgress(false);
                        self.consumablesCsvImportSuccessMessage(data.successMessages);
                        var errorMessage = (data.errorCollection || []).join(" <br> ");
                        self.consumablesCsvImportErrorMessage(errorMessage);
                        break;
                }
            }
        };

        self.loadSheetsStateForSidebar = function(){
            if (self.currentPrinterNumber() == null){
                self.sidebarCurrentSheet(null);
                self.sidebarMagazineSheets([]);
                return;
            }

            self.apiClient.callSheetsState(self.currentPrinterNumber(), function(responseData){
                var current = responseData.currentSheet || null;
                var magazine = responseData.magazineSheets || [];
                self.sidebarCurrentSheet(current ? self._createSheetItem(current) : null);
                self.sidebarMagazineSheets(ko.utils.arrayMap(magazine, function(sheetData){
                    return self._createSheetItem(sheetData);
                }));
            });
        }

        self.sidebarSetSheetFromScan = function(){
            if (self.currentPrinterNumber() == null){
                return;
            }
            var nid = (self.sidebarSheetNid() || "").trim();
            if (!nid){
                return;
            }

            self.apiClient.callAssignSheetToPrinterByNid(self.currentPrinterNumber(), nid, function(){
                self.sidebarSheetNid("");
                self.loadSheetsStateForSidebar();
                self.loadSheets();
            });
        }

        self.sidebarAppendSheetFromScan = function(){
            if (self.currentPrinterNumber() == null){
                return;
            }
            var nid = (self.sidebarSheetNid() || "").trim();
            if (!nid){
                return;
            }

            self.apiClient.callAppendSheetToMagazineByNid(self.currentPrinterNumber(), nid, function(){
                self.sidebarSheetNid("");
                self.loadSheetsStateForSidebar();
                self.loadSheets();
            });
        }

        self.sidebarUnassignSheet = function(sheetItem){
            if (!sheetItem || sheetItem.databaseId() == null){
                return;
            }
            self.apiClient.callUnassignSheet(sheetItem.databaseId(), function(){
                self.loadSheetsStateForSidebar();
                self.loadSheets();
            });
        }

        self.sidebarSetSheetFromMagazine = function(sheetItem){
            if (self.currentPrinterNumber() == null || !sheetItem || sheetItem.databaseId() == null){
                return;
            }
            self.apiClient.callAssignSheetToPrinter(self.currentPrinterNumber(), sheetItem.databaseId(), function(){
                self.loadSheetsStateForSidebar();
                self.loadSheets();
            });
        }

        self._showSheetDialog = function(){
            $("#dialog_sheet_edit").modal({
                keyboard: false
            });
        }

        self.addNewSheet = function(){
            self.currentSheetEditItem(self._createSheetItem({
                databaseId: null,
                nid: "",
                note: "",
                compatibleMaterials: "",
                sheetTypeId: null,
                sheetTypeName: null,
                printerNumber: null,
                magazinePosition: null
            }));
            self._showSheetDialog();
        }

        self.editSheet = function(sheetItem){
            self.currentSheetEditItem(self._createSheetItem({
                databaseId: sheetItem.databaseId(),
                version: sheetItem.version(),
                nid: sheetItem.nid(),
                note: sheetItem.note(),
                compatibleMaterials: sheetItem.compatibleMaterials(),
                sheetTypeId: sheetItem.sheetTypeId(),
                sheetTypeName: sheetItem.sheetTypeName(),
                printerNumber: sheetItem.printerNumber(),
                magazinePosition: sheetItem.magazinePosition()
            }));
            self._showSheetDialog();
        }

        self.saveCurrentSheet = function(){
            var item = self.currentSheetEditItem();
            if (!item){
                return;
            }
			if (!self.canSaveCurrentSheet()){
				return;
			}

            self.apiClient.callSaveSheet(item, function(){
                $("#dialog_sheet_edit").modal("hide");
                self.loadSheets();
            });
        }

        self.deleteSheet = function(sheetItem){
            if (!sheetItem || sheetItem.databaseId() == null){
                return;
            }
            if (!confirm("Delete sheet " + sheetItem.nid() + "?")){
                return;
            }
            self.apiClient.callDeleteSheet(sheetItem.databaseId(), function(){
                self.loadSheets();
            });
        }

        self.assignSheetToCurrentPrinter = function(sheetItem){
            if (self.currentPrinterNumber() == null || sheetItem == null){
                return;
            }
            if (sheetItem.databaseId() == null){
                return;
            }
            self.apiClient.callAssignSheetToPrinter(self.currentPrinterNumber(), sheetItem.databaseId(), function(){
                self.loadSheets();
                self.loadSheetsStateForSidebar();
            });
        }

        self.appendSheetToCurrentMagazine = function(sheetItem){
            if (self.currentPrinterNumber() == null || sheetItem == null){
                return;
            }
            if (sheetItem.databaseId() == null){
                return;
            }
            self.apiClient.callAppendSheetToMagazine(self.currentPrinterNumber(), sheetItem.databaseId(), function(){
                self.loadSheets();
                self.loadSheetsStateForSidebar();
            });
        }

        self.unassignSheet = function(sheetItem){
            if (sheetItem == null){
                return;
            }
            if (sheetItem.databaseId() == null){
                return;
            }
            self.apiClient.callUnassignSheet(sheetItem.databaseId(), function(){
                self.loadSheets();
            });
        }


        //////////////////////////////////////////////////////////////////////////////////////////////// HELPER FUNCTION

        loadSettingsFromBrowserStore = function(){
            // TODO maybe in a separate js-file
            // load all settings from browser storage
            if (!Modernizr.localstorage) {
                // damn!!!
                return false;
            }
            // Table visibility
            self.initTableVisibilities();
            self.initLowStockVisibilities();

            self.spoolItemTableHelper.selectedPageSize("all");
        }

        // Typs: error
        self.showPopUp = function(popupType, popupTitle, message, autoclose){
            var title = popupType.toUpperCase() + ": " + popupTitle;
            var popupId = (title+message).replace(/([^a-z0-9]+)/gi, '-');
            if($("."+popupId).length <1) {
                new PNotify({
                    title: "SPM:" + title,
                    text: message,
                    type: popupType,
                    hide: autoclose,
                    addclass: popupId
                });
            }
        };


        // found here: https://stackoverflow.com/questions/19491336/how-to-get-url-parameter-using-jquery-or-plain-javascript?rq=1
        var getUrlParameter = function getUrlParameter(sParam) {
            var sPageURL = window.location.search.substring(1),
                sURLVariables = sPageURL.split('&'),
                sParameterName,
                i;

            for (i = 0; i < sURLVariables.length; i++) {
                sParameterName = sURLVariables[i].split('=');

                if (sParameterName[0] === sParam) {
                    return sParameterName[1] === undefined ? true : decodeURIComponent(sParameterName[1]);
                }
            }
        };

        self.reloadQRCodePreviewImage = function(){
            var imageDom = $("#settings-qrimage-preview");
            var currentSrc = imageDom.attr("src");
            currentSrc = currentSrc + "&"+new Date().getTime();
            imageDom.attr("src", currentSrc);
        }

        // Generate HTML-Image Attributes for the QR-Code
        self.generateQRCodeImageSourceAttribute = function(databaseId, spoolDisplayName, showHtmlView, withColors){
            var requestParameters = "";
            if (withColors){
                requestParameters = "?" +
                                    "fillColor=" + encodeURIComponent(self.pluginSettings.qrCodeFillColor()) + "&" +
                                    "backgroundColor=" + encodeURIComponent(self.pluginSettings.qrCodeBackgroundColor());

                if (self.pluginSettings.qrCodeUseURLPrefix() == true){
                    requestParameters = requestParameters + "&" +
                        "useURLPrefix=true" + "&" +
                        "urlPrefix=" + encodeURIComponent(self.pluginSettings.qrCodeURLPrefix())
                }
            }

            var source = "";
            if (showHtmlView == "htmlView"){
                source = PLUGIN_BASEURL + "SpoolManager/generateQRCodeView/" + databaseId + "" + requestParameters;
            } else {
                source = PLUGIN_BASEURL + "SpoolManager/generateQRCode/" + databaseId+ "" + requestParameters;
            }
            var title = "QR-Code for " + spoolDisplayName;
            return {
                src: source,
                href: source,
                title: title
            }
        }


        ///////////////////////////////////////////////////// START: SETTINGS
        self.pluginNotWorking = ko.observable(undefined);

        self.downloadDatabaseUrl = ko.observable();
        self.databaseConnectionProblemDialog = new DatabaseConnectionProblemDialog();

        self.databaseMetaData = {
            localSchemeVersionFromDatabaseModel: ko.observable(),
            localSpoolItemCount: ko.observable(),
            externalSchemeVersionFromDatabaseModel: ko.observable(),
            externalSpoolItemCount: ko.observable(),
            schemeVersionFromPlugin: ko.observable(),
        }
        self.showInternalSuccessMessage = ko.observable(false);
        self.showInternalDatabaseErrorMessage = ko.observable(false);
        self.showExternalSuccessMessage = ko.observable(false);
        self.showExternalDatabaseErrorMessage = ko.observable(false);
        self.showUpdateSchemeMessage = ko.observable(false);
        self.externalDatabaseErrorMessage = ko.observable("");
        self.internalDatabaseErrorMessage = ko.observable("");
        self.showLocalBusyIndicator = ko.observable(false);
        self.showExternalBusyIndicator = ko.observable(false);
        self.databaseInUse = ko.observable("Internal");

        self.resetDatabaseMessages = function(){
            self.showInternalSuccessMessage(false);
            self.showInternalDatabaseErrorMessage(false);
            self.showExternalSuccessMessage(false);
            self.showExternalDatabaseErrorMessage(false);
            self.showUpdateSchemeMessage(false);
            self.externalDatabaseErrorMessage("");
            self.internalDatabaseErrorMessage("");
        }

        self.handleDatabaseMetaDataResponse = function(metaDataResponse){
            var metadata = metaDataResponse["metadata"];
            console.log(metadata);

            if (metadata != null){
                var errorMessage = metadata["errorMessage"];
                if (errorMessage != null && errorMessage.length != 0){
                    if (self.pluginSettings.useExternal()) {
                        self.showExternalDatabaseErrorMessage(true);
                        self.externalDatabaseErrorMessage(errorMessage);
                    }
                    else {
                        self.showInternalDatabaseErrorMessage(true);
                        self.internalDatabaseErrorMessage(errorMessage);
                    }
                }
                var success = metadata["success"];
                if (success != null && success == true){
                    self.showExternalSuccessMessage(true && self.pluginSettings.useExternal());
                    self.showInternalSuccessMessage(true && !self.pluginSettings.useExternal());
                } else {
                    self.showExternalSuccessMessage(false && self.pluginSettings.useExternal());
                    self.showInternalSuccessMessage(false && !self.pluginSettings.useExternal());
                }

                self.databaseMetaData.localSchemeVersionFromDatabaseModel(metadata["localSchemeVersionFromDatabaseModel"]);
                self.databaseMetaData.localSchemeVersionFromDatabaseModel(metadata["localSchemeVersionFromDatabaseModel"]);
                self.databaseMetaData.localSpoolItemCount(metadata["localSpoolItemCount"]);
                self.databaseMetaData.externalSchemeVersionFromDatabaseModel(metadata["externalSchemeVersionFromDatabaseModel"]);
                self.databaseMetaData.externalSpoolItemCount(metadata["externalSpoolItemCount"]);
                self.databaseMetaData.schemeVersionFromPlugin(metadata["schemeVersionFromPlugin"]);

                if (self.databaseMetaData.schemeVersionFromPlugin() != self.databaseMetaData.externalSchemeVersionFromDatabaseModel()){
                    self.showUpdateSchemeMessage(true);
                }
            }
        }

        self.buildDatabaseSettings = function(){

            var databaseSettings = {
                useExternal: self.pluginSettings.useExternal(),
                databaseType: self.pluginSettings.databaseType(),
                databaseHost: self.pluginSettings.databaseHost(),
                databasePort: self.pluginSettings.databasePort(),
                databaseName: self.pluginSettings.databaseName(),
                databaseUser: self.pluginSettings.databaseUser(),
                databasePassword: self.pluginSettings.databasePassword(),
            }
            return databaseSettings
        }

        self.testDatabaseConnection = function(){
            self.resetDatabaseMessages()
            self.showLocalBusyIndicator(self.pluginSettings.useExternal() == false);
            self.showExternalBusyIndicator(self.pluginSettings.databasePassword() == true);

            var databaseSettings = self.buildDatabaseSettings();

            self.apiClient.testDatabaseConnection(databaseSettings, function(responseData) {
                  self.handleDatabaseMetaDataResponse(responseData);
                  self.showLocalBusyIndicator(false);
                  self.showExternalBusyIndicator(false);
             });
        }

        self.deleteDatabaseAction = function(databaseType) {
            var result = confirm("Do you really want to delete all SpoolManager data in the " + databaseType + " database?");
            if (result == true){
                var databaseSettings = self.buildDatabaseSettings();
                databaseSettings.useExternal = databaseType == "external"
                
                self.apiClient.callDeleteDatabase(databaseType, databaseSettings, function(responseData) {
                    self.handleDatabaseMetaDataResponse(responseData);
                    self.spoolItemTableHelper.reloadItems();
                });
            }
        };

        self.copySpools = function() {
            var result = confirm("Do you really want to copy all SpoolManager data from the internal database? This will replace all existing data.");
            if (result == true) {
                var databaseSettings = self.buildDatabaseSettings();
                self.apiClient.callCopyDatabase(databaseSettings, function(responseData) {
                    self.spoolItemTableHelper.reloadItems();
                    self.apiClient.loadDatabaseMetaData(function(responseData) {
                        self.handleDatabaseMetaDataResponse(responseData);
                    });
                });

            }
        }

        $("#spoolmanger-settings-tab").find('a[data-toggle="tab"]').on('shown', function (e) {

              var activatedTab = e.target.hash; // activated tab
              var prevTab = e.relatedTarget.hash; // previous tab

              if (self.pluginSettings.useExternal() == true) {
                self.databaseInUse("External")
              } else {
                self.databaseInUse("Internal")
              }

              if ("#tab-spool-Storage" == activatedTab){
                  self.resetDatabaseMessages()
                  
                  self.showLocalBusyIndicator(self.pluginSettings.useExternal() == false);
                  self.showExternalBusyIndicator(self.pluginSettings.databasePassword() == true);      
                  
                  var databaseSettings = self.buildDatabaseSettings();
                  self.apiClient.loadDatabaseMetaData(function(responseData) {
                        self.handleDatabaseMetaDataResponse(responseData);
                        self.showExternalSuccessMessage(false);
                        self.showInternalSuccessMessage(false);
                        self.showLocalBusyIndicator(false);
                        self.showExternalBusyIndicator(false);
                   });
              }
        });

        self.isFilamentManagerPluginAvailable = ko.observable(false);

        // - Import CSV
        self.csvFileUploadName = ko.observable();
        self.csvImportInProgress = ko.observable(false);

        self.csvImportDialog = new SpoolManagerImportDialog();
        self.csvImportUploadButton = $("#settings-spool-importcsv-upload");
        self.csvImportUploadData = undefined;
        self.csvImportUploadButton.fileupload({
            dataType: "json",
            maxNumberOfFiles: 1,
            autoUpload: false,
            headers: OctoPrint.getRequestHeaders(),
            add: function(e, data) {
                if (data.files.length === 0) {
                    // no files? ignore
                    return false;
                }
                self.csvFileUploadName(data.files[0].name);
                self.csvImportUploadData = data;
            },
            done: function(e, data) {
                self.csvImportInProgress(false);
                self.csvFileUploadName(undefined);
                self.csvImportUploadData = undefined;
            },
            error: function(response, data, errorMessage){
                self.csvImportInProgress(false);
                statusCode = response.status;       // e.g. 400
                statusText = response.statusText;   // e.g. BAD REQUEST
                responseText = response.responseText; // e.g. Invalid request
            }
        });
        self.performCSVImportFromUpload = function() {
            if (self.csvImportUploadData === undefined) return;

            self.csvImportInProgress(true);
            self.csvImportDialog.showDialog(function(shouldTableReload){
                    //
                    if (shouldTableReload == true){
                        self.spoolItemTableHelper.reloadItems();
                    }
                }
            );
            self.csvImportUploadData.submit();
        };

        // template stuff
        self.checkExcludedFromTemplateCopy = function(fieldName) {
            return ko.pureComputed({
                read: function () {
                    var result = self.pluginSettings.excludedFromTemplateCopy().includes(fieldName) == false;
                    return result
                },
                write: function (value) {
                    if (value == false){
                        self.pluginSettings.excludedFromTemplateCopy.push(fieldName);
                    } else {
                       self.pluginSettings.excludedFromTemplateCopy.remove(fieldName);
                    }
                },
                owner: this
            });
        }

        // overwrite save-button
        const origSaveSettingsFunction = self.settingsViewModel.saveData;
        const newSaveSettingsFunction = function confirmSpoolSelectionBeforeStartPrint(data, successCallback, setAsSending) {
            if (self.pluginSettings.useExternal() == true &&
                (self.showExternalDatabaseErrorMessage() == true || self.showInternalDatabaseErrorMessage() == true || 
                    self.showUpdateSchemeMessage() == true)
                ){
                return origSaveSettingsFunction(data, successCallback, setAsSending);
            }
            return origSaveSettingsFunction(data, successCallback, setAsSending);
        }
        self.settingsViewModel.saveData = newSaveSettingsFunction;

        // QR-Code stuff
        self.generateQRCodeTestLink = function(){
            var source = self.pluginSettings.qrCodeURLPrefix() + "/plugin/SpoolManager/selectSpoolByQRCode/qrPreviewId";
            var title = "This link is used for the QR-Code";
            return {
                href: source,
                title: title
            }
        }

        ///////////////////////////////////////////////////// END: SETTINGS


        ////////////////////////////////////////////////////////////////////////////////////////// SIDEBAR - REPLACEMENT
        self.printerStateViewModel.spoolsWithWeight = ko.observableArray([]);
        self.printerStateViewModel.extrusionValues = ko.observableArray([]);

        self.updateExtrusionValues = function(extrusionValuesArray){
            // update patched PrinterStateViewModel
            self.printerStateViewModel.extrusionValues(extrusionValuesArray);
        }

        self.updateRequiredFilament = function(requiredFilament){
/*
                    # "metaDataPresent": metaDataPresent,
					# "warnUser": fromPluginSettings,
					# "attributesMissing": someAttributesMissing,
					# "notEnough": notEnough,
					# "detailedSpoolResult": [
					# 				"toolIndex": toolIndex,
					# 				"requiredWeight": requiredWeight,
					# 				"requiredLength": filamentLength,
					# 				"diameter": diameter,
					# 				"density": density,
					# 				"notEnough": notEnough,
					# 				"spoolSelected": True
					# ]
 */
            var filamentList = requiredFilament["detailedSpoolResult"];
            var filteredFilamentList = [];
            // filter not required tools
            for (filamentItem of filamentList){
                if (filamentItem.requiredLength > 0){
                    filteredFilamentList.push(filamentItem)
                }
            }
            self.printerStateViewModel.spoolsWithWeight(filteredFilamentList)
        }

        self.printerStateViewModel.formatSpoolsWithWeight = function formatSpoolsWithWeightInSidebar(filament) {
            if (!filament) return '-';

            // length in m
            var result = (filament.requiredLength / 1000).toFixed(2) + 'm';
            // try to get the weight
            if (filament.requiredWeight) {
                result += ' / ' + filament.requiredWeight.toFixed(2) + 'g';
            }
            if (filament.spoolSelected && filament.spoolSelected == true){
                if (filament.notEnough) {
                    if (filament.notEnough == true){
                        result += ' (<span style="color:red">'+filament.remainingWeight.toFixed(2) +'g</span>)';
                    }
                }
            } else {
                if (filament.requiredLength > 0){
                    result += ' (no spool selected)';
                }
            }

            return result;
        };

        self.replaceFilamentView = function replaceFilamentViewInSidebar() {
            $('#state').find('.accordion-inner').contents().each(function (index, item) {
                if (item.nodeType === Node.COMMENT_NODE) {
                    if (item.nodeValue === ' ko foreach: filament ' || item.nodeValue === ' ko foreach: [] ') {
                        item.nodeValue = ' ko foreach: [] '; // eslint-disable-line no-param-reassign
                        var element = '<!-- ko if: spoolsWithWeight().length < 1 -->  <span><strong>Required Filament unknown</strong></span><br/> <!-- /ko -->';
                        element += '<!-- ko foreach: spoolsWithWeight --> <span data-bind="text: \'Tool \' + toolIndex + \': \', attr: {title: \'Filament usage for Spool \' + spoolName}"></span><strong data-bind="html: $root.formatSpoolsWithWeight($data)"></strong><br> <!-- /ko -->';

                        element += '<div data-bind="visible: settings.settings.plugins.SpoolManager.extrusionDebuggingEnabled">';
                        element += '<!-- ko foreach: extrusionValues -->';
                        element += '<div>Extruded Tool <span data-bind="text: $index"></span>: <strong data-bind="text: $data.toFixed(2)"></strong></div>';
                        element += '<!-- /ko -->';

                        element += '</div>'
                        $(element).insertBefore(item);

                        return false; // exit loop
                    }
                }
                return true;
            });
        };

        /////////////////////////////////////////////////////////////////////////////////////////// SIDEBAR - SELECT
        self.allSpoolsForSidebar = ko.observableArray([]);
        self.selectedSpoolsForSidebar = ko.observableArray([]);
        // see FILTER/SORTING https://embed.plnkr.co/plunk/Kj5JMv
        self.filterSelectionQuery = ko.observable();

        // self.sidebarFilterSorter = new SpoolsFilterSorter("sidebarSpoolSelection", self.allSpoolsForSidebar);

        self.sidebarSelectSpoolModalToolIndex = ko.observable(null);  // index of the current tool we want to select for
        self.sidebarSelectSpoolModalSpoolItem = ko.observable(null); // current spoolitem

        self.deselectSpoolForSidebar = function(toolIndex, item){
            self.selectSpoolForSidebar(toolIndex, null);
        }

        self.loadSpoolsForSidebar = function() {
            // update filament list length
            var currentProfileData = self.settingsViewModel.printerProfiles.currentProfileData(),
                numExtruders = (currentProfileData ? currentProfileData.extruder.count() : 0),
                currentSelectedSpools = self.selectedSpoolsForSidebar().length,
                diff = numExtruders - currentSelectedSpools,
                i, item;
            if (diff !== 0) {
                if (diff > 0) {
                    for (i = 0; i < diff; i++) {
                        self.selectedSpoolsForSidebar().push(ko.observable(null));
                    }
                } else if (diff < 0) {
                    for (i = 0; i > diff; i--) {
                        self.selectedSpoolsForSidebar().pop();
                    }
                }
                self.selectedSpoolsForSidebar.valueHasMutated();
            }

            var currentFilterName = "all";
            // if (self.pluginSettings!= null){
            //      if(self.pluginSettings.hideEmptySpoolsInSidebar() == true) {
            //          currentFilterName = "hideEmptySpools";
            //      }
            //      if(self.pluginSettings.hideInactiveSpoolsInSidebar() == true) {
            //          currentFilterName = "hideInactiveSpools";
            //      }
            //      if(self.pluginSettings.hideEmptySpoolsInSidebar() == true && self.pluginSettings.hideInactiveSpoolsInSidebar() == true) {
            //          currentFilterName = "hideEmptySpools,hideInactiveSpools";
            //      }
            // }

            var tableQuery = {
                filterName: currentFilterName,
                from: 0,
                to: 3333,
                sortColumn: "displayName",
                sortOrder: "desc"
            }

            // api-call
            self.apiClient.callLoadSpoolsByQuery(tableQuery, function(responseData){

                var allSpoolData = responseData["allSpools"]; // rawdtata
                if (allSpoolData != null){
                    var allSpoolItems = ko.utils.arrayMap(allSpoolData, function (spoolData) {
                        var result = self.spoolDialog.createSpoolItemForTable(spoolData);
                        return result;
                    }); // transform to SpoolItems with KO.obseravables
                    self.allSpoolsForSidebar(allSpoolItems);

                    
                    var spoolsData = responseData["selectedSpools"],
                        slot, spoolData, spoolItem;
                    for(var i=0; i<self.selectedSpoolsForSidebar().length; i++) {
                        slot = self.selectedSpoolsForSidebar()[i];
                        spoolData = (i < spoolsData.length) ? spoolsData[i] : null;
                        spoolItem = spoolData ? self.spoolDialog.createSpoolItemForTable(spoolData) : null;
                        slot(spoolItem);
                    }
                    // Pre sorting in Selection-Dialog
                    // self.sidebarFilterSorter.sortSpoolArray("displayName", "ascending");
                }
            });
        }

        _buildRemainingText = function(spoolItem){
            var remainingInfo = "";
            // if (  spoolItem.remainingWeight() != null && spoolItem.remainingWeight().length != 0
            //     && spoolItem.remainingPercentage() != null && spoolItem.remainingPercentage().length != 0){
            //     remainingInfo = "("+spoolItem.remainingWeight()+"g / "+spoolItem.remainingPercentage()+"%)";
            // }
            if (  spoolItem.remainingWeight() != null && spoolItem.remainingWeight().length != 0){
                // remainingInfo = "(R: "+spoolItem.remainingWeight()+"g)";
                remainingInfo = ""+spoolItem.remainingWeight()+"g";
            }
            return remainingInfo
        }

        self.remainingText = function(spoolItem){
            var remainingInfo = "("+_buildRemainingText(spoolItem) + ")";
            return remainingInfo;
        }

        self.buildTooltipForSpoolItem = function(spoolItem, textPrefix, attribute){
            var value = "";
            if (spoolItem[attribute]() != null){
                value = spoolItem[attribute]();
            }
            var toolTip = textPrefix + value;
            return toolTip;
        }

        self.getSpoolItemSelectedTool = function(databaseId) {
            var spoolItem;
            for (var i=0; i<self.selectedSpoolsForSidebar().length; i++) {
                spoolItem = self.selectedSpoolsForSidebar()[i]();
                if (spoolItem !== null && self.selectedSpoolsForSidebar()[i]().databaseId() === databaseId) {
                    return i;
                }
            }
            return null;
        }

        self.selectSpoolForSidebar = function(toolIndex, spoolItem){
            var commitCurrentSpoolValues;
            if (self.printerStateViewModel.isPrinting()) {
                commitCurrentSpoolValues = confirm(
                    'You are changing a spool while printing. SpoolManager will commit the usage so far to the previous spool, unless you wish otherwise.\n\n' +
                    'Commit the usage of the print so far…\n' +
                    '"OK": …to the previously selected spool\n' +
                    '"Cancel": …to the new spool'
                )
            }
            // api-call
            var databaseId = -1
            if (spoolItem != null){
                databaseId = spoolItem.databaseId();
                // Why do we need this information
                // if (toolIndex != -1){
                //     var alreadyInTool = self.getSpoolItemSelectedTool(databaseId);
                //     if (alreadyInTool !== null) {
                //         alert('This spool is already selected for tool ' + alreadyInTool + '!');
                //         return;
                //     }
                // }
            }
            self.apiClient.callSelectSpool(toolIndex, databaseId, commitCurrentSpoolValues, function(responseData){
                var spoolItem = null;
                var spoolData = responseData["selectedSpool"];
                if (spoolData != null){
                    spoolItem = self.spoolDialog.createSpoolItemForTable(spoolData);
                } else {
                    // remove spool from toolIndex
                    self.selectedSpoolsForSidebar()[toolIndex](null);
                    return;
                }

                // remove the spool from the current toolIndex
                var currentDatabaseId = spoolItem.databaseId();
                for (var i = 0; i < self.selectedSpoolsForSidebar().length; i++) {
                    var tmpSpoolItem = self.selectedSpoolsForSidebar()[i]();
                    if (tmpSpoolItem !== null && tmpSpoolItem.databaseId() === currentDatabaseId) {
                        self.selectedSpoolsForSidebar()[i](null);
                        break;
                    }
                }
                // assign to new (or same) toolIndex
                if (toolIndex != -1) {
                    self.selectedSpoolsForSidebar()[toolIndex](spoolItem)
                }

            });
        }

        self.editSpoolFromSidebar = function(toolIndex, spoolItem){
            if (spoolItem == null){
                alert("Something is wrong. No Spool is selected to edit from sidebar!")
            }
            self.showSpoolDialogAction(spoolItem);
        }

        self.sidebarSelectSpoolFromDialog = function (spoolItem) {
            self.selectionSpoolDialog.modal("hide");
            self.selectSpoolForSidebar(self.sidebarSelectSpoolModalToolIndex(), spoolItem);
        }

        self.sidebarOpenSelectSpoolDialog = function(toolIndex, spoolItem){

            /* needed for Filter-Search dropdown-menu */
            $('.dropdown-menu.keep-open').click(function(e) {
                e.stopPropagation();
            });

            self.sidebarSelectSpoolModalSpoolItem(spoolItem);
            self.sidebarSelectSpoolModalToolIndex(toolIndex);

            // self.sidebarFilterSorter.initFilterSorter();

            self.selectionSpoolDialog.modal({
                minHeight: 300,
                show: true
            });
            $("#filterSelectionQueryTextfield").focus();
        }

        //////////////////////////////////////////////////////////////////////////////////////////////////// TABLE / TAB

        self.addNewSpool = function(){
            self.spoolDialog.showDialog(null, closeDialogHandler);
        }

        var LowStockColumnVisibility = function(){
            this.lp = ko.observable(true);
            this.name = ko.observable(true);
            this.barcode = ko.observable(true);
            this.min = ko.observable(true);
            this.count = ko.observable(true);
            this.ordered = ko.observable(true);
            this.deficit = ko.observable(true);
            // filament columns
            this.filament = ko.observable(true);
            this.currentWeight = ko.observable(true);
            this.minWeight = ko.observable(true);
            this.filDeficit = ko.observable(true);
            this.spoolsToOrder = ko.observable(true);
            this.filOrdered = ko.observable(true);
        }
        self.lowStockColVis = new LowStockColumnVisibility();

        self.initLowStockVisibilities = function(){
            if (!Modernizr.localstorage) return;
            var assign = function(attr){
                var key = "spoolmanager.lowstock.visible." + attr;
                if (localStorage[key] == null){
                    localStorage[key] = self.lowStockColVis[attr]();
                } else {
                    self.lowStockColVis[attr]("true" == localStorage[key]);
                }
                self.lowStockColVis[attr].subscribe(function(v){ localStorage[key] = v; });
            };
            var cols = ["lp","name","barcode","min","count","ordered","deficit",
                        "filament","currentWeight","minWeight","filDeficit","spoolsToOrder","filOrdered"];
            for (var i = 0; i < cols.length; i++) assign(cols[i]);
        }

        var TableAttributeVisibility = function (){
            this.printer = ko.observable(true);
            this.shelf = ko.observable(true);
            this.databaseId = ko.observable(false);
            this.displayName = ko.observable(true);
            this.material = ko.observable(true);
            this.lastFirstUse = ko.observable(true);
            this.weight = ko.observable(true);
            this.used = ko.observable(true);
            this.note = ko.observable(true);
            this.serialNumber = ko.observable(true);
            this.project = ko.observable(true);
        }
        self.tableAttributeVisibility = new TableAttributeVisibility();

        self.initTableVisibilities = function(){
            // load all settings from browser storage
            if (!Modernizr.localstorage) {
                // damn!!!
                return false;
            }

            assignVisibility = function(attributeName){
                var storageKey = "spoolmanager.table.visible." + attributeName;
                if (localStorage[storageKey] == null){
                    // localStorage[storageKey] = true; // default value
                    localStorage[storageKey] = self.tableAttributeVisibility[attributeName](); // default value
                } else {
                    self.tableAttributeVisibility[attributeName]( "true" == localStorage[storageKey]);
                }
                self.tableAttributeVisibility[attributeName].subscribe(function(newValue){
                    localStorage[storageKey] = newValue;
                });
            }

            assignVisibility("printer");
            assignVisibility("shelf");
            assignVisibility("databaseId");
            assignVisibility("displayName");
            assignVisibility("material");
            assignVisibility("lastFirstUse");
            assignVisibility("weight");
            assignVisibility("used");
            assignVisibility("note");
            assignVisibility("serialNumber");
            assignVisibility("project");
        }

        ///////////////////////////////////////////////////////////////////////////////////////////////// TABLE BEHAVIOR
        /* needed for Filter-Search dropdown-menu */
        $('.dropdown-menu.keep-open').click(function(e) {
            e.stopPropagation();
        });

        self.spoolItemTableHelper = new TableItemHelper(function(tableQuery, observableTableModel, observableTotalItemCount){

            // api-call
            self.apiClient.callLoadSpoolsByQuery(tableQuery, function(responseData){

                if (responseData["databaseConnectionProblem"] != null && responseData["databaseConnectionProblem"] == true){
                    self.pluginNotWorking(true);
                } else {
                    self.pluginNotWorking(false);
                }

                totalItemCount = responseData["totalItemCount"];
                allSpoolItems = responseData["allSpools"];
                var allCatalogs = responseData["catalogs"];
                console.log(allCatalogs);
        

                // assign catalogs to sidebarFilterSorter
                // self.sidebarFilterSorter.updateCatalogs(allCatalogs);
                // assign catalogs to tablehelper
                self.spoolItemTableHelper.updateCatalogs(allCatalogs);
                // assign all catalogs to editview
                self.spoolDialog.updateCatalogs(allCatalogs);

                templateSpoolsData = responseData["templateSpools"];
                self.spoolDialog.updateTemplateSpools(templateSpoolsData);
                
                dataRows = ko.utils.arrayMap(allSpoolItems, function (spoolData) {
                    var result = self.spoolDialog.createSpoolItemForTable(spoolData);
                    return result;
                });

                observableTotalItemCount(totalItemCount);
                observableTableModel(dataRows);
                return;
            });
            },
            "all",
            "databaseId",
            "hideEmptySpools"
        );

        self.showSpoolDialogAction = function(selectedSpoolItem) {

            // identify for which toolindex is the current selectedSpoolItem is selected
            var currentDatabaseId = selectedSpoolItem.databaseId();
            if (currentDatabaseId) {
                for (var i = 0; i < self.selectedSpoolsForSidebar().length; i++) {
                    spoolItem = self.selectedSpoolsForSidebar()[i]();
                    if (spoolItem !== null && spoolItem.databaseId() === currentDatabaseId) {
                        selectedSpoolItem.selectedForTool(i);
                        break;
                    }
                }
            }
            self.spoolDialog.showDialog(selectedSpoolItem, closeDialogHandler);
        };

        closeDialogHandler = function(shouldTableReload, specialAction, currentSpoolItem){

            if (specialAction === "selectSpoolForPrinting"){
                var toolIndex = currentSpoolItem.selectedForTool();
                if (toolIndex === undefined){
                    // clear current selection
                    toolIndex = -1;
                }
                self.selectSpoolForSidebar(toolIndex, currentSpoolItem);
            }

            if (shouldTableReload == true){
                self.spoolItemTableHelper.reloadItems();
                // TODO auto reload of sidebar spools without loosing selection
                self.loadSpoolsForSidebar();
            }
        }

        ///////////////////////////////////////////////////////////////////////////////////////// OCTOPRINT PRINT-BUTTON
        const origStartPrintFunction = self.printerStateViewModel.print;
        const newStartPrintFunction = function confirmSpoolSelectionBeforeStartPrint() {
                // api-call
                self.apiClient.allowedToPrint(function(responseData){
                    var result = responseData.result,
                        check, itemList;

                    var warning = "";
                    var warning2 = "";
                    if (responseData.metaOrAttributesMissing){
                        warning = "ATTENTION: Needed filament could not calculated (missing metadata or spool-fields)\n\n";
                        warning2 = " (maybe)"
                    }


                    if (result.noSpoolSelected.length) {
                        itemList = [];
                        for (item of result.noSpoolSelected) {
                            itemList.push('Tool '+item.toolIndex)
                        }
                        if (itemList.length === 1) {
                            check = confirm(
                                warning +
                                'There is no spool selected for ' + itemList[0] + ' despite it being used' + warning2 + ' by this print.\n\n' +
                                'Do you want to start the print without a selected spool?'
                            );
                        } else {
                            check = confirm(
                                warning +
                                'There are no spools selected for the following tools despite them being used' + warning2 + ' by this print:\n' +
                                '- '+ itemList.join('\n- ') + '\n\n' +
                                'Do you want to start the print without selected spools?'
                            );
                        }
                        if (!check) {
                            return;
                        }
                    }

                    buildSpoolLabel = function(item){
                        var label =  item.toolIndex+": '" + item.material + " - " + item.spoolName;

                        if (item.remainingWeight != null && typeof item.remainingWeight === 'number'){
                            label = label + " ("+item.remainingWeight.toFixed(2)  +"g)";
                        }
                        label = label + "'";
                        return label;
                    }

                    if (result.filamentNotEnough.length) {
                        itemList = [];
                        for (item of result.filamentNotEnough) {
                            var spoolLabel = buildSpoolLabel(item);
                            // itemList.push("'" + item.spoolName + "' (tool "+item.toolIndex+")");
                            itemList.push(spoolLabel);
                        }
                        if (itemList.length === 1) {
                            check = confirm(
                                warning +
                                'The selected spool for tool ' + itemList[0] + ' does not have enough remaining filament'+warning2+'.\n\n' +
                                'Do you want to start the print anyway?'
                            );
                        } else {
                            check = confirm(
                                warning +
                                'The following selected spools do not have enough remaining filament'+warning2+':\n' +
                                '- '+ itemList.join('\n- ') + '\n\n' +
                                'Do you want to start the print anyway?'
                            );
                        }
                        if (!check) {
                            return;
                        }
                    }

                    if (result.reminderSpoolSelection.length) {
                        itemList = [];
                        // for (item of result.reminderSpoolSelection) {
                        //     itemList.push(((result.reminderSpoolSelection.length>1)?("Tool "+item.toolIndex+": "):'')+"'" + item.spoolName + "'");
                        // }
                        // if (itemList.length === 1) {
                        //     check = confirm(
                        //         'Do you want to start the print with the selected spool?\n- ' + itemList[0] + '?'
                        //     );
                        // } else {
                        //     check = confirm(
                        //         "Do you want to start the print with following selected spools?\n" +
                        //         '- '+ itemList.join('\n- ')
                        //     );
                        // }
                        // build message for each tool
                        for (item of result.reminderSpoolSelection) {
                            var toolMessage = buildSpoolLabel(item);
                            if (responseData.toolOffsetEnabled && item.toolOffset != null) toolMessage += "\n--  Tool Offset:  "+item.toolOffset+'\u00B0';
                            if (responseData.bedOffsetEnabled && item.bedOffset != null) toolMessage += "\n--  Bed Offset:  "+item.bedOffset+'\u00B0';
                            if (responseData.enclosureOffsetEnabled && item.enclosureOffset != null) toolMessage += "\n--  Enclosure Offset:  "+item.enclosureOffset+'\u00B0';
                            itemList.push(toolMessage);
                        }
                        check = confirm(
                            "Do you want to start the print with following selected spools?\n" +
                            "- "+ itemList.join("\n- ")
                        );

                        if (!check) {
                            return;
                        }
                    }
                    // we are ready to go. Inform the backend and after that START PRINT
                    self.apiClient.startPrintConfirmed(function(responseData){
                        origStartPrintFunction();
                    });
                });
        };
        // overwrite loadFile
        self.filesViewModel.loadFile = function confirmSpoolSelectionOnLoadAndPrint(data, printAfterLoad) {
            // orig. SourceCode
            if (!self.filesViewModel.loginState.hasPermission(self.filesViewModel.access.permissions.FILES_SELECT)) return;

            if (!data) {
                return;
            }

            if (printAfterLoad && self.filesViewModel.listHelper.isSelected(data) && self.filesViewModel.enablePrint(data)) {
                // file was already selected, just start the print job with the newStartPrint function
                // SPOOLMANAGER-CHANGE changed OctoPrint.job.start();
                newStartPrintFunction();
            } else {
                // select file, start print job (if requested and within dimensions)
                var withinPrintDimensions = self.filesViewModel.evaluatePrintDimensions(data, true);
                var print = printAfterLoad && withinPrintDimensions;

                if (print && self.filesViewModel.settingsViewModel.feature_printStartConfirmation()) {
                    showConfirmationDialog({
                        message: gettext("This will start a new print job. Please check that the print bed is clear."),
                        question: gettext("Do you want to start the print job now?"),
                        cancel: gettext("No"),
                        proceed: gettext("Yes"),
                        onproceed: function() {
                            OctoPrint.files.select(data.origin, data.path, false).done(function () {
                                if (print){
                                    newStartPrintFunction();
                                }
                            });
                        },
                        nofade: true
                    });
                } else {
                    OctoPrint.files.select(data.origin, data.path, false).done(function () {
                                                                                    if (print){
                                                                                     newStartPrintFunction();
                                                                                    }
                                                                                });
                }
            }
        };

        self.printerStateViewModel.print = newStartPrintFunction;

        //////////////////////////////////////////////////////////////////////////////////////// PUBLIC VIEWMODEL - APIs
        // e.g. for CostEstaminator-Plugin
        self.api_getSelectedSpoolInformations = function(){
            var result = [];
            var spoolItem;
            for (var i=0; i<self.selectedSpoolsForSidebar().length; i++) {
                var spoolData = null;
                spoolItem = self.selectedSpoolsForSidebar()[i]();
                if (spoolItem !== null) {
                    spoolData = {
                        toolIndex: i,
                        databaseId: spoolItem.databaseId(),
                        spoolName: spoolItem.displayName(),
                        vendor: spoolItem.vendor ? spoolItem.vendor() : null,
                        project: spoolItem.project ? spoolItem.project() : null,
                        material: spoolItem.material ? spoolItem.material() : null,
                        diameter: spoolItem.diameter ? spoolItem.diameter() : null,
                        density: spoolItem.density ? spoolItem.density() : null,
                        colorName: spoolItem.colorName ? spoolItem.colorName() : null,
                        color: spoolItem.color ? spoolItem.color() : null,
                        cost: spoolItem.cost ? spoolItem.cost() : null,
                        weight: spoolItem.totalWeight ? spoolItem.totalWeight() : null
                    };
                }
                result.push(spoolData);
            }
            return result;
        }

        //////////////////////////////////////////////////////////////////////////////////////////////// OCTOPRINT HOOKS
        self.onStartup = function onStartupCallback() {
            // Replace Filementview in sidebar to show weight instead of volumne
            self.replaceFilamentView();
        };

        self.onBeforeBinding = function() {
            // Register Knockout Components
            new SpoolSelectionTableComp().registerSpoolSelectionTableComp();

            // assign current pluginSettings
            self.pluginSettings = self.settingsViewModel.settings.plugins[PLUGIN_ID];
            // load browser stored settings (includs TabelVisibility and pageSize, ...)
            loadSettingsFromBrowserStore();

            // resetSettings-Stuff
             new ResetSettingsUtilV3(self.pluginSettings).assignResetSettingsFeature(PLUGIN_ID, function(data){
                // no additional reset function needed in V2
             });

            // Load all Spools
            self.loadSpoolsForSidebar();
            // Edit Spool Dialog Binding
            self.spoolDialog.initBinding(self.apiClient, self.pluginSettings, self.printerProfilesViewModel);
            // Import Dialog
            self.csvImportDialog.init(self.apiClient);
            // Database connection problem dialog
            self.databaseConnectionProblemDialog.init(self.apiClient);
            // Select Spool Dialog (no special binding)
            self.selectionSpoolDialog = $("#dialog_spool_selection");



            // Settings - Color-Picker
            self.componentFactory = new ComponentFactory();
            var fillColorViewModel = self.componentFactory.createColorPicker("qrcode-fill-color-picker");
            this.qrCodeFillColor = fillColorViewModel.selectedColor;
            // Init with current value
            this.qrCodeFillColor(self.pluginSettings.qrCodeFillColor());  // needed
            this.qrCodeFillColor.subscribe(function(newColorValue){
                self.pluginSettings.qrCodeFillColor(newColorValue);
            });

            var backgroundColorViewModel = self.componentFactory.createColorPicker("qrcode-background-color-picker");
            this.qrCodeBackgroundColor = backgroundColorViewModel.selectedColor;
            // Init with current value
            this.qrCodeBackgroundColor(self.pluginSettings.qrCodeBackgroundColor());  // needed
            this.qrCodeBackgroundColor.subscribe(function(newColorValue){
                self.pluginSettings.qrCodeBackgroundColor(newColorValue);
            });

            // self.pluginSettings.hideEmptySpoolsInSidebar.subscribe(function(newCheckedVaue){
            //     var payload = {
            //             "hideEmptySpoolsInSidebar": newCheckedVaue
            //         };
            //     OctoPrint.settings.savePluginSettings(PLUGIN_ID, payload);
            //     // self.loadSpoolsForSidebar();
            //     // self.filterSelectionSidebar();
            // });
            // self.pluginSettings.hideInactiveSpoolsInSidebar.subscribe(function(newCheckedVaue){
            //     var payload = {
            //             "hideInactiveSpoolsInSidebar": newCheckedVaue
            //         };
            //     OctoPrint.settings.savePluginSettings(PLUGIN_ID, payload);
            //     // self.loadSpoolsForSidebar();
            //     // self.filterSelectionSidebar();
            // });

            // needed after the tool-count is changed
            self.settingsViewModel.printerProfiles.currentProfileData.subscribe(self.loadSpoolsForSidebar);

			try {
				var instanceNameObservable = self.settingsViewModel.settings.appearance.name;
				self.octoPrintInstanceName(instanceNameObservable());
				self.currentPrinterNumber(self._parsePrinterNumberFromInstanceName(instanceNameObservable()));
				instanceNameObservable.subscribe(function(newName){
					self.octoPrintInstanceName(newName);
					self.currentPrinterNumber(self._parsePrinterNumberFromInstanceName(newName));
					self.loadSheetsStateForSidebar();
				});
			} catch (e) {
				self.octoPrintInstanceName(null);
				self.currentPrinterNumber(null);
			}

			self.loadSheets();
			self.loadSheetsStateForSidebar();
			self.loadConsumables();
			self.loadFilamentTypes();

			// Consumables CSV Import - file upload wiring
			var consumablesCsvUploadButton = $("#consumables-importcsv-upload");
			consumablesCsvUploadButton.fileupload({
				dataType: "json",
				maxNumberOfFiles: 1,
				autoUpload: false,
				headers: OctoPrint.getRequestHeaders(),
				add: function(e, data) {
					if (data.files.length === 0) {
						return false;
					}
					self.consumablesCsvFileUploadName(data.files[0].name);
					self.consumablesCsvImportUploadData = data;
				},
				done: function(e, data) {
					self.consumablesCsvImportInProgress(false);
					self.consumablesCsvFileUploadName(undefined);
					self.consumablesCsvImportUploadData = undefined;
				},
				error: function(response, data, errorMessage){
					self.consumablesCsvImportInProgress(false);
				}
			});
        }

        self.onAfterBinding = function() {
            self.spoolDialog.afterBinding();
            self.downloadDatabaseUrl(self.apiClient.getDownloadDatabaseUrl());

// testing            self.spoolDialog.showDialog(null, closeDialogHandler);
        }

        self.onSettingsShown = function(){
            if (self.isFilamentManagerPluginAvailable() == false){
                self.apiClient.callAdditionalSettings(function(responseData) {
                    self.isFilamentManagerPluginAvailable(responseData.isFilamentManagerPluginAvailable);
                });
            }
        }

        // receive data from server
        self.onDataUpdaterPluginMessage = function (plugin, data) {
            if (plugin != PLUGIN_ID) {
                return;
            }

            if ("initalData" == data.action){

                self.pluginNotWorking(data.pluginNotWorking);
                self.isFilamentManagerPluginAvailable(data.isFilamentManagerPluginAvailable);
                var spoolsData = data.selectedSpools,
                    slot, spoolData, spoolItem;
                for(var i=0; i<self.selectedSpoolsForSidebar().length; i++) {
                    slot = self.selectedSpoolsForSidebar()[i];
                    spoolData = (i < spoolsData.length) ? spoolsData[i] : null;
                    spoolItem = spoolData ? self.spoolDialog.createSpoolItemForTable(spoolData) : null;
                    slot(spoolItem);
                }

                return;
            }
            if ("showPopUp" == data.action){
                self.showPopUp(data.type, data.title, data.message, data.autoclose);
                return;
            }
            if ("reloadTable" == data.action){
                self.spoolItemTableHelper.reloadItems();
                return;
            }
            if ("reloadTable and sidebarSpools" == data.action){
                self.spoolItemTableHelper.reloadItems();
                self.loadSpoolsForSidebar();
                return;
            }
            if ("reloadSheets" == data.action){
                self.loadSheets();
                self.loadSheetsStateForSidebar();
                return;
            }
            if ("csvImportStatus" == data.action){
                self.csvImportDialog.updateText(data);
                return;
            }
            if ("consumablesCsvImportStatus" == data.action){
                self._handleConsumablesCsvImportStatus(data);
                return;
            }
            if ("errorPopUp" == data.action){
                self.showPopUp("error", 'ERROR:' + data.title, data.message, data.autoclose);
                return;
            }
            if ("requiredFilamentChanged" == data.action){
                self.updateRequiredFilament(data);
                return;
            }
            if ("extrusionValuesChanged" == data.action){
                self.updateExtrusionValues(data.extrusionValues);
                return;
            }


            if ("showConnectionProblem" == data.action){
// TODO enable problem dialog again
//                new PNotify({
//                    title: 'ERROR:' + data.title,
//                    text: data.message,
//                    type: "error",
//                    hide: false
//                    });

//                self.databaseConnectionProblemDialog.showDialog(data, function(){
//                    // nothing special here, everything is done in the dialog
//                });

                return;
            }

        }

        self.onEventplugin_spoolmanager_spool_weight_updated_after_print = function(payload) {
            try {
                if (!payload) {
                    return;
                }

                console.info("[SpoolManager] spool_weight_updated_after_print", payload);

                var showPopup = false;
                try {
                    showPopup = (
                        self.pluginSettings &&
                        self.pluginSettings.extrusionDebuggingEnabled &&
                        self.pluginSettings.extrusionDebuggingEnabled() === true
                    );
                } catch (e) {
                    showPopup = false;
                }

                if (!showPopup) {
                    return;
                }

                var toolId = (payload.toolId != null) ? payload.toolId : "?";
                var spoolName = payload.spoolName || "";
                var source = payload.calculationSource || "unknown";
                var usedLength = payload.usedLengthThisPrint;
                var usedWeight = payload.usedWeightThisPrint;
                var odometerLength = payload.odometerLengthThisPrint;
                var metadataLength = payload.metadataLengthThisPrint;

                var msg = "Tool " + toolId + ": " + spoolName + "<br/>";
                msg += "Used length: " + (usedLength != null ? usedLength : "n/a") + " mm<br/>";
                msg += "Used weight: " + (usedWeight != null ? usedWeight : "n/a") + " g<br/>";
                msg += "Source: " + source + "<br/>";
                msg += "Odometer length: " + (odometerLength != null ? odometerLength : "n/a") + " mm<br/>";
                msg += "Metadata length: " + (metadataLength != null ? metadataLength : "n/a") + " mm";

                if (toolId === 0 || toolId === "0") {
                    self.showPopUp("info", "Filament usage (this print)", msg, true);
                }
            } catch (e) {
            }
        }

        self.onTabChange = function(next, current){
            try {
                if ($(next).find("#tab_spoolOverview").length) {
                    self.spoolItemTableHelper.reloadItems();
                }
                if ($(next).find("#tab_sheetsOverview").length) {
                    self.loadSheets();
                }
                if ($(next).find("#tab_consumablesOverview").length) {
                    self.loadConsumables();
                }
                if ($(next).find("#tab_lowStockOverview").length) {
                    self.spoolItemTableHelper.reloadItems();
                    self.loadConsumables();
                    self.loadFilamentTypes();
                }
            } catch (e) {
            }
            //alert("Next:"+next +" Current:"+current);
            if ("#tab_plugin_PrintJobHistory" == next){
                //self.reloadTableData();
            }
        }

        self.onAfterTabChange = function(current, previous){
            // alert("Next:"+next +" Current:"+previous);
            //if ("#tab_plugin_SpoolManager" == current){
            // var selectedSpoolId = getUrlParameter("selectedSpoolId");
            // if (selectedSpoolId) {
            //     console.error("Id"+selectedSpoolId);
            // }
            var tabHashCode = window.location.hash;
            // QR-Code-Call: We can only contain -spoolId on the very first page
            if (tabHashCode.includes("#tab_plugin_SpoolManager-spoolId")){
                var selectedSpoolId = tabHashCode.replace("-spoolId", "").replace("#tab_plugin_SpoolManager", "");
                selectedSpoolId = parseInt(selectedSpoolId);
                console.info('Loading spool: '+selectedSpoolId);
                var alreadyInTool = self.getSpoolItemSelectedTool(selectedSpoolId);
                if (alreadyInTool !== null) {
                    alert('This spool is already selected for tool ' + alreadyInTool + '!');
                    return;
                }
                if (self.printerStateViewModel.isPrinting()) {
                    // not doing this while printing
                    return;
                }
                // - Load SpoolItem from Backend
                // - Open SpoolItem
                // methode signature: toolIndex, databaseId, commitCurrentSpoolValues, responseHandler
                var commitCurrentSpoolValues = false;
                var toolIndex = 0
                self.apiClient.callSelectSpool(0, selectedSpoolId, commitCurrentSpoolValues, function(responseData){
                    //Select the SpoolManager tab
                    $('a[href="#tab_plugin_SpoolManager"]').tab('show')
                    var spoolItem = null;
                    var spoolData = responseData["selectedSpool"];
                    if (spoolData != null){
                        spoolItem = self.spoolDialog.createSpoolItemForTable(spoolData);
                        spoolItem.selectedFromQRCode(true);
                        self.selectedSpoolsForSidebar()[0](spoolItem);
                        self.showSpoolDialogAction(spoolItem);
                    }
                });
            }
            //}
        }

    }

    /* view model class, parameters for constructor, container to bind to
     * Please see http://docs.octoprint.org/en/master/plugins/viewmodels.html#registering-custom-viewmodels for more details
     * and a full list of the available options.
     */
    OCTOPRINT_VIEWMODELS.push({
        construct: SpoolManagerViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: [
            "loginStateViewModel",
            "settingsViewModel",
            "printerStateViewModel",
            "filesViewModel",
            "printerProfilesViewModel"
        ],
        // Elements to bind to, e.g. #settings_plugin_SpoolManager, #tab_plugin_SpoolManager, ...
        elements: [
            document.getElementById("settings_spoolmanager"),
            document.getElementById("tab_spoolOverview"),
            document.getElementById("tab_sheetsOverview"),
            document.getElementById("tab_consumablesOverview"),
            document.getElementById("tab_lowStockOverview"),
            document.getElementById("modal-dialogs-spoolManager"),
            document.getElementById("sidebar_spool_select")
        ]
    });
});
