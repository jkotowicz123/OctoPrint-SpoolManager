/**
 * loadItemsFunction,
 * defaultPageSize,
 * defaultSortColumn,
 * defaultFilterName
 */

defaultSortColumn = "displayName"
defaultPageSize = "all"
defaultFilterName = "hideEmptySpools"

$(document).ready(function() {
	$('[data-toggle="toggle"]').change(function(){
		$(this).parents().next('.hide').toggle();
	});
});

function TableItemHelper(loadItemsFunction, defaultPageSize, defaultSortColumn, defaultFilterName){

    var self = this;
    var totalFilamentsWeight = 0;

    var _pureComputed = ko.pureComputed ? ko.pureComputed : ko.computed;

    self.loadItemsFunction = loadItemsFunction;
    self.items = ko.observableArray([]);
    self.totalItemCount = ko.observable(0);

    self.groupedItemsByDisplayName = ko.observableArray([]);

    self.groupSortMode = ko.observable("name");

    self.toggleGroupSortMode = function () {
        if (self.groupSortMode() === "name") {
            self.groupSortMode("remaining");
        } else {
            self.groupSortMode("name");
        }
        self._rebuildGroupsByDisplayName();
    };

    self.groupSortLabel = _pureComputed(function () {
        return self.groupSortMode() === "name" ? "Sort groups by remaining" : "Sort groups by name";
    });

    self.toggleAllGroups = function () {
        var groups = self.groupedItemsByDisplayName();
        if (!groups) {
            return;
        }

        var anyExpanded = false;
        for (var i = 0; i < groups.length; i++) {
            if (groups[i] && groups[i].expanded && groups[i].expanded()) {
                anyExpanded = true;
                break;
            }
        }

        for (var j = 0; j < groups.length; j++) {
            if (groups[j] && groups[j].expanded) {
                groups[j].expanded(!anyExpanded);
            }
        }
    };

    self.toggleAllGroupsLabel = _pureComputed(function () {
        var groups = self.groupedItemsByDisplayName();
        if (!groups || groups.length === 0) {
            return "Collapse all";
        }
        for (var i = 0; i < groups.length; i++) {
            if (groups[i] && groups[i].expanded && groups[i].expanded()) {
                return "Collapse all";
            }
        }
        return "Expand all";
    });

    self.totalFilamentsWeight = _pureComputed(function () {
        var sum = 0;
        var items = self.items();
        if (!items) {
            return 0;
        }
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (!item) {
                continue;
            }
            var remainingWeight = ko.utils.unwrapObservable(item.remainingWeight);
            var w = parseFloat(remainingWeight);
            if (!isNaN(w)) {
                sum += w;
            }
        }
        return Math.round(sum * 100) / 100;
    });

    self._rebuildGroupsByDisplayName = function () {
        var items = self.items();
        if (!items) {
            self.groupedItemsByDisplayName([]);
            return;
        }

        var expandedByName = {};
        var prevGroups = self.groupedItemsByDisplayName();
        if (prevGroups) {
            for (var p = 0; p < prevGroups.length; p++) {
                var prev = prevGroups[p];
                if (prev && prev.displayName != null && prev.expanded) {
                    expandedByName[prev.displayName] = prev.expanded();
                }
            }
        }

        var groups = {};
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (!item) {
                continue;
            }

            var displayName = ko.utils.unwrapObservable(item.displayName);
            var key = (displayName != null && ("" + displayName).length > 0) ? ("" + displayName) : "(no name)";

            if (!groups[key]) {
                groups[key] = {
                    displayName: key,
                    spoolCount: 0,
                    totalRemainingWeight: 0,
                    items: [],
                    expanded: ko.observable(expandedByName[key] !== undefined ? expandedByName[key] : true)
                };
            }

            groups[key].items.push(item);
            groups[key].spoolCount += 1;

            var remainingWeight = ko.utils.unwrapObservable(item.remainingWeight);
            var w = parseFloat(remainingWeight);
            if (!isNaN(w)) {
                groups[key].totalRemainingWeight += w;
            }
        }

        var result = [];
        for (var name in groups) {
            if (Object.prototype.hasOwnProperty.call(groups, name)) {
                groups[name].items.sort(function (a, b) {
                    var aVal = parseFloat(ko.utils.unwrapObservable(a.remainingWeight));
                    var bVal = parseFloat(ko.utils.unwrapObservable(b.remainingWeight));

                    if (isNaN(aVal)) {
                        aVal = Number.POSITIVE_INFINITY;
                    }
                    if (isNaN(bVal)) {
                        bVal = Number.POSITIVE_INFINITY;
                    }

                    return aVal - bVal;
                });
                groups[name].totalRemainingWeight = Math.round(groups[name].totalRemainingWeight * 100) / 100;
                result.push(groups[name]);
            }
        }

        if (self.groupSortMode && self.groupSortMode() === "remaining") {
            result.sort(function (a, b) {
                return a.totalRemainingWeight - b.totalRemainingWeight;
            });
        } else {
            result.sort(function (a, b) {
                return ("" + a.displayName).toLowerCase().localeCompare(("" + b.displayName).toLowerCase());
            });
        }

        self.groupedItemsByDisplayName(result);
    };

    self.items.subscribe(function () {
        self._rebuildGroupsByDisplayName();
    });

    self.collapseAllGroups = function () {
        self.toggleAllGroups();
    };

    // paging
    self.pageSizeOptions = ko.observableArray([10, 25, 50, 100, "all"])
    self.selectedPageSize = ko.observable(defaultPageSize)
    self.pageSize = ko.observable(self.selectedPageSize() === "all" ? 0 : self.selectedPageSize());
    self.currentPage = ko.observable(0);
    // Sorting
    self.sortColumn = ko.observable("displayName");
    self.sortOrder = ko.observable("desc");
    // Filtering - all, hide empty, hide inactive
    //self.filterOptions = ["all", "onlySuccess", "onlyFailed"];
    self.selectedFilterName = ko.observable("hideEmptySpools");

    self.selectedFilterNameArrayKO = ko.observableArray(defaultFilterName ? [defaultFilterName] : []);

    // Filtering - Material
    self.allMaterials = ko.observableArray([]);
    self.showAllMaterialsForFilter = ko.observable(true);
    self.selectedMaterialsForFilter = ko.observableArray();
    // Filtering - Vendor
    self.allVendors = ko.observableArray([]);
    self.showAllVendorsForFilter = ko.observable(true);
    self.selectedVendorsForFilter = ko.observableArray();
    // Filtering - Project
    self.allProjects = ko.observableArray([]);
    self.showAllProjectsForFilter = ko.observable(true);
    self.selectedProjectsForFilter = ko.observableArray();
    // Filtering - Color
    self.allColors = ko.observableArray([]);
    self.showAllColorsForFilter = ko.observable(true);
    self.selectedColorsForFilter = ko.observableArray();

    self.isInitialLoadDone = false;
    self._catalogsInitialized = false;
    // ############################################################################################### private functions


    self._evalFilter = function(allItems, selectedItems){
        var filterResult = ["all"];
        if (allItems.length != selectedItems.length){
            filterResult = selectedItems;
        }
        return filterResult;
        // return selectedItems;
    }

    self._loadItems = function(){
        var selectedPageSize = self.selectedPageSize();

        var from = 0;
        var to = 0;

        if ("all" != selectedPageSize){
            from = Math.max(self.currentPage() * self.pageSize(), 0);
    //        var to = Math.min(from + self.pageSize(), self.totalItemCount());
            to = self.pageSize();
            if (to == 0){
                to = self.pageSize();
            }
        }

        var materialFilter = self._evalFilter(self.allMaterials(), self.selectedMaterialsForFilter());
        var vendorFilter = self._evalFilter(self.allVendors(), self.selectedVendorsForFilter());
        var projectFilter = self._evalFilter(self.allProjects(), self.selectedProjectsForFilter());
        var colorFilter = self._evalFilter(self.allColors(), self.selectedColorsForFilter());

        var selectedFilterNamesString = "all";
        var selectedFilterNames = self.selectedFilterNameArrayKO();
        if (selectedFilterNames.length != 0){
            selectedFilterNamesString = selectedFilterNames.sort().join();
        }

        var tableQuery = {
            "selectedPageSize": selectedPageSize,
            "from": from,
            "to": to,
            "sortColumn": self.sortColumn(),
            "sortOrder": self.sortOrder(),
            "filterName": self.selectedFilterName(),
            "filterName": selectedFilterNamesString,
            "materialFilter": materialFilter,
            "vendorFilter": vendorFilter,
            "projectFilter":projectFilter,
            "colorFilter": colorFilter
        };

        self.loadItemsFunction( tableQuery, self.items, self.totalItemCount );
    }

    self.currentPage.subscribe(function(newPageIndex) {
        self._loadItems()
    });

    self.selectedPageSize.subscribe(function(newPageSize) {
        self.currentPage(0);
        if ("all" == newPageSize){
            self.pageSize(0);
        } else {
            self.pageSize(newPageSize);
        }
        // TODO Optimize. provide the defaultpagesize during creation of the helper (default page size)
        self._loadItems()
    });

    self.selectedMaterialsForFilter.subscribe(function(newValues) {
        if (self.selectedMaterialsForFilter().length > 0){
            self.showAllMaterialsForFilter(true);
        } else{
            self.showAllMaterialsForFilter(false);
        }
        // TODO Optimize enable after the values where initialy changed
        self.reloadItems();
    });
    self.selectedVendorsForFilter.subscribe(function(newValues) {
        if (self.selectedVendorsForFilter().length > 0){
            self.showAllVendorsForFilter(true);
        } else{
            self.showAllVendorsForFilter(false);
        }
        // TODO Optimize enable after the values where initialy changed
        self.reloadItems();
    });
    self.selectedProjectsForFilter.subscribe(function(newValues) {
        if (self.selectedProjectsForFilter().length > 0){
            self.showAllProjectsForFilter(true);
        } else{
            self.showAllProjectsForFilter(false);
        }
        // TODO Optimize enable after the values where initialy changed
        self.reloadItems();
    });
    self.selectedColorsForFilter.subscribe(function(newValues) {
        if (self.selectedColorsForFilter().length == 0){
            self.showAllColorsForFilter(true);
            self.reloadItems();
        } else{
            self.showAllColorsForFilter(false);
        }

        if (self.selectedColorsForFilter().length != 0){
            // TODO Optimize enable after the values where initialy changed
            self.reloadItems();
        }

    });

    self._evalFilterLabel = function(allArray, selectionArray){
        // check if all selected
        var selectionCount = 0
        for (let item of allArray) {
            if (selectionArray.indexOf(item) != -1){
                selectionCount++;
            }
        }
        var allSelected = selectionCount ==  allArray.length
        return allSelected == true ? "all" : selectionArray.length;
    };

    // ################################################################################################ public functions
    self.reloadItems = function(){
        self._loadItems();
    }

    self.updateCatalogs = function(catalogs){
        self.allCatalogs = catalogs;
        var materialsCatalog = self.allCatalogs["materials"];
        var vendorsCatalog = self.allCatalogs["vendors"];
        var projectsCatalog = self.allCatalogs["projects"];
        var colorsCatalog = self.allCatalogs["colors"];

        self.allMaterials(materialsCatalog);
        self.allVendors(vendorsCatalog);
        self.allProjects(projectsCatalog);
        self.allColors(colorsCatalog);

        if (self._catalogsInitialized === false){
            self._catalogsInitialized = true;

            self.selectedMaterialsForFilter().length = 0;
            ko.utils.arrayPushAll(self.selectedMaterialsForFilter(), self.allMaterials());
            self.selectedMaterialsForFilter.valueHasMutated();

            self.selectedVendorsForFilter().length = 0;
            ko.utils.arrayPushAll(self.selectedVendorsForFilter(), self.allVendors());
            self.selectedVendorsForFilter.valueHasMutated();

            self.selectedProjectsForFilter().length = 0;
            ko.utils.arrayPushAll(self.selectedProjectsForFilter(), self.allProjects());
            self.selectedProjectsForFilter.valueHasMutated();

            self.selectedColorsForFilter().length = 0;
            for (let i = 0; i < self.allColors().length; i++) {
                let colorObject = self.allColors()[i];
                if (colorObject && colorObject.colorId){
                    self.selectedColorsForFilter().push(colorObject.colorId);
                }
            }
            self.selectedColorsForFilter.valueHasMutated();
        }
    }

    self.paginatedItems = ko.dependentObservable(function() {
        if (self.items() === undefined) {
            return [];
        } else if (self.pageSize() === 0) {
            return self.items();
        } else {
            if (self.isInitialLoadDone == false){
                self.isInitialLoadDone = true;
                self._loadItems();
            }
            return self.items();
        }
    });


    // ############################################## SORTING
    self.changeSortOrder = function(newSortColumn){
        if (newSortColumn == self.sortColumn()){
            // toggle
            if ("desc" == self.sortOrder()){
                self.sortOrder("asc");
            } else {
               self.sortOrder("desc");
            }
        } else {
            self.sortColumn(newSortColumn);
            self.sortOrder("asc");
        }
        self.currentPage(0);
        self._loadItems();
    }

    self.sortOrderLabel = function(sortColumn){
        if (sortColumn == self.sortColumn()){
            // toggle
            if ("desc" == self.sortOrder()){
                return ("(descending)");
            } else {
               return ("(ascending)");
            }
        }
        return "";
    }

    // ############################################## FILTERING
    self.changeFilter = function(newFilterName) {
        self.selectedFilterName(newFilterName)
        self.currentPage(0);
        self._loadItems();
    };

    self.toggleFilter = function(newFilterName){
        if (self.selectedFilterNameArrayKO().includes(newFilterName)){
            self.selectedFilterNameArrayKO.remove(newFilterName);
        } else {
            // Add the Filter
            self.selectedFilterNameArrayKO.push(newFilterName);
        }
        self.currentPage(0);
        self._loadItems();
    }

    self.isFilterSelected = function(filterName) {
        // return self.selectedFilterName() == filterName;
        return self.selectedFilterNameArrayKO().includes(filterName);
    };

    self.doFilterSelectAll = function(data, catalogName){
        let checked;
        switch (catalogName) {
            case "material":
                checked = self.showAllMaterialsForFilter();
                if (checked == true) {
                    self.selectedMaterialsForFilter().length = 0;
                    ko.utils.arrayPushAll(self.selectedMaterialsForFilter(), self.allMaterials());
                } else {
                    self.selectedMaterialsForFilter.removeAll();
                }
                break;
            case "vendor":
                checked = self.showAllVendorsForFilter();
                if (checked == true) {
                    self.selectedVendorsForFilter().length = 0;
                    ko.utils.arrayPushAll(self.selectedVendorsForFilter(), self.allVendors());
                } else {
                    self.selectedVendorsForFilter.removeAll();
                }
                break;
            case "project":
                checked = self.showAllProjectsForFilter();
                if (checked == true) {
                    self.selectedProjectsForFilter().length = 0;
                    ko.utils.arrayPushAll(self.selectedProjectsForFilter(), self.allProjects());
                } else {
                    self.selectedProjectsForFilter.removeAll();
                }
                break;
            case "color":
                checked = self.showAllColorsForFilter();
                if (checked == true) {
                    self.selectedColorsForFilter().length = 0;
                    // we are using an colorId as a checked attribute, we can just move the color-objects to the selectedArrary
                    // ko.utils.arrayPushAll(self.spoolItemTableHelper.selectedColorsForFilter, self.spoolItemTableHelper.allColors());
                    for (let i = 0; i < self.allColors().length; i++) {
                        let colorObject = self.allColors()[i];
                        self.selectedColorsForFilter().push(colorObject.colorId);
                    }
                    self.selectedColorsForFilter.valueHasMutated();
                } else {
                    self.selectedColorsForFilter.removeAll();
                }
                break;
        }
    }

    self.buildFilterLabel = function(filterLabelName){
        // spoolItemTableHelper.selectedColorsForFilter().length == spoolItemTableHelper.allColors().length ? 'all' : spoolItemTableHelper.selectedColorsForFilter().length
        // to detecting all, we can't use the length, because if just the color is changed then length is still true
        // so we need to compare each value
        if ("color" == filterLabelName){
            var selectionArray = self.selectedColorsForFilter(); // array of colorIds [#ffa500;orange, #ffffff;white]
            var allColorArray = self.allColors(); // array of object with 'colorId=#ffa500;orange','color=#ffa500','colorName="orange"'
            // check if all colors selected
            var selectionCount = 0
            for (let colorItem of allColorArray) {
                var colorId = colorItem.colorId;
                if (selectionArray.indexOf(colorId) != -1){
                    selectionCount++;
                }
            }
            var allColorsSelected = selectionCount ==  allColorArray.length
            return allColorsSelected == true ? "all" : self.selectedColorsForFilter().length;
        }
        if ("material" == filterLabelName){
            return self._evalFilterLabel(self.allMaterials(), self.selectedMaterialsForFilter());
        }
        if ("vendor" == filterLabelName){
            return self._evalFilterLabel(self.allVendors(), self.selectedVendorsForFilter());
        }
        if ("project" == filterLabelName){
            return self._evalFilterLabel(self.allProjects(), self.selectedProjectsForFilter());
        }

        return "not defined:" + filterLabelName;
    }

    // ############################################## PAGING
    self.changePage = function(newPage) {
        if (newPage < 0 || newPage > self.lastPage())
            return;
        self.currentPage(newPage);
    };

    self.prevPage = function() {
        if (self.currentPage() > 0) {
            self.currentPage(self.currentPage() - 1);
        }
    };
    self.nextPage = function() {
        if (self.currentPage() < self.lastPage()) {
            self.currentPage(self.currentPage() + 1);
        }
    };
    self.lastPage = ko.dependentObservable(function() {
        return (self.pageSize() === 0 ? 1 :
                Math.ceil(self.totalItemCount() / self.pageSize()) - 1);
    });

   self.pages = ko.dependentObservable(function() {
        var pages = [];
        var i;

        if (self.pageSize() === 0) {
            pages.push({ number: 0, text: 1 });
        } else if (self.lastPage() < 7) {
            for (i = 0; i < self.lastPage() + 1; i++) {
                pages.push({ number: i, text: i+1 });
            }
        } else {
            pages.push({ number: 0, text: 1 });
            if (self.currentPage() < 5) {
                for (i = 1; i < 5; i++) {
                    pages.push({ number: i, text: i+1 });
                }
                pages.push({ number: -1, text: "…"});
            } else if (self.currentPage() > self.lastPage() - 5) {
                pages.push({ number: -1, text: "…"});
                for (i = self.lastPage() - 4; i < self.lastPage(); i++) {
                    pages.push({ number: i, text: i+1 });
                }
            } else {
                pages.push({ number: -1, text: "…"});
                for (i = self.currentPage() - 1; i <= self.currentPage() + 1; i++) {
                    pages.push({ number: i, text: i+1 });
                }
                pages.push({ number: -1, text: "…"});
            }
            pages.push({ number: self.lastPage(), text: self.lastPage() + 1})
        }
        return pages;
    });

    if (self.isInitialLoadDone == false){
        self.isInitialLoadDone = true;
        self._loadItems();
    }
    
}
