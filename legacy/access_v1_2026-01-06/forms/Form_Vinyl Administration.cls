VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Form_Vinyl Administration"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Compare Database
Option Explicit

Private Sub AddRecord_Click()
    ' Open LoadForm in Add (DataEntry) mode – blank new record
    DoCmd.OpenForm "LoadForm", DataMode:=acFormAdd
End Sub

Private Sub cboFindRecord_AfterUpdate()
    Dim selectedKey As String
    
    ' cboFindRecord is bound to MasterKey because it's the first field in Row Source
    selectedKey = Nz(Me!cboFindRecord, "")
    
    If selectedKey = "" Then
        Exit Sub
    End If
    
    ' Debug: show what we're about to open
    MsgBox "Opening LoadForm for MasterKey: " & selectedKey, vbInformation, "Debug"
    
    ' Open LoadForm filtered to that MasterKey
    DoCmd.OpenForm "LoadForm", DataMode:=acFormEdit, _
                   WhereCondition:="MasterKey = '" & selectedKey & "'"
End Sub

Private Sub cmdTestLoadForm_Click()
    DoCmd.OpenForm "LoadForm", DataMode:=acFormEdit
End Sub


Private Sub cmdOpenEarlyWarning2_Click()
    On Error GoTo ErrHandler

    DoCmd.OpenQuery "qryEarlyWarningSystem", acViewNormal, acReadOnly
    Exit Sub

ErrHandler:
    MsgBox "Early Warning failed: " & Err.Number & " - " & Err.Description, vbExclamation
End Sub


Private Sub cmdSearch_Click()
    Dim sInput As String
    Dim sPattern As String
    Dim sCriteria As String
    Dim sSQL As String

    sInput = Trim(Nz(Me.txtSearch, ""))

    If sInput = "" Then
        ' If blank, reset Combo14 to show ALL records
        sSQL = "SELECT MasterKey, Artist, AlbumTitle, Year " & _
               "FROM Vinyl " & _
               "ORDER BY Artist, AlbumTitle;"
        Me.Combo14.RowSource = sSQL
        Me.Combo14.Requery
        MsgBox "Search cleared. Full list restored.", vbInformation, "Search"
        Exit Sub
    End If

    ' If user typed * or ? use it directly, otherwise do a contains search
    If InStr(sInput, "*") > 0 Or InStr(sInput, "?") > 0 Then
        sPattern = sInput
    Else
        sPattern = "*" & sInput & "*"
    End If

    ' Escape single quotes
    sPattern = Replace(sPattern, "'", "''")

    ' Build WHERE clause across multiple fields
    sCriteria = "Artist LIKE '" & sPattern & "'" & _
                " OR AlbumTitle LIKE '" & sPattern & "'" & _
                " OR MasterKey LIKE '" & sPattern & "'" & _
                " OR Year LIKE '" & sPattern & "'"

    ' Build filtered RowSource for Combo14
    sSQL = "SELECT MasterKey, Artist, AlbumTitle, Year " & _
           "FROM Vinyl " & _
           "WHERE " & sCriteria & _
           " ORDER BY Artist, AlbumTitle;"

    ' Apply to Combo14 and refresh the list
    Me.Combo14.RowSource = sSQL
    Me.Combo14 = Null
    Me.Combo14.Requery

       ' If no rows match, Combo14 will be empty
    If Me.Combo14.ListCount = 0 Then
        MsgBox "No records found matching: " & sInput, _
               vbInformation, "Search"
    Else
        ' Give Combo14 focus, then drop the list so you can see matches
        Me.Combo14.SetFocus
        Me.Combo14.Dropdown
    End If
End Sub




Private Sub cmdBulkUploadSpecial2_Click()
    Call BulkUploadSpecialFromCSV
End Sub

Private Sub cmdForceRebin_Click()
    On Error GoTo ErrHandler

    If MsgBox("Generate a fresh Task List of physical moves based on current data?", _
              vbQuestion + vbYesNo, "Generate Task List") <> vbYes Then
        Exit Sub
    End If

    GenerateTaskList
    Exit Sub

ErrHandler:
    MsgBox "Error " & Err.Number & ": " & Err.Description, _
           vbExclamation, "Generate Task List"
End Sub





Private Sub cmdResetBaseline_Click()
    On Error GoTo ErrHandler
    
    Dim db As DAO.Database
    Set db = CurrentDb

    ' Confirm with user
    If MsgBox("This will reset your baseline and clear all completed rebin tasks." & vbCrLf & _
              "Only NEW moves after this moment will appear in the task list." & vbCrLf & vbCrLf & _
              "Proceed?", _
              vbQuestion + vbYesNo, "Reset Rebin Baseline") <> vbYes Then
        Exit Sub
    End If

    ' Update the baseline table
    db.Execute "UPDATE tblRebinBaseline SET BaselineDate = Now();", dbFailOnError

    MsgBox "Baseline reset. Only future REBIN/DELETE entries will appear in the task list.", _
           vbInformation, "Baseline Updated"

    ' Requery the form if it's open
    Me.Requery

ExitHere:
    Set db = Nothing
    Exit Sub

ErrHandler:
    MsgBox "Error resetting baseline: " & Err.Number & " - " & Err.Description, vbExclamation
    Resume ExitHere
End Sub


Private Sub Combo14_AfterUpdate()
    Dim selectedKey As String
    
    ' Combo14 is bound to MasterKey (first field in Row Source)
    selectedKey = Nz(Me!Combo14, "")
    
    If selectedKey = "" Then
        Exit Sub
    End If
    
    ' Debug: prove we have a key and the event is firing
    MsgBox "Opening LoadForm for MasterKey: " & selectedKey, vbInformation, "Debug"
    
    ' Open LoadForm filtered to that MasterKey
    DoCmd.OpenForm "LoadForm", DataMode:=acFormEdit, _
                   WhereCondition:="MasterKey = '" & selectedKey & "'"
End Sub




Private Sub cmdBulkUploadSpecial_Click()
    Call BulkUploadSpecialFromCSV
End Sub


