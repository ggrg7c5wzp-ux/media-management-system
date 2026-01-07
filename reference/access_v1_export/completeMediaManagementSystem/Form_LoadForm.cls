VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Form_LoadForm"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Compare Database
Option Explicit

Private Sub cmdAddTag_Click()
    On Error GoTo EH

    ' If we're on a new/dirty record, save it first so MasterKey exists in the table
    If Me.NewRecord Or Me.Dirty Then
        DoCmd.RunCommand acCmdSaveRecord
    End If

    If Nz(Me.MasterKey, "") = "" Then
        MsgBox "No MasterKey present. Cannot tag this record.", vbExclamation
        Exit Sub
    End If

    If IsNull(Me.cboAddTag) Then
        MsgBox "Pick a tag first.", vbInformation
        Exit Sub
    End If

    CurrentDb.Execute _
        "INSERT INTO tblVinylTag (MasterKey, TagID, DateTagged, TaggedBy) " & _
        "VALUES (" & _
        "'" & Replace(Me.MasterKey, "'", "''") & "', " & _
        CLng(Me.cboAddTag) & ", Now(), '" & Replace(Environ$("Username"), "'", "''") & "');", _
        dbFailOnError

    Me.sfrmVinylTags.Requery
    Me.cboAddTag = Null
    Me.cboAddTag.Requery
    Exit Sub

EH:
    If Err.Number = 3022 Then
        MsgBox "That tag is already assigned to this record.", vbInformation
    Else
        MsgBox "Error adding tag: " & Err.Description, vbExclamation
    End If
    
End Sub


Private Sub cmdDeleteRecord_Click()
    On Error GoTo ErrHandler

    Dim mk As String
    Dim art As String
    Dim alb As String
    Dim yr As Variant
    Dim binVal As Variant
    Dim BinCode As String

    Dim resp As VbMsgBoxResult
    Dim verify As String

    Dim db As DAO.Database
    Dim rsLog As DAO.Recordset

    ' ===== 1) Ensure we are on an existing record =====
    If Me.NewRecord Then
        MsgBox "There is no existing record to delete.", vbInformation, "Delete Record"
        Exit Sub
    End If

    ' ===== 2) Capture values BEFORE delete =====
    mk = Nz(Me!MasterKey, "")
    art = Nz(Me!Artist, "")
    alb = Nz(Me!AlbumTitle, "")
    yr = IIf(IsNull(Me!Year), Null, Me!Year)
    binVal = Nz(Me!Bin, 0)
    BinCode = Nz(Me!BinCode, "")

    ' ===== 3) First confirmation =====
    resp = MsgBox( _
        "WARNING: You are about to PERMANENTLY delete this record:" & vbCrLf & vbCrLf & _
        "  MasterKey: " & mk & vbCrLf & _
        "  Artist:    " & art & vbCrLf & _
        "  Album:     " & alb & vbCrLf & vbCrLf & _
        "This CANNOT be undone." & vbCrLf & _
        "Are you ABSOLUTELY sure?", _
        vbExclamation + vbYesNo + vbDefaultButton2, _
        "Confirm Delete")

    If resp <> vbYes Then Exit Sub

    ' ===== 4) Second extra-scary confirmation =====
    verify = InputBox( _
        "To confirm deletion, type DELETE and press OK." & vbCrLf & _
        "Anything else will cancel.", _
        "Final Delete Confirmation")

    If StrComp(verify, "DELETE", vbTextCompare) <> 0 Then
        MsgBox "Deletion cancelled.", vbInformation, "Delete Record"
        Exit Sub
    End If

    ' ===== 5) Log deletion in ChangeLog =====
    Set db = CurrentDb
    On Error Resume Next
    Set rsLog = db.OpenRecordset("ChangeLog", dbOpenDynaset)
    If Err.Number = 0 Then
        rsLog.AddNew
            rsLog!ChangeDate = Now()
            rsLog!ChangeType = "DELETE"
            rsLog!MasterKey = mk
            rsLog!Artist = art
            rsLog!AlbumTitle = alb
            If Not IsNull(yr) Then rsLog!Year = yr
            rsLog!Bin = binVal
            rsLog!BinCode = BinCode
            rsLog!UserName = Environ$("Username")
        rsLog.Update
        rsLog.Close
    End If
    Set rsLog = Nothing
    On Error GoTo ErrHandler

    ' ===== 6) Delete the record =====
    DoCmd.RunCommand acCmdDeleteRecord

    ' ===== 7) RUN FULL GLOBAL REBIN + LOGGING =====
   ' DoCmd.Hourglass True
   ' GlobalRebinAndLog "DELETE:" & mk
    ' DoCmd.Hourglass False

    MsgBox "Record deleted.", vbInformation, "Delete Record"

ExitHere:
    DoCmd.Hourglass False
    Exit Sub

ErrHandler:
    DoCmd.Hourglass False
    MsgBox "Delete Error " & Err.Number & ": " & Err.Description, vbExclamation
    Resume ExitHere
End Sub



Private Sub cmdSaveRebin_Click()
    On Error GoTo ErrHandler

    If Me.Dirty Then
        DoCmd.RunCommand acCmdSaveRecord
    End If

    MsgBox "Record saved.", vbInformation, "Save Entry"
    DoCmd.GoToRecord , , acNewRec
    Exit Sub

ErrHandler:
    MsgBox "Error " & Err.Number & ": " & Err.Description, vbExclamation, "Save Error"
End Sub







Private Sub Form_BeforeUpdate(Cancel As Integer)

    ' Only enforce Media Type when inserting a *new* row.
    ' Existing records are allowed to save even if SortKey3 is weird;
    ' we already normalized old data via an UPDATE query.
    If Me.NewRecord Then
        If IsNull(Me.SortKey3) Or Me.SortKey3 = 0 Then
            MsgBox "Please select a Media Type (Standard LP, 7"" Vinyl, Cassette, etc.).", _
                   vbExclamation, "Media Type Required"
            Cancel = True
        End If
    End If

End Sub


Private Sub cmdForceRebin_Click()
    GenerateTaskList
End Sub





Private Sub Combo70_AfterUpdate()
    ' Bound to SortKey2 already, so no need to manually set it.
    ' We also no longer use a Genre field/control in code.
    ' This event can even be left empty, but we'll keep the stub
    ' in case you want UI tweaks later.
End Sub




' =========================================================
' MasterKey assignment
' =========================================================

Private Sub Form_BeforeInsert(Cancel As Integer)
    ' Assign MasterKey ONCE when the user starts a brand-new record
    ' Bins are handled by RecalcBucketsAndBins
    If IsNull(Me.MasterKey) Or Me.MasterKey = "" Then
        Me.MasterKey = GetNextMasterKey()
    End If
End Sub

Private Sub Form_Current()
    ' IMPORTANT:
    ' Do NOT generate or change MasterKey here.
    ' If you had any other UI logic here before, you can re-add it
    ' as long as it does not touch Me.MasterKey.
End Sub

' =========================================================
' Close button
' =========================================================

Private Sub cmdClose_Click()
    On Error Resume Next

    ' If form is dirty (unsaved changes), undo them BEFORE closing
    If Me.Dirty Then
        Me.Undo     ' Cancel pending edits
    End If

    ' If we are on a brand-new blank record, undo it too
    If Me.NewRecord Then
        Me.Undo
    End If
    
    DoCmd.Close acForm, Me.Name
End Sub






