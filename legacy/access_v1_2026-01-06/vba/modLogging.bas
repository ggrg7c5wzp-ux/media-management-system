Attribute VB_Name = "modLogging"
Option Explicit

' ==========================================================
' PRIVATE: Core logging helper – writes a row to ChangeLog
' ==========================================================
Private Sub WriteChangeLog( _
        ByVal ChangeType As String, _
        ByVal TriggerMasterKey As String, _
        ByVal AffectedMasterKey As String, _
        ByVal OldBin As Variant, _
        ByVal OldBinCode As Variant, _
        ByVal NewBin As Variant, _
        ByVal NewBinCode As Variant)

    On Error GoTo ErrHandler

    Dim db As DAO.Database
    Dim rsLog As DAO.Recordset
    Dim rsVin As DAO.Recordset

    Dim sTrigger As String
    Dim sArtist As String
    Dim sAlbum As String
    Dim vYear As Variant

    Dim currentBin As Variant
    Dim currentBinCode As Variant

    Set db = CurrentDb()

    ' ----- Normalize trigger (we'll store this in UserName) -----
    sTrigger = Trim$(Nz(TriggerMasterKey, ""))
    If sTrigger = "" Then
        sTrigger = "(UNKNOWN)"
    End If

    ' ----- Default normalization for bin values -----
    If IsNull(OldBin) Then OldBin = 0
    If IsNull(NewBin) Then NewBin = 0
    If IsNull(OldBinCode) Then OldBinCode = ""
    If IsNull(NewBinCode) Then NewBinCode = ""

    ' ----- Look up Vinyl metadata (Artist/Album/Year + current Bin/BinCode) -----
    sArtist = ""
    sAlbum = ""
    vYear = Null
    currentBin = 0
    currentBinCode = ""

    If Len(Trim$(Nz(AffectedMasterKey, ""))) > 0 Then
        Set rsVin = db.OpenRecordset( _
            "SELECT Artist, AlbumTitle, [Year], Bin, BinCode " & _
            "FROM Vinyl " & _
            "WHERE MasterKey = '" & Replace(AffectedMasterKey, "'", "''") & "'", _
            dbOpenSnapshot)

        If Not (rsVin.BOF And rsVin.EOF) Then
            sArtist = Nz(rsVin!Artist, "")
            sAlbum = Nz(rsVin!AlbumTitle, "")
            vYear = rsVin!Year
            currentBin = Nz(rsVin!Bin, 0)
            currentBinCode = Nz(rsVin!BinCode, "")
        End If

        rsVin.Close
        Set rsVin = Nothing
    End If

    ' ----- If NewBin/NewBinCode weren’t really provided (0 / blank), use Vinyl values -----
    If Nz(NewBin, 0) = 0 And Len(Nz(NewBinCode, "")) = 0 Then
        NewBin = currentBin
        NewBinCode = currentBinCode
    End If

    ' ----- FINAL debug snapshot of what we’re about to log -----
    Debug.Print "WriteChangeLog:", _
                "Type=" & ChangeType, _
                "Trig=" & sTrigger, _
                "Aff=" & AffectedMasterKey, _
                "OldBin=" & Nz(OldBin, 0), _
                "OldBinCode='" & Nz(OldBinCode, "") & "'", _
                "NewBin=" & Nz(NewBin, 0), _
                "NewBinCode='" & Nz(NewBinCode, "") & "'"

    ' ----- Open ChangeLog and append row -----
    ' ChangeLog fields:
    '   ChangeDate, ChangeType, MasterKey, Artist, AlbumTitle, Year,
    '   UserName, Notes, OldBin, OldBinCode, Bin, BinCode
    Set rsLog = db.OpenRecordset("ChangeLog", dbOpenDynaset)

    With rsLog
        .AddNew

        .Fields("ChangeDate").Value = Now()
        .Fields("ChangeType").Value = ChangeType

        ' We treat AffectedMasterKey as the MasterKey for the row
        .Fields("MasterKey").Value = AffectedMasterKey

        .Fields("Artist").Value = sArtist
        .Fields("AlbumTitle").Value = sAlbum
        .Fields("Year").Value = vYear

        ' Store who/what triggered this in UserName
        .Fields("UserName").Value = sTrigger

        .Fields("OldBin").Value = OldBin
        .Fields("OldBinCode").Value = OldBinCode

        ' Your table uses Bin / BinCode for the *new* bin values
        .Fields("Bin").Value = NewBin
        .Fields("BinCode").Value = NewBinCode
        .Fields("Notes").Value = BuildNotes(ChangeType, OldBin, OldBinCode, NewBin, NewBinCode)

        ' New: every new log row starts unreviewed
        .Fields("Reviewed").Value = False

        .Update

    End With

CleanExit:
    On Error Resume Next
    If Not rsLog Is Nothing Then rsLog.Close
    If Not rsVin Is Nothing Then rsVin.Close
    Set rsLog = Nothing
    Set rsVin = Nothing
    Set db = Nothing
    Exit Sub

ErrHandler:
    Debug.Print "WriteChangeLog error " & Err.Number & ": " & Err.Description
    Resume CleanExit
End Sub

' ==========================================================
' PRIVATE: Builds a human-readable Notes string
' ==========================================================
Private Function BuildNotes( _
        ByVal ChangeType As String, _
        ByVal OldBin As Variant, _
        ByVal OldBinCode As Variant, _
        ByVal NewBin As Variant, _
        ByVal NewBinCode As Variant) As String

    Dim isAdd As Boolean

    ' Treat any change with no real old bin as an "Add"
    isAdd = (Nz(OldBin, 0) = 0 And Len(Nz(OldBinCode, "")) = 0)

    If isAdd Then
        BuildNotes = "Add to Bin " & Nz(NewBin, "0") & " (" & Nz(NewBinCode, "") & ")."
    Else
        BuildNotes = "Move from Bin " & Nz(OldBin, "0") & " (" & Nz(OldBinCode, "") & _
                     ") to Bin " & Nz(NewBin, "0") & " (" & Nz(NewBinCode, "") & ")."
    End If
End Function


' ==========================================================
' PUBLIC API – these are what your other code calls
' ==========================================================

' Log a move / rebin operation
' (Same signature you were using before.)
Public Sub LogBinMove( _
        ByVal TriggerMasterKey As String, _
        ByVal AffectedMasterKey As String, _
        ByVal OldBin As Variant, _
        ByVal OldBinCode As Variant, _
        ByVal NewBin As Variant, _
        ByVal NewBinCode As Variant)

    Debug.Print "LogBinMove called:", _
                "Trig=" & TriggerMasterKey, _
                "Aff=" & AffectedMasterKey, _
                "OldBin=" & Nz(OldBin, 0), _
                "OldBinCode='" & Nz(OldBinCode, "") & "'", _
                "NewBin=" & Nz(NewBin, 0), _
                "NewBinCode='" & Nz(NewBinCode, "") & "'"

    Call WriteChangeLog("MOVE", _
                        TriggerMasterKey, AffectedMasterKey, _
                        OldBin, OldBinCode, _
                        NewBin, NewBinCode)
End Sub

' Optional: log a brand-new vinyl being added
' Call this AFTER your bin-calculation routine, so NewBin/NewBinCode are final.
Public Sub LogAdd( _
        ByVal TriggerMasterKey As String, _
        ByVal AffectedMasterKey As String, _
        ByVal NewBin As Variant, _
        ByVal NewBinCode As Variant)

    Debug.Print "LogAdd called:", _
                "Trig=" & TriggerMasterKey, _
                "Aff=" & AffectedMasterKey, _
                "NewBin=" & Nz(NewBin, 0), _
                "NewBinCode='" & Nz(NewBinCode, "") & "'"

    Call WriteChangeLog("ADD", _
                        TriggerMasterKey, AffectedMasterKey, _
                        0, "", _
                        NewBin, NewBinCode)
End Sub

' Optional: log a vinyl being deleted
Public Sub LogDelete( _
        ByVal TriggerMasterKey As String, _
        ByVal AffectedMasterKey As String, _
        ByVal OldBin As Variant, _
        ByVal OldBinCode As Variant)

    Debug.Print "LogDelete called:", _
                "Trig=" & TriggerMasterKey, _
                "Aff=" & AffectedMasterKey, _
                "OldBin=" & Nz(OldBin, 0), _
                "OldBinCode='" & Nz(OldBinCode, "") & "'"

    Call WriteChangeLog("DELETE", _
                        TriggerMasterKey, AffectedMasterKey, _
                        OldBin, OldBinCode, _
                        0, "")
End Sub




