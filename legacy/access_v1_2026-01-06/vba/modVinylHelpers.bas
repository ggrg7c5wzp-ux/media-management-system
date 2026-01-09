Attribute VB_Name = "modVinylHelpers"
Option Compare Database
Option Explicit

' ==========================
'  Core Rebin Logic (Helper)
' ==========================

Public Sub RecalcBucketsAndBins(Optional ByVal TriggerSource As String = "MANUAL")
    On Error GoTo ErrHandler

    Const BIN_CAPACITY As Long = 55   ' bin size

    Dim db As DAO.Database
    Dim rs As DAO.Recordset

    Dim currentBin As Long
    Dim countInBin As Long

    Dim lastGroupKey As Variant   ' tracks the last "bin group" we were in
    Dim groupKey As Long          ' current row's "bin group" (based on SK2/SK3)

    Dim overrideCode As String

    Set db = CurrentDb

    ' For binning we use a hybrid key:
    '   - Standard LPs (SortKey3 = 10)   => group by SortKey2 (Genre)
    '   - All other media types          => group by SortKey3 (MediaType/bin family)
    '
    ' We implement this directly in the ORDER BY so records are processed
    ' in bin-group order, then AlphaBucket, Artist, AlbumTitle.
Set rs = db.OpenRecordset( _
    "SELECT * FROM Vinyl " & _
    "ORDER BY " & _
    "IIf(Nz(SortKey3,10)=10, Nz(SortKey2,0), Nz(SortKey3,0)), " & _
    "SortName([Artist]), AlbumTitle, Year, MasterKey;", _
    dbOpenDynaset)


    If rs.EOF Then
        GoTo CleanExit
    End If

    currentBin = 1
    countInBin = 0
    lastGroupKey = Null

    rs.MoveFirst
    Do While Not rs.EOF

        ' ===== MediaType-based override (using SortKey3) =====
        ' Values like 11, 14, 15, 17, 20, 21 in SortKey3
        ' get special two-letter bin codes and do NOT consume normal bins.
        overrideCode = GetOverrideBinCode(rs!SortKey3)

        If overrideCode <> "" Then
            rs.Edit
            rs!Bin = Null            ' keep these out of numeric bins
            rs!BinCode = overrideCode
            rs.Update

            rs.MoveNext
            GoTo ContinueLoop        ' skip normal bin logic
        End If

        ' ===== Compute the bin group for this record (normal vinyl flow) =====
        ' Standard LP (SK3 = 10) -> use SortKey2 (Genre)
        ' Special types          -> use SortKey3 (MediaType/bin family)
        If Nz(rs!SortKey3, 10) = 10 Then
            groupKey = Nz(rs!SortKey2, 0)
        Else
            groupKey = Nz(rs!SortKey3, 0)
        End If

        ' ===== When the bin group changes, force a NEW bin =====
        If Not IsNull(lastGroupKey) Then
            If groupKey <> lastGroupKey Then
                currentBin = currentBin + 1
                countInBin = 0
            End If
        End If
        lastGroupKey = groupKey

        ' ===== If current bin is full, move to next bin =====
        If countInBin >= BIN_CAPACITY Then
            currentBin = currentBin + 1
            countInBin = 0
        End If

        ' ===== Assign Bin (continuous, never reset) =====
        rs.Edit
        rs!Bin = currentBin
        ' BinCode for normal vinyl will be handled by FixAlphaBucketAndBinCodeForNulls
        rs.Update

        countInBin = countInBin + 1

        rs.MoveNext
ContinueLoop:
    Loop

CleanExit:
    On Error Resume Next
    If Not rs Is Nothing Then rs.Close
    Set rs = Nothing
    Set db = Nothing
    Exit Sub

ErrHandler:
    MsgBox "Error " & Err.Number & ": " & Err.Description, vbExclamation, "RecalcBucketsAndBins Error"
    Resume CleanExit
End Sub


Public Sub GlobalRebinAndLog(ByVal TriggerSource As String)
    On Error GoTo ErrHandler

    Dim db As DAO.Database
    Dim rs As DAO.Recordset

    Set db = CurrentDb

    ' ===== 1) Ensure snapshot table exists =====
    ' We store old Bin/BinCode for ALL records here.
    On Error Resume Next
    db.Execute _
        "CREATE TABLE tblBinSnapshot (" & _
        "  MasterKey TEXT(10)," & _
        "  OldBin LONG," & _
        "  OldBinCode TEXT(20)" & _
        ");"
    On Error GoTo ErrHandler

    ' Clear any previous snapshot
    db.Execute "DELETE FROM tblBinSnapshot;", dbFailOnError

    ' ===== 2) Snapshot current Bin/BinCode for every record =====
    db.Execute _
        "INSERT INTO tblBinSnapshot (MasterKey, OldBin, OldBinCode) " & _
        "SELECT MasterKey, Bin, BinCode " & _
        "FROM Vinyl;", _
        dbFailOnError

    ' ===== 3) Run full rebin pipeline =====
    ' Rebuild AlphaBucket + BinCode BEFORE + AFTER rebin.
    FixAlphaBucketAndBinCodeForNulls
    RecalcBucketsAndBins TriggerSource
    FixAlphaBucketAndBinCodeForNulls

    ' ===== 4) Compare snapshot vs new state, log any changes =====
    Set rs = db.OpenRecordset( _
        "SELECT V.MasterKey, " & _
        "       S.OldBin, S.OldBinCode, " & _
        "       V.Bin AS NewBin, V.BinCode AS NewBinCode " & _
        "FROM Vinyl AS V " & _
        "LEFT JOIN tblBinSnapshot AS S " & _
        "       ON V.MasterKey = S.MasterKey " & _
        "WHERE Nz(S.OldBin,0) <> Nz(V.Bin,0) " & _
        "   OR Nz(S.OldBinCode,'') <> Nz(V.BinCode,'');", _
        dbOpenSnapshot)

        Do While Not rs.EOF
        On Error Resume Next

        Dim isAdd As Boolean
        isAdd = (Nz(rs!OldBin, 0) = 0 And Len(Nz(rs!OldBinCode, "")) = 0)

        If isAdd Then
            ' New record: no prior bin -> ADD
            LogAdd TriggerSource, _
                   Nz(rs!MasterKey, ""), _
                   rs!NewBin, rs!NewBinCode
        Else
            ' Existing record: moved from old bin -> MOVE
            LogBinMove TriggerSource, _
                       Nz(rs!MasterKey, ""), _
                       rs!OldBin, rs!OldBinCode, _
                       rs!NewBin, rs!NewBinCode
        End If

        On Error GoTo ErrHandler
        rs.MoveNext
    Loop


CleanExit:
    On Error Resume Next
    If Not rs Is Nothing Then rs.Close
    Set rs = Nothing
    Set db = Nothing
    Exit Sub

ErrHandler:
    MsgBox "GlobalRebinAndLog error " & Err.Number & ": " & Err.Description, _
           vbExclamation, "GlobalRebinAndLog"
    Resume CleanExit
End Sub

' SortKey3-based override:
' 10 = normal LPs (no override)
' 11,14,15,17,20,21 = special locations with custom codes
Public Function GetOverrideBinCode(SortKey3 As Variant) As String
    Select Case Nz(SortKey3, 0)
        Case 11          ' Off floor
            GetOverrideBinCode = "OF"
        Case 14          ' Media room
            GetOverrideBinCode = "MR"
        Case 15          ' Media cabinet
            GetOverrideBinCode = "MC"
        Case 17          ' Small storage
            GetOverrideBinCode = "SS"
        Case 20, 21      ' Small cabinet
            GetOverrideBinCode = "SC"
        Case Else
            GetOverrideBinCode = ""   ' No override ? normal bin logic
    End Select
End Function

Public Sub GlobalRebinNoLog(Optional ByVal TriggerSource As String = "EDIT")
    On Error GoTo ErrHandler

    ' Rebuild AlphaBucket + BinCode BEFORE + AFTER rebin.
    FixAlphaBucketAndBinCodeForNulls
    RecalcBucketsAndBins TriggerSource
    FixAlphaBucketAndBinCodeForNulls

    Exit Sub

ErrHandler:
    MsgBox "GlobalRebinNoLog error " & Err.Number & ": " & Err.Description, _
           vbExclamation, "GlobalRebinNoLog"
End Sub

Public Sub GenerateTaskList()
    On Error GoTo ErrHandler

    DoCmd.Hourglass True

    CurrentDb.Execute _
        "UPDATE ChangeLog SET Reviewed = True WHERE Reviewed = False OR Reviewed Is Null;", _
        dbFailOnError

    GlobalRebinAndLog "TASKGEN"

    DoCmd.Hourglass False
    DoCmd.OpenForm "frmRebinTaskList"
    Exit Sub

ErrHandler:
    DoCmd.Hourglass False
    MsgBox "GenerateTaskList error " & Err.Number & ": " & Err.Description, _
           vbExclamation, "Generate Task List"
End Sub




