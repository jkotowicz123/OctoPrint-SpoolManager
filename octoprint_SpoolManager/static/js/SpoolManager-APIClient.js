

function SpoolManagerAPIClient(pluginId, baseUrl) {

    this.pluginId = pluginId;
    this.baseUrl = baseUrl;

    // see https://gomakethings.com/how-to-build-a-query-string-from-an-object-with-vanilla-js/
    var _buildRequestQuery = function (data) {
        // If the data is already a string, return it as-is
        if (typeof (data) === 'string') return data;

        // Create a query array to hold the key/value pairs
        var query = [];

        // Loop through the data object
        for (var key in data) {
            if (data.hasOwnProperty(key)) {

                // Encode each key and value, concatenate them into a string, and push them to the array
                query.push(encodeURIComponent(key) + '=' + encodeURIComponent(data[key]));
            }
        }
        // Join each item in the array with a `&` and return the resulting string
        return query.join('&');

    };

    var _addApiKeyIfNecessary = function(urlContext){
        if (UI_API_KEY){
            urlContext = urlContext + "?apikey=" + UI_API_KEY;
        }
        return urlContext;
    }

    this.getExportUrl = function(exportType, databaseInUse){
        return _addApiKeyIfNecessary("./plugin/" + this.pluginId + "/exportSpools/" + exportType + "?instance=" + databaseInUse);
    }

    this.getSampleCSVUrl = function(){
        return _addApiKeyIfNecessary("./plugin/" + this.pluginId + "/sampleCSV");
    }

    //////////////////////////////////////////////////////////////////////////////// LOAD AdditionalSettingsValues
    this.callAdditionalSettings = function (responseHandler){
        var urlToCall = this.baseUrl + "api/plugin/"+this.pluginId+"?action=additionalSettingsValues";
        $.ajax({
            url: urlToCall,
            type: "GET"
        }).always(function( data ){
            responseHandler(data)
        });
    }

    this.callGetMmuRouting = function (successHandler, errorHandler){
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/mmuRouting",
            dataType: "json",
            type: "GET"
        }).done(function(data){
            successHandler(data);
        }).fail(function(xhr){
            if (errorHandler) errorHandler(xhr);
        });
    }

    this.callUpdateMmuRouting = function (payload, successHandler, errorHandler){
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/mmuRouting",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload || {}),
            type: "PUT"
        }).done(function(data){
            successHandler(data);
        }).fail(function(xhr){
            if (errorHandler) errorHandler(xhr);
        });
    }
    //////////////////////////////////////////////////////////////////////////////// LOAD DatabaseMetaData
    this.loadDatabaseMetaData = function (responseHandler){
        var urlToCall = this.baseUrl + "plugin/"+this.pluginId+"/loadDatabaseMetaData";
        $.ajax({
            url: urlToCall,
            type: "GET"
        }).always(function( data ){
            responseHandler(data)
        });
    }
    //////////////////////////////////////////////////////////////////////////////// TEST DatabaseConnection
    this.testDatabaseConnection = function (databaseSettings, responseHandler){
        jsonPayload = ko.toJSON(databaseSettings)

        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/testDatabaseConnection",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: jsonPayload,
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callSaveConsumable = function (consumableItem, responseHandler){
        jsonPayload = ko.toJSON(consumableItem)

        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/saveConsumable",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: jsonPayload,
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callUpdateConsumableStock = function (payload, responseHandler){
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/updateConsumableStock",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callAdjustConsumableCount = function (payload, responseHandler){
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/adjustConsumableCount",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callAdjustConsumableOrdered = function (payload, responseHandler){
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/adjustConsumableOrdered",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    //////////////////////////////////////////////////////////////////////////////// CONFIRM DatabaseConnectionPoblem
    this.confirmDatabaseProblemMessage = function (responseHandler){
        $.ajax({
            //url: API_BASEURL + "plugin/"+PLUGIN_ID+"/loadPrintJobHistory",
            url: this.baseUrl + "plugin/" + this.pluginId + "/confirmDatabaseProblemMessage",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }


    //////////////////////////////////////////////////////////////////////////////// LOAD FILTERED/SORTED PrintJob-Items
    this.callLoadSpoolsByQuery = function (tableQuery, responseHandler){
        query = _buildRequestQuery(tableQuery);
        urlToCall = this.baseUrl + "plugin/"+this.pluginId+"/loadSpoolsByQuery?"+query;
        $.ajax({
            //url: API_BASEURL + "plugin/"+PLUGIN_ID+"/loadPrintJobHistory",
            url: urlToCall,
            type: "GET"
        }).always(function( data ){
            responseHandler(data)
            //shoud be done by the server to make sure the server is informed countdownDialog.modal('hide');
            //countdownDialog.modal('hide');
            //countdownCircle = null;
        });
    }

    this.callLoadSheets = function (responseHandler){
        urlToCall = this.baseUrl + "plugin/"+this.pluginId+"/loadSheets";
        $.ajax({
            url: urlToCall,
            type: "GET"
        }).always(function( data ){
            responseHandler(data)
        });
    }

    this.callLoadConsumables = function (responseHandler){
        urlToCall = this.baseUrl + "plugin/"+this.pluginId+"/loadConsumables";
        $.ajax({
            url: urlToCall,
            type: "GET"
        }).always(function( data ){
            responseHandler(data)
        });
    }

    this.callLoadFilamentTypes = function (responseHandler){
        urlToCall = this.baseUrl + "plugin/"+this.pluginId+"/loadFilamentTypes";
        $.ajax({
            url: urlToCall,
            type: "GET"
        }).always(function( data ){
            responseHandler(data)
        });
    }

    this.callSaveFilamentTypeStock = function (payload, responseHandler){
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/saveFilamentTypeStock",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callConsumableByBarcode = function (barcode, responseHandler){
        var b = (barcode || "").trim();
        urlToCall = this.baseUrl + "plugin/" + this.pluginId + "/consumableByBarcode/" + encodeURIComponent(b);
        $.ajax({
            url: urlToCall,
            type: "GET"
        }).always(function( data ){
            responseHandler(data)
        });
    }


    //////////////////////////////////////////////////////////////////////////////////////////////////// SAVE Spool-Item
    this.callSaveSpool = function (spoolItem, responseHandler){
        jsonPayload = ko.toJSON(spoolItem)

        $.ajax({
            //url: API_BASEURL + "plugin/"+PLUGIN_ID+"/loadPrintJobHistory",
            url: this.baseUrl + "plugin/" + this.pluginId + "/saveSpool",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: jsonPayload,
            type: "PUT"
        }).always(function( data ){
            responseHandler();
        });
    }

    this.callSaveSheet = function (sheetItem, responseHandler){
        jsonPayload = ko.toJSON(sheetItem)

        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/saveSheet",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: jsonPayload,
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    ////////////////////////////////////////////////////////////////////////////////////////////////// DELETE Spool-Item
    this.callDeleteSpool = function (databaseId, responseHandler){
        $.ajax({
            //url: API_BASEURL + "plugin/"+PLUGIN_ID+"/loadPrintJobHistory",
            url: this.baseUrl + "plugin/" + this.pluginId + "/deleteSpool/" + databaseId,
            type: "DELETE"
        }).always(function( data ){
            responseHandler();
        });
    }

    this.callDeleteSheet = function (databaseId, responseHandler){
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/deleteSheet/" + databaseId,
            type: "DELETE"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callDeleteConsumable = function (databaseId, responseHandler){
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/deleteConsumable/" + databaseId,
            type: "DELETE"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callAssignSheetToPrinter = function (printerNumber, databaseId, responseHandler, errorHandler){
        var payload = {
            printerNumber: printerNumber,
            databaseId: databaseId
        }
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/assignSheetToPrinter",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).done(function(data){
            if (responseHandler) responseHandler(data);
        }).fail(function(xhr){
            if (errorHandler) errorHandler(xhr);
        });
    }

    this.callAppendSheetToMagazine = function (printerNumber, databaseId, responseHandler, errorHandler){
        var payload = {
            printerNumber: printerNumber,
            databaseId: databaseId
        }
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/appendSheetToMagazine",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).done(function(data){
            if (responseHandler) responseHandler(data);
        }).fail(function(xhr){
            if (errorHandler) errorHandler(xhr);
        });
    }

    this.callUnassignSheet = function (databaseId, responseHandler){
        var payload = {
            databaseId: databaseId
        }
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/unassignSheet",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callAssignSheetToPrinterByNid = function (printerNumber, nid, responseHandler){
        var payload = {
            printerNumber: printerNumber,
            nid: nid
        }
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/assignSheetToPrinter",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callAppendSheetToMagazineByNid = function (printerNumber, nid, responseHandler){
        var payload = {
            printerNumber: printerNumber,
            nid: nid
        }
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/appendSheetToMagazine",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callUnassignSheetByNid = function (nid, responseHandler){
        var payload = {
            nid: nid
        }
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/unassignSheet",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    this.callSheetsState = function(printerNumber, responseHandler){
        urlToCall = this.baseUrl + "plugin/" + this.pluginId + "/sheetsState/" + printerNumber;
        $.ajax({
            url: urlToCall,
            type: "GET"
        }).always(function( data ){
            responseHandler(data)
        });
    }

    this.callSaveSheetType = function(name, responseHandler){
        var payload = {
            name: name
        }
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/saveSheetType",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    ////////////////////////////////////////////////////////////////////////////////////////////////// SELECT Spool-Item
    this.callSelectSpool = function (toolIndex, databaseId, commitCurrentSpoolValues, responseHandler){
        if (databaseId == null){
            databaseId = -1;
        }
        var payload = {
            databaseId: databaseId,
            toolIndex: toolIndex,
        }
        if (commitCurrentSpoolValues !== undefined) {
            payload.commitCurrentSpoolValues = commitCurrentSpoolValues;
        }
        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/selectSpool",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: JSON.stringify(payload),
            type: "PUT"
        }).always(function( data ){
            responseHandler( data );
        });
    }

    /////////////////////////////////////////////////////////////////////////////////////////////////// ALLOWED TO PRINT
    this.allowedToPrint = function (responseHandler){

        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/allowedToPrint",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            type: "GET"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    /////////////////////////////////////////////////////////////////////////////////////////////////// START PRINT CONFIRMED
    this.startPrintConfirmed = function (responseHandler){

        $.ajax({
            url: this.baseUrl + "plugin/" + this.pluginId + "/startPrintConfirmed",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            type: "GET"
        }).always(function( data ){
            responseHandler(data);
        });
    }

    //////////////////////////////////////////////////////////////////////////////////////////////////// DELETE Database
    this.callDeleteDatabase = function(databaseType, databaseSettings, responseHandler){
        jsonPayload = ko.toJSON(databaseSettings)
        $.ajax({
            //url: API_BASEURL + "plugin/"+PLUGIN_ID+"/loadPrintJobHistory",
            url: this.baseUrl + "plugin/"+this.pluginId+"/deleteDatabase/"+databaseType,
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: jsonPayload,
            type: "POST"
        }).always(function( data ){
            responseHandler(data)
        });
    }

    //////////////////////////////////////////////////////////////////////////////////////////////////// Copy Database
    this.callCopyDatabase = function(databaseSettings, responseHandler) {
        jsonPayload = ko.toJSON(databaseSettings)
        $.ajax({
            url: this.baseUrl + "plugin/"+this.pluginId+"/copyDatabase",
            dataType: "json",
            contentType: "application/json; charset=UTF-8",
            data: jsonPayload,
            type: "POST"
        }).always(function( data ){
            responseHandler(data)
        });
    }

    ////////////////////////////////////////////////////////////////////////////////////////////////// DOWNLOAD Database
    this.getDownloadDatabaseUrl = function(exportType){
        return _addApiKeyIfNecessary("./plugin/" + this.pluginId + "/downloadDatabase");
    }

//    // deactivate the Plugin/Check
//    this.callDeactivatePluginCheck =  function (){
//        $.ajax({
//            url: this.baseUrl + "plugin/"+ this.pluginId +"/deactivatePluginCheck",
//            type: "PUT"
//        }).done(function( data ){
//            //responseHandler(data)
//        });
//    }





}
