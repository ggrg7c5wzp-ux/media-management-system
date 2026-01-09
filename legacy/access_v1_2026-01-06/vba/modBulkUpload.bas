Attribute VB_Name = "modBulkUpload"
Option Compare Database
Option Explicit

' ==========================================================
' MasterKey generator
' ==========================================================
Public Function GetNextMasterKey() As String
    ' Returns the next MasterKey using pattern like A1111, A1112, etc.
    ' Assumes MasterKey is 1 letter + 4 digits and stored in Vinyl.MasterKey

    Dim db As DAO.Database
    Dim rs As DAO.Recordset
    Dim lastKey As String
    Dim prefix As String
    Dim num As Long

    Set db = CurrentDb
    Set rs = db.OpenRecordset( _
        "SELECT Max(MasterKey) AS MaxKey " & _
        "FROM Vinyl " & _
        "WHERE MasterKey Is Not Null", dbOpenSnapshot)

    If rs.EOF Or IsNull(rs!MaxKey) Then
        ' No keys yet – start at A1111
        GetNextMasterKey = "A1111"
    Else
        lastKey = rs!MaxKey        ' e.g. "A1347"
        prefix = Left(lastKey, 1)  ' "A"
        num = Val(Mid(lastKey, 2)) ' 1347
        num = num + 1              ' 1348

        ' If we ever overflow A9999, go to B1111, etc.
        If num > 9999 Then
            prefix = Chr(Asc(prefix) + 1)
            num = 1111
        End If

        GetNextMasterKey = prefix & Format(num, "0000")  ' e.g. "A1348"
    End If

    rs.Close
    Set rs = Nothing
    Set db = Nothing
End Function

Public Sub BulkUploadSpecialFromCSV()

    Const msoFileDialogFilePicker As Long = 3   ' avoid Office reference

    Dim fd As Object
    Dim filePath As String
    Dim db As DAO.Database
    Dim rsSrc As DAO.Recordset
    Dim rsDest As DAO.Recordset
    Dim imported As Long
    Dim newKeys As Collection
    Dim newKey As String
    Dim vSpecial As Variant
    Dim sSpecial As String
    Dim vSK3 As Variant          ' *** NEW: to read SortKey3 from staging ***
    
    On Error GoTo ErrHandler

    Set newKeys = New Collection

    '----- 1. Let user pick the CSV file -----
    Set fd = Application.FileDialog(msoFileDialogFilePicker)
    With fd
        .Title = "Select DataUpload CSV file"
        .AllowMultiSelect = False
        .Filters.Clear
        .Filters.Add "CSV Files", "*.csv"
        If .Show <> -1 Then
            Exit Sub   ' user cancelled
        End If
        filePath = .SelectedItems(1)
    End With

    '----- 2. Clear staging table, then import -----
    ' tblBulkUpload must have: Artist, AlbumTitle, SortKey2, Year, Special,
    ' and now also SortKey3 if you want to drive media type from CSV.
    CurrentDb.Execute "DELETE FROM tblBulkUpload", dbFailOnError
    
    DoCmd.TransferText _
        TransferType:=acImportDelim, _
        TableName:="tblBulkUpload", _
        FileName:=filePath, _
        HasFieldNames:=True

    '----- 3. Loop through staging and add to Vinyl -----
    Set db = CurrentDb
    Set rsSrc = db.OpenRecordset("SELECT * FROM tblBulkUpload", dbOpenSnapshot)
    Set rsDest = db.OpenRecordset("Vinyl", dbOpenDynaset)

    Do While Not rsSrc.EOF
        
        ' basic sanity check – require Artist & AlbumTitle
        If Nz(rsSrc!Artist, "") <> "" And Nz(rsSrc!AlbumTitle, "") <> "" Then
        
            ' Generate the MasterKey so we can track it
            newKey = GetNextMasterKey()
            
            rsDest.AddNew
            rsDest!MasterKey = newKey
            rsDest!Artist = rsSrc!Artist
            rsDest!AlbumTitle = rsSrc!AlbumTitle
            
            ' ----- SortKey2 (Genre) -----
            If Not IsNull(rsSrc!SortKey2) Then
                rsDest!SortKey2 = rsSrc!SortKey2
            End If
            
            ' ----- SortKey3 (MediaType / VinylType) – THIS WAS MISSING -----
            ' Try to read from staging. If missing/null/0, default to 10 (Standard LP).
            vSK3 = Null
            On Error Resume Next
            vSK3 = rsSrc!SortKey3      ' requires tblBulkUpload to have a SortKey3 field
            On Error GoTo ErrHandler

            If IsNull(vSK3) Or vSK3 = 0 Then
                rsDest!SortKey3 = 10   ' default media type: Standard LP
            Else
                rsDest!SortKey3 = vSK3
            End If
            ' ---------------------------------------------

            ' Year
            If Not IsNull(rsSrc!Year) Then
                rsDest!Year = rsSrc!Year
            End If
            
            ' ===== Special flag from CSV =====
            vSpecial = Null
            On Error Resume Next        ' in case Special column is missing or typed oddly
            vSpecial = rsSrc!Special
            On Error GoTo ErrHandler

            sSpecial = UCase(Trim(Nz(vSpecial, "")))

            If sSpecial = "YES" Or sSpecial = "Y" Or sSpecial = "TRUE" Or sSpecial = "-1" Or sSpecial = "1" Then
                rsDest!Special = True           ' checkbox checked
            Else
                rsDest!Special = False          ' checkbox not checked
            End If
            
            rsDest.Update

            ' Track this new record for ADD logging
            newKeys.Add newKey

            imported = imported + 1
        End If
        
        rsSrc.MoveNext
    Loop

    rsDest.Close
    rsSrc.Close
    Set rsDest = Nothing
    Set rsSrc = Nothing
    Set db = Nothing

    '----- 4. Log ADD entries for the new records -----
   ' If imported > 0 Then
    '    LogBulkUploadAdds newKeys
    ' End If

    '----- 5. Run GLOBAL REBIN + LOGGING for ALL records -----
    'DoCmd.Hourglass True
    'GlobalRebinAndLog "BULKUPLOAD"
    'DoCmd.Hourglass False

    'MsgBox imported & " records imported, binned, and all bin changes logged.", vbInformation
    'Exit Sub

ErrHandler:
    DoCmd.Hourglass False
    MsgBox "Bulk upload failed: " & Err.Number & " - " & Err.Description, vbExclamation

End Sub




Public Sub FixAlphaBucketAndBinCodeForNulls()

    Dim db As DAO.Database
    Set db = CurrentDb

    ' 1) Recalculate AlphaBucket for ALL rows based on Artist
    '    – First letter of Artist, ignoring "The ", "A ", "An "
db.Execute _
    "UPDATE Vinyl " & _
    "SET AlphaBucket = " & _
    "    IIf(Nz([Artist],'')='', Null, " & _
    "        UCase(Left(SortName([Artist]),1)) " & _
    "    ) " & _
    "WHERE Nz([Artist],'') <> '';", _
    dbFailOnError


    ' 2) Rebuild BinCode for ALL records that have a Bin
    '    – Format: SS-BB-A  (SortKey2, Bin, AlphaBucket)
    db.Execute _
        "UPDATE Vinyl " & _
        "SET BinCode = " & _
        "    Format(Nz([SortKey2],0),'00') & '-' & " & _
        "    Format(Nz([Bin],0),'00') & '-' & " & _
        "    Nz([AlphaBucket],'') " & _
        "WHERE Bin Is Not Null;", _
        dbFailOnError

    Set db = Nothing
End Sub

' ==========================================================
' Log bulk-uploaded records into ChangeLog as ADD only
' (REBIN moves are now logged by GlobalRebinAndLog)
' ==========================================================
Private Sub LogBulkUploadAdds(newKeys As Collection)
    On Error GoTo ErrHandler

    Dim db As DAO.Database
    Dim rsLog As DAO.Recordset
    Dim rsVin As DAO.Recordset
    Dim i As Long
    Dim mk As String
    Dim vYear As Variant
    Dim vBin As Variant
    Dim vBinCode As String
    Dim vArtist As String
    Dim vAlbum As String
    Dim sql As String

    If newKeys Is Nothing Then Exit Sub
    If newKeys.Count = 0 Then Exit Sub

    Set db = CurrentDb
    Set rsLog = db.OpenRecordset("ChangeLog", dbOpenDynaset)

    For i = 1 To newKeys.Count
        mk = CStr(newKeys(i))

        sql = "SELECT MasterKey, Artist, AlbumTitle, [Year], Bin, BinCode " & _
              "FROM Vinyl WHERE MasterKey = '" & Replace(mk, "'", "''") & "';"

        Set rsVin = db.OpenRecordset(sql, dbOpenSnapshot)

        If Not rsVin.EOF Then
            ' Cache values from Vinyl
            vArtist = Nz(rsVin!Artist, "")
            vAlbum = Nz(rsVin!AlbumTitle, "")

            If IsNull(rsVin![Year]) Then
                vYear = Null
            Else
                vYear = rsVin![Year]
            End If

            vBin = Nz(rsVin!Bin, 0)
            vBinCode = Nz(rsVin!BinCode, "")

            ' ---------- ADD entry ONLY ----------
            rsLog.AddNew
                rsLog!ChangeDate = Now()
                rsLog!ChangeType = "ADD"
                rsLog!MasterKey = rsVin!MasterKey
                rsLog!Artist = vArtist
                rsLog!AlbumTitle = vAlbum
                rsLog!Year = vYear
                rsLog!Bin = vBin
                rsLog!BinCode = vBinCode
                On Error Resume Next
                rsLog!UserName = Environ$("Username")
                On Error GoTo ErrHandler
            rsLog.Update
        End If

        rsVin.Close
        Set rsVin = Nothing
    Next

Cleanup:
    On Error Resume Next
    If Not rsLog Is Nothing Then rsLog.Close
    Set rsLog = Nothing
    Set db = Nothing
    Exit Sub

ErrHandler:
    Debug.Print "LogBulkUploadAdds error " & Err.Number & " - " & Err.Description
    Resume Cleanup
End Sub




