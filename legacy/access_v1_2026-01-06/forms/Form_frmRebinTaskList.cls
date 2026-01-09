VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Form_frmRebinTaskList"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Compare Database

Private Sub cmdMarkAll_Click()
    On Error GoTo ErrHandler

    ' Confirm the user really wants to mark everything
    If MsgBox("This will mark ALL unreviewed rebin changes as complete." & vbCrLf & _
              "Only NEW changes will appear in the list." & vbCrLf & vbCrLf & _
              "Proceed?", vbYesNo + vbQuestion, "Mark All Complete") <> vbYes Then
        Exit Sub
    End If

    ' Update all ChangeLog entries that are not yet reviewed
    CurrentDb.Execute _
        "UPDATE ChangeLog SET Reviewed = True WHERE Reviewed = False OR Reviewed Is Null;", _
        dbFailOnError

    ' Refresh the form so the list clears
    Me.Requery

    MsgBox "All tasks have been marked as complete.", vbInformation, "Completed"

    Exit Sub

ErrHandler:
    MsgBox "Error marking all complete: " & Err.Number & " - " & Err.Description, _
           vbExclamation, "Error"
End Sub


Private Sub cmdMarkReviewed_Click()
    On Error GoTo ErrHandler

    ' Don’t do anything on a new/blank row
    If Me.NewRecord Then Exit Sub

    ' We need a LogID from the current record
    If IsNull(Me!LogID) Then
        MsgBox "No LogID found for the current row.", vbExclamation, "Cannot Mark"
        Exit Sub
    End If

    Dim db As DAO.Database
    Dim sql As String

    sql = "UPDATE ChangeLog SET Reviewed = True WHERE LogID = " & Me!LogID

    Set db = CurrentDb
    db.Execute sql, dbFailOnError

    ' Refresh the form so this row disappears (since Reviewed = False is required in the query)
    Me.Requery

    MsgBox "Marked this change as reviewed. Only remaining changes are shown.", _
           vbInformation, "Change Reviewed"

CleanExit:
    Set db = Nothing
    Exit Sub

ErrHandler:
    MsgBox "Error marking change as reviewed: " & Err.Number & " - " & Err.Description, _
           vbExclamation, "Error"
    Resume CleanExit
End Sub
Private Sub cmdRefresh_Click()
    On Error GoTo ErrHandler

    Me.Requery          ' Reloads the form’s recordsource (qryRebinTaskList)

    Exit Sub

ErrHandler:
    MsgBox "Error refreshing task list: " & Err.Number & " - " & Err.Description, _
           vbExclamation, "Refresh Error"
End Sub



