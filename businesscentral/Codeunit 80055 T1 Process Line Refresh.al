// Rebuilds the T1ProcessData lines of ONE purchase order (all its BSO lines) using the logic of Report 80000
// "T1 Process Batch" (Desktop\Report 80000 T1 Process Batch.al): same sales / invoice / job / purchase side lookups and the
// same field assignments, but only for the BSO lines linked to the purchase order instead of a whole date range.
//
// Used by the Cisco PO Tracker web app: after "Sync into Business Central" has updated the purchase lines, the app calls
// the bound action of page 80055 "T1 Refresh API", which runs this codeunit once per purchase order document.
//
// Publish in: 5- APIManagement-Project\Codeunits   (needs the same dependencies as Report 80000).
// Codeunit ID 80055 is unused in that project; change it if another extension already uses it.
//
// Differences from the report (on purpose):
//  * only the BSO lines that the purchase order points to ("Sales Blanket Order No." / "Sales Blanket Order Line No.")
//    are rebuilt: their old T1ProcessData lines are deleted, then re-created;
//  * the BSO line filters of the report are kept (Order Type CISCO, Major/Minor = MJ, "T1 Process Comments" <> Ignore,
//    "No." <> 44-022110); a BSO line that does not pass them is left untouched;
//  * no order-date range, no progress window, no notification mail;
//  * GetLastScheduleDate() is not called - the report computes it but never stores it.
codeunit 80055 "T1 Process Line Refresh"
{
    Permissions = tabledata T1ProcessData = rimd;

    // Returns the number of T1ProcessData lines created.
    procedure RefreshForPurchaseOrder(PurchHeader: Record "Purchase Header") LinesCreated: Integer
    var
        PurchLn: Record "Purchase Line";
        BSOLine: Record "Sales Line";
        Done: List of [Text];
        LineKey: Text;
    begin
        PurchLn.SetRange("Document Type", PurchHeader."Document Type");
        PurchLn.SetRange("Document No.", PurchHeader."No.");
        PurchLn.SetFilter("Sales Blanket Order No.", '<>%1', '');
        if PurchLn.FindSet() then
            repeat
                LineKey := PurchLn."Sales Blanket Order No." + '|' + Format(PurchLn."Sales Blanket Order Line No.");
                if not Done.Contains(LineKey) then begin
                    Done.Add(LineKey);
                    if BSOLine.Get(BSOLine."Document Type"::"Blanket Order", PurchLn."Sales Blanket Order No.", PurchLn."Sales Blanket Order Line No.") then
                        LinesCreated += RefreshBSOLine(BSOLine);
                end;
            until PurchLn.Next() = 0;
    end;

    local procedure RefreshBSOLine(BSOLine: Record "Sales Line"): Integer
    var
        MajorMinor: Option " ",MJ,MI;
    begin
        BSOSalesLine := BSOLine;
        if not BSOSalesHeader.Get(BSOSalesHeader."Document Type"::"Blanket Order", BSOSalesLine."Document No.") then
            exit(0);

        // the filters of the report's BSO header / line data items
        if BSOSalesHeader."Order Type" <> BSOSalesHeader."Order Type"::CISCO then
            exit(0);
        if BSOSalesLine."T1 Process Comments" = 'Ignore' then
            exit(0);
        if BSOSalesLine."Major/Minor" <> MajorMinor::MJ then
            exit(0);
        if BSOSalesLine."No." = '44-022110' then
            exit(0);

        // drop the existing T1 lines of this BSO line, they are re-created below
        T1DeleteRecord.Reset();
        T1DeleteRecord.SetRange("BSO No", BSOSalesLine."Document No.");
        T1DeleteRecord.SetRange("BSO Line No.", BSOSalesLine."Line No.");
        T1DeleteRecord.DeleteAll();

        Created := 0;
        Clear(SalesHeader);

        // BSO header level (report: BSOSalesHeader OnAfterGetRecord)
        Clear(CustomerName);
        Clear(CustomerNo);
        Clear(AMName);
        Clear(AMEmailID);
        Clear(MasterCustID);
        Clear(LastScheduledDate);
        Clear(MasterCustName);
        Clear(ZSID);

        Salespeople.Reset();
        if Salespeople.Get(BSOSalesHeader."Salesperson Code") then begin
            AMName := Salespeople.Name;
            AMEmailID := Salespeople."E-Mail";
            ZSID := Salespeople."Zoho Salesperson ID";
        end;
        Cust.Reset();
        Cust.SetRange("No.", BSOSalesHeader."Sell-to Customer No.");
        if Cust.FindFirst() then begin
            MasterCustID := Cust."Master Customer ID";
            MasterCustName := Cust.Name;
        end;

        // BSO line level (report: BSOSalesLine OnAfterGetRecord)
        SalesLine.Reset();
        SalesLine.SetCurrentKey("Document Type", "Blanket Order No.", "Blanket Order Line No.");
        SalesLine.SetRange("Document Type", SalesLine."Document Type"::Order);
        SalesLine.SetRange("Blanket Order No.", BSOSalesLine."Document No.");
        SalesLine.SetRange("Blanket Order Line No.", BSOSalesLine."Line No.");
        if SalesLine.FindFirst() then begin
            repeat
                ResetVariable();
                BSOQty := BSOSalesLine.Quantity;
                SOAmount := SalesLine."Line Amount";
                Comments := BSOSalesLine."T1 Process Comments";
                SalesHeader.Reset();
                SalesHeader.Get(SalesLine."Document Type", SalesLine."Document No.");

                SONo := SalesHeader."No.";
                SODate := SalesHeader."Order Date";
                SOOrderMonth := GetSOMonth(SODate);
                POType := Format(SalesHeader."PO Type");
                if POType = '' then
                    POType := 'DTA';

                SOLineNo := SalesLine."Line No.";
                SOQuantity := SalesLine.Quantity;
                SOPendingQty := SalesLine."Qty. to Ship";
                OtyShipped := SalesLine."Quantity Shipped";
                Techcode := GetTechnology(SalesLine."Product Group Code-Cust");
                SalesTeam := GetSalesTeam(SalesLine."Product Group Code-Cust");
                CustomerPONo := SalesHeader."Customer Order No.";
                CustomerPODate := SalesHeader."Customer PO Date";
                ShiptoCustomerName := SalesHeader."Ship-to Name";

                if SalesHeader."Order Type" = SalesHeader."Order Type"::GENERAL then
                    CiscoNONCisco := 'Non Cisco';
                if (SalesHeader."Order Type" = SalesHeader."Order Type"::"MIS-Cisco") or (SalesHeader."Order Type" = SalesHeader."Order Type"::CISCO) then
                    CiscoNONCisco := 'Cisco';
                if SalesHeader."Order Type" = SalesHeader."Order Type"::CABLE then
                    CiscoNONCisco := 'Cabling';

                if BSOSalesLine.Type = BSOSalesLine.Type::Item then begin
                    GRN.SetCurrentKey("Sales Blanket Order No.", "Sales Blanket Order Line No.");
                    GRN.SetRange("Sales Blanket Order No.", SalesLine."Blanket Order No.");
                    GRN.SetRange("Sales Blanket Order Line No.", SalesLine."Blanket Order Line No.");
                    if GRN.FindFirst() then
                        ProductRecDate := GRN."Posting Date";
                end;

                SetLineType();

                PartNo := BSOSalesLine."Part No.";
                if LType = 'Professional Services' then
                    PartNo := 'Professional Services';
                if LType = 'Attached Services' then
                    PartNo := BSOSalesLine."Service Part Code";

                SIL.Reset();
                SIL.SetCurrentKey("Blanket Order No.", "Blanket Order Line No.");
                SIL.SetRange("Blanket Order No.", SalesLine."Blanket Order No.");
                SIL.SetRange("Blanket Order Line No.", SalesLine."Blanket Order Line No.");
                if SIL.FindFirst() then begin
                    SIH.Reset();
                    if SIH.Get(SIL."Document No.") then begin
                        CustomerDeliveryDate := SIH."Customer Delivery Date";
                        PODNo := SIH."POD No.";
                        DispatchThrough := SIH."Dispatch Through";
                        DispatchDate := SIH."Dispatch Date";
                    end;
                    SINo := SIL."Document No.";
                    SIDate := SIL."Posting Date";
                end;

                JOA.Reset();
                JOA.SetRange(Type, JOA.Type::Sales);
                JOA.SetRange("Order No.", SalesLine."Document No.");
                if JOA.FindFirst() then begin
                    JOBNo := JOA."Job No.";
                    JobHeader.Reset();
                    JobHeader.SetRange("No.", JOA."Job No.");
                    if JobHeader.FindFirst() then begin
                        JobStatus := Format(JobHeader."Job Status");
                        PMName := JobHeader."Project Manager Name";
                    end;
                end;

                if JOBNo <> '' then begin
                    if SalesLine.Type = SalesLine.Type::Item then
                        JobTaskNo := '1010';

                    if SalesLine.Type = SalesLine.Type::"G/L Account" then begin
                        if StrPos(SalesLine.Description, 'Project') <> 0 then
                            JobTaskNo := '3030'
                        else
                            JobTaskNo := '3020';
                    end;
                end;

                if SalesLine."Job No." = '' then
                    ProjectNonProject := 'Non Project'
                else
                    ProjectNonProject := 'Project';

                ProactiveOrderStatus := GetSOStatus(SalesHeader."No.");
                PendingQtyforSO := BSOSalesLine.Quantity - SalesLine.Quantity;

                OrderLineStatus := 'Vendor PO Pending';

                GetPurchaseSideDetails();
            until SalesLine.Next() = 0;
        end else begin
            ResetVariable();
            Comments := BSOSalesLine."T1 Process Comments";
            Techcode := GetTechnology(BSOSalesLine."Product Group Code-Cust");
            SalesTeam := GetSalesTeam(BSOSalesLine."Product Group Code-Cust");
            POType := Format(BSOSalesHeader."PO Type");
            if POType = '' then
                POType := 'DTA';
            if BSOSalesHeader."Order Type" = BSOSalesHeader."Order Type"::GENERAL then
                CiscoNONCisco := 'Non Cisco';
            if (BSOSalesHeader."Order Type" = BSOSalesHeader."Order Type"::"MIS-Cisco") or (BSOSalesHeader."Order Type" = BSOSalesHeader."Order Type"::CISCO) then
                CiscoNONCisco := 'Cisco';
            if BSOSalesHeader."Order Type" = BSOSalesHeader."Order Type"::CABLE then
                CiscoNONCisco := 'Cabling';

            if (BSOSalesHeader."BSO Type" = BSOSalesHeader."BSO Type"::"Not Project") or (BSOSalesHeader."BSO Type" = BSOSalesHeader."BSO Type"::" ") then
                ProjectNonProject := 'Non Project';
            if BSOSalesHeader."BSO Type" = BSOSalesHeader."BSO Type"::Project then
                ProjectNonProject := 'Project';

            PendingQtyforSO := BSOSalesLine.Quantity;
            if BSOSalesLine.Type = BSOSalesLine.Type::Item then begin
                GRN.SetCurrentKey("Sales Blanket Order No.", "Sales Blanket Order Line No.");
                GRN.SetRange("Sales Blanket Order No.", BSOSalesLine."Document No.");
                GRN.SetRange("Sales Blanket Order Line No.", BSOSalesLine."Line No.");
                if GRN.FindFirst() then
                    ProductRecDate := GRN."Posting Date";
            end;

            SetLineType();

            PartNo := BSOSalesLine."Part No.";
            if LType = 'Professional Services' then
                PartNo := 'Professional Services';
            if LType = 'Attached Services' then
                PartNo := BSOSalesLine."Service Part Code";

            OrderLineStatus := 'SO & PO Pending';
            GetPurchaseSideDetails();
        end;

        exit(Created);
    end;

    // The Line Type block that the report repeats in both branches of OnAfterGetRecord.
    local procedure SetLineType()
    begin
        if BSOSalesLine."Item Catalog Category" = 'M' then
            LType := 'Products';
        if BSOSalesLine."Item Catalog Category" = 'm' then
            LType := 'Products';
        if BSOSalesLine."Item Catalog Category" = 'B' then
            LType := 'Products';
        if BSOSalesLine."Item Catalog Category" = 'L' then
            LType := 'Licenses';
        if BSOSalesLine."Item Catalog Category" = 'LS' then
            LType := 'Embedded software Subscriptions';
        if BSOSalesLine."Item Catalog Category" = 'E' then
            LType := 'Embedded software Subscriptions';
        if BSOSalesLine."Item Catalog Category" = 'X' then
            LType := 'Attached SAAS';
        if BSOSalesLine."Item Catalog Category" = 'S' then
            LType := 'Attached Services';
        if BSOSalesLine."Item Catalog Category" = 's' then
            LType := 'Attached Services';
        if BSOSalesLine."No." = '44-021110' then
            LType := 'Manpower Services';
        if BSOSalesLine."No." = '44-021150' then
            LType := 'Rental Sales';
        if BSOSalesLine."No." = '44-022110' then
            LType := 'Professional Services';
        if BSOSalesLine."No." = '44-021130' then
            LType := 'Professional Services';
        if BSOSalesLine."No." = '51-740800' then
            LType := 'Freight Expenses';
        if BSOSalesLine."No." = '44-024100' then
            LType := 'Freight Expenses';
        if BSOSalesLine."No." = '44-001550' then
            LType := 'Products';
    end;

    local procedure GetPurchaseSideDetails()
    begin
        PL.Reset();
        PL.SetCurrentKey("Sales Blanket Order No.", "Sales Blanket Order Line No.");
        PL.SetRange("Sales Blanket Order No.", BSOSalesLine."Document No.");
        PL.SetRange("Sales Blanket Order Line No.", BSOSalesLine."Line No.");
        if PL.FindFirst() then begin
            PH.Reset();
            PH.SetRange("No.", PL."Document No.");
            if PH.FindFirst() then begin
                PONo := PH."No.";
                PODate := PH."Posting Date";
                CISCOOrderNo := PH."CISCO Order No.";
                VendorName := PH."Buy-from Vendor Name";
            end;

            LinktoMajor := PL."Linked to Major";
            POLinktoMajorLineNo := PL."SO Line No.";
            ServiceDeleydays := PL."Service Delay Days";
            ShipsetNo := PL.Shipset;
            if PL."CISCO Delivery Status" <> '' then
                CiscoS := PL."CISCO Delivery Status"
            else
                CiscoS := Format(PL."CISCO Staus");
            SchDate := PL.Scheduled_Date;

            if SchDate = 0D then begin
                HPos := StrPos(PL."Document No.", '-');
                PurchLine.Reset();
                PurchLine.SetCurrentKey("Linked to Major", "SO Line No.");
                if HPos <> 0 then
                    PurchLine.SetFilter("Document No.", '%1', CopyStr(PL."Document No.", 1, HPos - 1) + '*')
                else
                    PurchLine.SetFilter("Document No.", '%1', PL."Document No.");
                PurchLine.SetFilter("SO Line No.", '%1', PL."Linked to Major");
                PurchLine.SetFilter(Scheduled_Date, '<>%1', 0D);
                if PurchLine.FindFirst() then begin
                    if PL.Type = PL.Type::"G/L Account" then begin
                        if ServiceDeleydays <> '' then begin
                            if StrPos(ServiceDeleydays, 'D') <> 0 then begin
                                if (StrPos(ServiceDeleydays, 'D') >= 3) then
                                    Evaluate(NoofDays, CopyStr(ServiceDeleydays, 1, StrPos(ServiceDeleydays, 'D') - 1))
                            end else
                                Evaluate(NoofDays, ServiceDeleydays);
                        end else begin
                            if (CiscoNONCisco = 'Cisco') and (LType = 'Attached Services') then
                                NoofDays := 60;
                        end;
                        SchDate := GetExtendeddaysDate(PurchLine.Scheduled_Date, Techcode, NoofDays, true);
                    end;
                end;
            end;
            if CiscoNONCisco in ['Non Cisco', 'Cabling'] then
                SchDate := SalesLine."Delivery Timeline";

            POLineNo := PL."Line No.";
            POBuyerLineNo := PL."Buyers Line No.";
            PreviousScheduleShipDate := PL."Previous Scheduled Date";
            Shipmentdate := PL.Shipping_Date;

            if PL."Previous Scheduled Date" = '' then
                ShipDateStatus := 'No Change'
            else begin
                Evaluate(DD, CopyStr(PreviousScheduleShipDate, 1, 2));
                Evaluate(MM, CopyStr(PreviousScheduleShipDate, 4, 2));
                Evaluate(YYYY, '20' + CopyStr(PreviousScheduleShipDate, 7, 2));
                PrevSchDate := DMY2Date(DD, MM, YYYY);
                if SchDate = PrevSchDate then
                    ShipDateStatus := 'No Change';
                if SchDate > PrevSchDate then
                    ShipDateStatus := 'Date Shifted';
                if SchDate < PrevSchDate then
                    ShipDateStatus := 'Date Improved';
            end;

            PurchLocationCode := PL."Location Code";

            PIL.Reset();
            PIL.SetCurrentKey("Sales Blanket Order No.", "Sales Blanket Order Line No.");
            PIL.SetRange("Sales Blanket Order No.", BSOSalesLine."Document No.");
            PIL.SetRange("Sales Blanket Order Line No.", BSOSalesLine."Line No.");
            if PIL.FindFirst() then begin
                PILInvoiceNo := PIL."Document No.";
                PILInvoiceDate := PIL."Posting Date";
            end;

            InsertT1Line();
        end;
    end;

    // The report's "ENo += 1; T1.Init(); ... T1.Modify();" block.
    local procedure InsertT1Line()
    begin
        T1Last.Reset();
        if T1Last.FindLast() then
            ENo := T1Last."Entry No."
        else
            ENo := 0;

        ENo += 1;
        T1.Init();
        T1."Entry No." := ENo;
        T1.Insert(true);
        T1."Account Manager Name" := AMName;
        T1."AM Email ID" := AMEmailID;
        T1."PM Name" := PMName;
        T1."BSO No" := BSOSalesLine."Document No.";
        T1."BSO Line No." := BSOSalesLine."Line No.";
        T1."BSO Quantity" := BSOSalesLine.Quantity;
        T1."Order Date" := BSOSalesHeader."Order Date";
        T1."BSO Quantity" := BSOQty;
        T1."Pending to Create SO Qty" := PendingQtyforSO;
        T1."Cisco/Non Cisco" := CiscoNONCisco;
        T1."Project/Non Project" := ProjectNonProject;
        T1."SO No" := SONo;
        T1."SO Date" := SODate;
        T1."PO Type" := POType;
        T1."SO Line No" := SOLineNo;
        T1."SO Qty" := SOQuantity;
        T1."Quantity Shipped" := OtyShipped;
        T1."SO Pending Quantity" := SOPendingQty;
        T1."Customer PO No" := CustomerPONo;
        T1."Customer PO Date" := CustomerPODate;
        T1."Master Customer ID" := MasterCustID;
        T1."Master Customer Name" := MasterCustName;
        CustomerRec.Reset();
        if CustomerRec.Get(MasterCustID) then
            T1."Zoho Account ID" := CustomerRec."Zoho Account ID";
        T1."Zoho Salesperson ID" := ZSID;
        T1."Customer ID" := BSOSalesHeader."Sell-to Customer No.";
        T1."Customer Name" := BSOSalesHeader."Sell-to Customer Name";
        T1."Ship to Customer Name" := ShiptoCustomerName;
        T1."Ship To City" := SalesHeader."Ship-to City";
        T1."Major Minor" := BSOSalesLine."Major/Minor";
        T1."Link to Major" := LinktoMajor;
        T1."PO LtoM Line No." := POLinktoMajorLineNo;
        T1."Part Code" := PartNo;
        T1."Product Description" := BSOSalesLine.Description;
        T1."Previous Schedule Ship Date" := PreviousScheduleShipDate;
        T1."Scheduled Date" := PL.Scheduled_Date;
        T1."Service Delay Days" := ServiceDeleydays;
        T1."Ship Date Status" := ShipDateStatus;
        T1."Est Del Date Comp Shipment" := PL."Estimate Delivery Date";
        T1."Est Del Date Parti Shipment" := PL."Estimate Delivery Date";
        T1."Sales Invoice No" := SINo;
        T1."Sales Invoice Date" := SIDate;
        T1."POD No." := PODNo;
        T1."Dispatch Through" := DispatchThrough;
        T1."Dispatch Date" := DispatchDate;
        T1."Customer Delivery Date" := CustomerDeliveryDate;
        T1."Line Status" := PL."Cisco Delivery Status";
        T1."Line Type" := LType;
        T1."SO Amount" := SOAmount;
        T1."Job No" := JOBNo;
        T1."Job Task No" := JobTaskNo;
        T1."Proactive PO No" := PONo;
        T1."Proactive PO Line No." := POLineNo;
        T1."Proactive PO Date" := PODate;
        T1."Proactive Vendor Name" := VendorName;
        T1."CISCO Order Status" := CiscoS;
        T1."CISCO Order No" := CISCOOrderNo;
        if StrLen(ShipsetNo) = 1 then
            T1."CISCO Shipset No" := ShipsetNo;
        T1."Port for Receive Imp Shipment" := PurchLocationCode;
        T1."Product Receive Date" := ProductRecDate;
        T1."Purchase Invoice No" := PILInvoiceNo;
        T1."Purchase Invoice Date" := PILInvoiceDate;
        T1."Proactive Order Status" := ProactiveOrderStatus;
        T1.Technology := Techcode;
        T1."Sales Teams" := CopyStr(SalesTeam, 1, 10);
        T1.Comments := Comments;
        T1."Job Status" := JobStatus;
        T1."Delivery Contact" := BSOSalesHeader."Delivery Contact";
        T1."Delivery Contact Email ID" := BSOSalesHeader."Delivery Contact Email ID";
        T1."Delivery Contact Phone No." := BSOSalesHeader."Delivery Contact Phone No.";
        T1."Zoho Sync" := true;
        T1.Modify();
        Created += 1;
    end;

    local procedure GetExtendeddaysDate(CurrDate: Date; Technology: Text; AddDays: Integer; SSExclude: Boolean): Date
    begin
        CurrDate := CurrDate + AddDays;
        if not SSExclude then begin
            DayforWeek.Reset();
            if DayforWeek.Get(DayforWeek."Period Type"::Date, CurrDate) then begin
                if (DayforWeek."Period Name" = 'Sunday') then
                    CurrDate := CurrDate + 1;
                if (DayforWeek."Period Name" = 'Saturday') then
                    CurrDate := CurrDate + 2;
            end;
        end;
        exit(CurrDate);
    end;

    local procedure GetSalesTeam(TCode: Code[10]) STeams: Code[20]
    var
        ProductGroup: Record "Product Group-Cust";
        ProductGroup1: Record "Product Group-Cust";
    begin
        ProductGroup1.Reset();
        ProductGroup1.SetRange(Code, TCode);
        if ProductGroup1.FindFirst() then begin
            ProductGroup.Reset();
            ProductGroup.SetRange("Technology Code", ProductGroup1."Technology Code");
            if ProductGroup.FindFirst() then
                STeams := ProductGroup."Technology Teams"
        end;
        exit(STeams);
    end;

    local procedure GetTechnology(TCode: Code[10]) STech: Code[20]
    var
        ProductGroup: Record "Product Group-Cust";
    begin
        ProductGroup.Reset();
        ProductGroup.SetRange(Code, TCode);
        if ProductGroup.FindFirst() then
            STech := ProductGroup."Technology Code";

        if TCode = 'MERAKI' then
            exit(TCode);
        exit(STech);
    end;

    local procedure GetSOStatus(SONumber: Code[20]): Text
    var
        SL: Record "Sales Line";
        St: Text;
    begin
        SL.Reset();
        SL.SetRange(SL."Document No.", SONumber);
        SL.SetFilter("Outstanding Quantity", '<>%1', 0);
        if SL.FindFirst() then
            St := 'Open'
        else
            St := 'Closed';

        if St = 'Open' then begin
            SL.Reset();
            SL.SetRange(SL."Document No.", SONumber);
            SL.SetFilter("Outstanding Quantity", '<>%1', 0);
            SL.SetFilter("No.", '<>%1', '44-022110');
            if not SL.FindFirst() then
                St := 'Shipment Delivered PS Billing Pending';
        end;
        exit(St);
    end;

    local procedure GetSOMonth(SOOrderDate: Date): Text
    begin
        if Date2DMY(SOOrderDate, 2) = 1 then
            exit('Jan');
        if Date2DMY(SOOrderDate, 2) = 2 then
            exit('Feb');
        if Date2DMY(SOOrderDate, 2) = 3 then
            exit('March');
        if Date2DMY(SOOrderDate, 2) = 4 then
            exit('April');
        if Date2DMY(SOOrderDate, 2) = 5 then
            exit('May');
        if Date2DMY(SOOrderDate, 2) = 6 then
            exit('June');
        if Date2DMY(SOOrderDate, 2) = 7 then
            exit('July');
        if Date2DMY(SOOrderDate, 2) = 8 then
            exit('August');
        if Date2DMY(SOOrderDate, 2) = 9 then
            exit('Sept');
        if Date2DMY(SOOrderDate, 2) = 10 then
            exit('Oct');
        if Date2DMY(SOOrderDate, 2) = 11 then
            exit('Nov');
        if Date2DMY(SOOrderDate, 2) = 12 then
            exit('Dec');
    end;

    local procedure ResetVariable()
    begin
        Clear(ShipsetNo);
        Clear(POLineNo);
        Clear(POBuyerLineNo);
        Clear(PreviousScheduleShipDate);
        Clear(Shipmentdate);
        Clear(SchDate);
        Clear(PONo);
        Clear(PODate);
        Clear(CISCOOrderNo);
        Clear(VendorName);
        Clear(PILInvoiceNo);
        Clear(PILInvoiceDate);
        Clear(LType);
        Clear(ShipDateStatus);
        Clear(ProductRecDate);
        Clear(SINo);
        Clear(SIDate);
        Clear(PurchLocationCode);
        Clear(CiscoS);
        Clear(PrevSchDate);
        Clear(DD);
        Clear(MM);
        Clear(YYYY);
        Clear(OrderLineStatus);
        Clear(ProactiveOrderStatus);
        Clear(CustomerDeliveryDate);
        Clear(PODNo);
        Clear(DispatchThrough);
        Clear(JOBNo);
        Clear(CiscoNONCisco);
        Clear(ProjectNonProject);
        Clear(SOQuantity);
        Clear(SONo);
        Clear(POType);
        Clear(SOLineNo);
        Clear(SODate);
        Clear(SOPendingQty);
        Clear(OtyShipped);
        Clear(PendingQtyforSO);
        Clear(Techcode);
        Clear(CustomerPONo);
        Clear(ShiptoCustomerName);
        Clear(CustomerPODate);
        Clear(SalesTeam);
        Clear(PartNo);
        Clear(DispatchDate);
        Clear(ServiceDeleydays);
        Clear(POLinktoMajorLineNo);
        Clear(LinktoMajor);
        Clear(NoofDays);
        Clear(Comments);
        Clear(HPos);
        Clear(SOAmount);
        Clear(JobStatus);
        Clear(SOOrderMonth);
        Clear(JobTaskNo);
        Clear(PMEmailID);
        Clear(PMName);
    end;

    var
        BSOSalesHeader: Record "Sales Header";
        BSOSalesLine: Record "Sales Line";
        SalesHeader: Record "Sales Header";
        SalesLine: Record "Sales Line";
        T1: Record T1ProcessData;
        T1DeleteRecord: Record T1ProcessData;
        T1Last: Record T1ProcessData;
        PL: Record "Purchase Line";
        PurchLine: Record "Purchase Line";
        PH: Record "Purchase Header";
        PIL: Record "Purch. Inv. Line";
        GRN: Record "Purch. Rcpt. Line";
        SIL: Record "Sales Invoice Line";
        SIH: Record "Sales Invoice Header";
        JOA: Record "Job-Order Application Entry";
        JobHeader: Record Job;
        Cust: Record Customer;
        CustomerRec: Record Customer;
        Salespeople: Record "Salesperson/Purchaser";
        DayforWeek: Record Date;
        Created: Integer;
        ENo: Integer;
        ZSID: Text[50];
        CustomerName: Text;
        CustomerNo: Code[20];
        ShipsetNo: Text;
        PreviousScheduleShipDate: Text;
        Shipmentdate: Date;
        PILInvoiceDate: Date;
        PILInvoiceNo: Code[20];
        PONo: Code[20];
        PODate: Date;
        CISCOOrderNo: Code[20];
        VendorName: Text;
        LType: Text[50];
        AMName: Text[100];
        AMEmailID: Text[50];
        ShipDateStatus: Text[20];
        ProductRecDate: Date;
        SINo: Code[20];
        SIDate: Date;
        SchDate: Date;
        MasterCustID: Code[20];
        MasterCustName: Text[100];
        PurchLocationCode: Code[10];
        CiscoS: Text[30];
        PrevSchDate: Date;
        DD: Integer;
        MM: Integer;
        YYYY: Integer;
        LastScheduledDate: Date;
        OrderLineStatus: Text[50];
        ProactiveOrderStatus: Text[50];
        CustomerDeliveryDate: Date;
        PODNo: Code[50];
        DispatchThrough: Text[100];
        JOBNo: Code[20];
        CiscoNONCisco: Text[10];
        ProjectNonProject: Text[15];
        SONo: Code[20];
        SOLineNo: Integer;
        SODate: Date;
        POType: Code[10];
        SOQuantity: Decimal;
        PendingQtyforSO: Decimal;
        SOPendingQty: Decimal;
        OtyShipped: Decimal;
        BSOQty: Decimal;
        POLineNo: Integer;
        Techcode: Code[20];
        CustomerPONo: Code[50];
        CustomerPODate: Date;
        ShiptoCustomerName: Text;
        POBuyerLineNo: Text;
        SalesTeam: Text;
        PartNo: Code[50];
        DispatchDate: Date;
        ServiceDeleydays: Text;
        LinktoMajor: Code[10];
        POLinktoMajorLineNo: Code[10];
        NoofDays: Integer;
        Comments: Text;
        HPos: Integer;
        SOAmount: Decimal;
        JobStatus: Text[20];
        SOOrderMonth: Text[10];
        JobTaskNo: Code[10];
        PMName: Text[30];
        PMEmailID: Text[50];
}
