// Read-only API page used by the Cisco PO Tracker web app ("T1 Process Report" button) to export the output of
// Report 80000 "T1ProcessBatch" to Excel. Page 80024 (T1JobProcessDataAPI) exposes only some of the T1ProcessData
// fields; this page exposes every field that the report outputs.
//
// Publish in: 5- APIManagement-Project\PageAPI   (same project as Page 80024 and Tab-Ext80000 T1ProcessDataExt).
// Page ID 80054 is unused in that project; change it if another extension already uses it.
// Endpoint:   .../api/Proactive/ProactiveAPI/v1.0/companies(<id>)/t1ProcessReport
page 80054 T1ProcessReportAPI
{
    PageType = API;
    APIGroup = 'ProactiveAPI';
    APIPublisher = 'Proactive';
    APIVersion = 'v1.0';
    Caption = 't1ProcessReport';
    EntityName = 't1ProcessReport';
    EntitySetName = 't1ProcessReport';
    EntityCaption = 'T1 Process Report';
    EntitySetCaption = 'T1 Process Report';
    SourceTable = T1ProcessData;
    ODataKeyFields = SystemId;
    DelayedInsert = true;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Permissions = tabledata T1ProcessData = r;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId) { }
                field(entryNo; Rec."Entry No.") { }
                field(accountManagerName; Rec."Account Manager Name") { }
                field(bsoNo; Rec."BSO No") { }
                field(bsoLineNo; Rec."BSO Line No.") { }
                field(bsoOrderDate; Rec."Order Date") { }
                field(bsoQuantity; Rec."BSO Quantity") { }
                field(pendingToCreateSOQty; Rec."Pending to Create SO Qty") { }
                field(ciscoNonCisco; Rec."Cisco/Non Cisco") { }
                field(projectNonProject; Rec."Project/Non Project") { }
                field(soNo; Rec."SO No") { }
                field(soDate; Rec."SO Date") { }
                field(poType; Rec."PO Type") { }
                field(soLineNo; Rec."SO Line No") { }
                field(soQty; Rec."SO Qty") { }
                field(quantityShipped; Rec."Quantity Shipped") { }
                field(soPendingQuantity; Rec."SO Pending Quantity") { }
                field(customerPONo; Rec."Customer PO No") { }
                field(customerPODate; Rec."Customer PO Date") { }
                field(masterCustomerID; Rec."Master Customer ID") { }
                field(masterCustomerName; Rec."Master Customer Name") { }
                field(customerID; Rec."Customer ID") { }
                field(customerName; Rec."Customer Name") { }
                field(shipToCustomerName; Rec."Ship to Customer Name") { }
                field(shipToCity; Rec."Ship To City") { }
                field(majorMinor; Rec."Major Minor") { }
                field(linkToMajor; Rec."Link to Major") { }
                field(poLtoMLineNo; Rec."PO LtoM Line No.") { }
                field(partCode; Rec."Part Code") { }
                field(productDescription; Rec."Product Description") { }
                field(previousScheduleShipDate; Rec."Previous Schedule Ship Date") { }
                field(scheduledDate; Rec."Scheduled Date") { }
                field(serviceDelayDays; Rec."Service Delay Days") { }
                field(shipDateStatus; Rec."Ship Date Status") { }
                field(estDelDateCompShipment; Rec."Est Del Date Comp Shipment") { }
                field(estDelDatePartiShipment; Rec."Est Del Date Parti Shipment") { }
                field(salesInvoiceNo; Rec."Sales Invoice No") { }
                field(salesInvoiceDate; Rec."Sales Invoice Date") { }
                field(podNo; Rec."POD No.") { }
                field(dispatchThrough; Rec."Dispatch Through") { }
                field(dispatchDate; Rec."Dispatch Date") { }
                field(customerDeliveryDate; Rec."Customer Delivery Date") { }
                field(lineStatus; Rec."Line Status") { }
                field(lineType; Rec."Line Type") { }
                field(soAmount; Rec."SO Amount") { }
                field(jobNo; Rec."Job No") { }
                field(jobTaskNo; Rec."Job Task No") { }
                field(proactivePONo; Rec."Proactive PO No") { }
                field(proactivePOLineNo; Rec."Proactive PO Line No.") { }
                field(proactivePODate; Rec."Proactive PO Date") { }
                field(proactiveVendorName; Rec."Proactive Vendor Name") { }
                field(ciscoOrderStatus; Rec."CISCO Order Status") { }
                field(ciscoOrderNo; Rec."CISCO Order No") { }
                field(ciscoShipsetNo; Rec."CISCO Shipset No") { }
                field(portForReceiveImpShipment; Rec."Port for Receive Imp Shipment") { }
                field(productReceiveDate; Rec."Product Receive Date") { }
                field(purchaseInvoiceNo; Rec."Purchase Invoice No") { }
                field(purchaseInvoiceDate; Rec."Purchase Invoice Date") { }
                field(proactiveOrderStatus; Rec."Proactive Order Status") { }
                field(technology; Rec.Technology) { }
                field(salesTeams; Rec."Sales Teams") { }
                field(comments; Rec.Comments) { }
                field(jobStatus; Rec."Job Status") { }
            }
        }
    }
}
