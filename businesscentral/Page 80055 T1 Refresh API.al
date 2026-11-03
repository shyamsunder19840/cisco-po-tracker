// API page used by the Cisco PO Tracker web app. It lists purchase orders and has one bound action, refreshT1Data,
// that rebuilds the T1ProcessData lines of that purchase order (codeunit 80055 "T1 Process Line Refresh").
//
// Publish in: 5- APIManagement-Project\PageAPI   (together with Codeunit 80055).
// Page ID 80055 is unused in that project; change it if another extension already uses it.
// Endpoint:   .../api/Proactive/ProactiveAPI/v1.0/companies(<id>)/t1Refresh
// Action:     POST .../t1Refresh(<id>)/Microsoft.NAV.refreshT1Data
page 80055 "T1 Refresh API"
{
    PageType = API;
    APIGroup = 'ProactiveAPI';
    APIPublisher = 'Proactive';
    APIVersion = 'v1.0';
    Caption = 't1Refresh';
    EntityName = 't1Refresh';
    EntitySetName = 't1Refresh';
    EntityCaption = 'T1 Refresh';
    EntitySetCaption = 'T1 Refresh';
    SourceTable = "Purchase Header";
    DelayedInsert = true;
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Permissions = tabledata "Purchase Header" = r, tabledata "Purchase Line" = r, tabledata T1ProcessData = rimd;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId) { Editable = false; }
                field(documentNo; Rec."No.") { Editable = false; }
                // number of T1ProcessData lines created by the last refreshT1Data call
                field(t1Rows; T1Rows) { Editable = false; }
            }
        }
    }

    trigger OnOpenPage()
    begin
        Rec.SetRange("Document Type", Rec."Document Type"::Order);
    end;

    [ServiceEnabled]
    procedure RefreshT1Data(var ActionContext: WebServiceActionContext)
    var
        T1Refresh: Codeunit "T1 Process Line Refresh";
    begin
        T1Rows := T1Refresh.RefreshForPurchaseOrder(Rec);
        ActionContext.SetObjectType(ObjectType::Page);
        ActionContext.SetObjectId(Page::"T1 Refresh API");
        ActionContext.AddEntityKey(Rec.FieldNo(SystemId), Rec.SystemId);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;

    var
        T1Rows: Integer;
}
