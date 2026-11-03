// API page used by the Cisco PO Tracker web app to sync Cisco order status into Purchase Lines.
// Copy this file into the AL project (3- Development-Project\Pages), publish the extension, then the app can call:
//   .../api/Proactive/ProactiveAPI/v1.0/companies(<id>)/purchaseLineSync
// Page ID 60544 is unused in 3- Development-Project; change it if another extension already uses it.
page 60544 "Purchase Line Sync API"
{
    PageType = API;
    APIGroup = 'ProactiveAPI';
    APIPublisher = 'Proactive';
    APIVersion = 'v1.0';
    Caption = 'purchaseLineSync';
    EntityName = 'purchaseLineSync';
    EntitySetName = 'purchaseLineSync';
    EntityCaption = 'Purchase Line Sync';
    EntitySetCaption = 'Purchase Line Sync';
    SourceTable = "Purchase Line";
    DelayedInsert = true;
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    DeleteAllowed = false;
    ModifyAllowed = true;
    Permissions = tabledata "Purchase Line" = rm;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId) { Editable = false; }
                // Lookup keys (read-only): the app finds lines by Document No. (<PO>-M / <PO>-S) + Buyers Line No.
                field(documentNo; Rec."Document No.") { Editable = false; }
                field(lineNo; Rec."Line No.") { Editable = false; }
                field(buyersLineNo; Rec."Buyers Line No.") { Editable = false; }
                // Fields written by the sync
                field(ciscoSOLineNo; Rec."CISCO SO Line No.") { }
                field(shipset; Rec.Shipset) { }
                field(ciscoDeliveryStatus; Rec."CISCO Delivery Status") { }
                field(scheduledDate; Rec.Scheduled_Date) { }
                field(previousScheduledDate; Rec."Previous Scheduled Date") { }
                field(estimateDeliveryDate; Rec."Estimate Delivery Date") { }
            }
        }
    }

    trigger OnOpenPage()
    begin
        Rec.SetRange("Document Type", Rec."Document Type"::Order);
    end;

    // Same behaviour as Report 60151 (Export-ImportPurchaseLine): fields are assigned directly and the
    // line is modified WITHOUT running Purchase Line table triggers, so released orders can be updated.
    trigger OnModifyRecord(): Boolean
    var
        PurchLine: Record "Purchase Line";
    begin
        PurchLine.Get(Rec."Document Type", Rec."Document No.", Rec."Line No.");
        PurchLine."CISCO SO Line No." := Rec."CISCO SO Line No.";
        PurchLine.Shipset := Rec.Shipset;
        PurchLine."CISCO Delivery Status" := Rec."CISCO Delivery Status";
        PurchLine.Scheduled_Date := Rec.Scheduled_Date;
        PurchLine."Previous Scheduled Date" := Rec."Previous Scheduled Date";
        PurchLine."Estimate Delivery Date" := Rec."Estimate Delivery Date";
        PurchLine.Modify(false);
        exit(false);
    end;
}
