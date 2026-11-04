// OPTIONAL speed-up for the Cisco PO Tracker. T1ProcessData has only the primary key "Entry No.", so every search by
// PO number or BSO number reads the whole table (about 1.4 million lines): that is the slowest part of
// "Sync into Business Central", of the T1 refresh and of the T1 Process Report filters.
// These two keys let Business Central find those lines directly.
//
// Publish in: 5- APIManagement-Project\Table Extension   (next to Tab-Ext80000.T1ProcessDataExt.al).
// Table extension ID 80055 is unused in that project; change it if another extension already uses it.
// Publishing builds the two indexes once, which can take a few minutes on a table this size.
tableextension 80055 T1ProcessDataKeys extends T1ProcessData
{
    keys
    {
        key(ProactivePO; "Proactive PO No") { }
        key(BSOLine; "BSO No", "BSO Line No.") { }
    }
}
